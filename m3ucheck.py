import asyncio
import aiohttp
import re
import datetime
import requests
import time
import threading
from queue import Queue
from collections import defaultdict
from typing import Dict, List, Optional, Any
import numpy as np
from urllib.parse import urlparse, urljoin
import logging
import atexit

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# 全局Session管理
_global_session = None

def get_session():
    """获取全局Session，使用上下文管理器确保资源正确释放"""
    global _global_session
    if _global_session is None:
        _global_session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20, 
            pool_maxsize=50,
            max_retries=3
        )
        _global_session.mount('http://', adapter)
        _global_session.mount('https://', adapter)
        # 注册清理函数
        atexit.register(cleanup_session)
    return _global_session

def cleanup_session():
    """清理全局Session"""
    global _global_session
    if _global_session:
        _global_session.close()
        _global_session = None

class TSStreamChecker:
    """TS流检测器，通过解析TS包数据来检测流的稳定性和响应时间"""
    
    def __init__(self, 
                 buffer_size: int = 8192, 
                 check_duration: int = 5,
                 response_time_threshold: int = 120,  # 响应时间阈值(毫秒)
                 request_timeout: int = 5,            # 请求超时时间(秒)
                 max_history_size: int = 20):         # 最大历史记录数量，防止内存泄露
        """
        TS流检测模块初始化
        :param buffer_size: 接收缓冲区大小
        :param check_duration: 每个TS流检测持续时间（秒）
        :param response_time_threshold: 响应时间阈值（毫秒），低于此值视为合格
        :param request_timeout: HTTP请求超时时间（秒）
        :param max_history_size: 最大历史记录数量，防止内存累积
        """
        self.buffer_size = buffer_size
        self.check_duration = check_duration
        self.response_time_threshold = response_time_threshold
        self.request_timeout = request_timeout
        self.max_history_size = max_history_size
        
        # 存储每个PID的连续性计数器
        self.pid_continuity: Dict[int, int] = defaultdict(int)
        # 统计信息 - 使用限制大小防止内存泄露
        self.stats: Dict[str, Any] = {
            "total_packets": 0,
            "invalid_packets": 0,
            "lost_packets": 0,
            "rate_history": [],
            "interval_history": [],
            "response_times": []
        }
        self.last_check_time = time.time()
        self.packets_in_window = 0
        self.last_packet_time: Optional[float] = None
        self.current_position = 0  # HTTP流当前位置，用于断点续传
    
    def _add_response_time(self, response_time: float):
        """添加响应时间，限制历史记录大小防止内存泄露"""
        self.stats["response_times"].append(response_time)
        if len(self.stats["response_times"]) > self.max_history_size:
            self.stats["response_times"].pop(0)
    
    def _reset_stats(self):
        """重置统计信息"""
        self.stats = {
            "total_packets": 0,
            "invalid_packets": 0,
            "lost_packets": 0,
            "rate_history": [],
            "interval_history": [],
            "response_times": []
        }
        self.pid_continuity.clear()
        self.current_position = 0
        self.last_check_time = time.time()
        self.packets_in_window = 0
        self.last_packet_time = None



    def parse_ts_packet(self, packet: bytes) -> Optional[Dict[str, Any]]:
        """解析TS包，提取关键信息"""
        if len(packet) != 188:  # 标准TS包长度为188字节
            return None
        
        # 检查同步字节（必须为0x47）
        sync_byte = packet[0]
        if sync_byte != 0x47:
            return None
        
        # 提取PID（13位）
        pid_bytes = packet[1:3]
        pid = (pid_bytes[0] & 0x1F) << 8 | pid_bytes[1]
        
        # 提取连续性计数器（4位）
        continuity_counter = (packet[3] & 0x0F)
        
        return {
            "pid": pid,
            "continuity": continuity_counter,
            "valid": True
        }

    def check_continuity(self, pid: int, current_counter: int) -> int:
        """检查PID对应的包连续性"""
        last_counter = self.pid_continuity.get(pid, -1)
        if last_counter == -1:
            self.pid_continuity[pid] = current_counter
            return 0
        
        # 计算理论上的下一个计数器值（循环16进制）
        expected = (last_counter + 1) % 16
        lost = (current_counter - expected) % 16
        
        if lost > 0:
            self.stats["lost_packets"] += lost
        
        self.pid_continuity[pid] = current_counter
        return lost

    def update_rate(self) -> None:
        """更新传输速率（包/秒）"""
        current_time = time.time()
        elapsed = current_time - self.last_check_time
        
        if elapsed >= 1.0:  # 每秒更新一次速率
            rate = self.packets_in_window / elapsed if elapsed > 0 else 0.0
            self.stats["rate_history"].append(rate)
            # 保留最近5个窗口的速率，防止内存泄露
            if len(self.stats["rate_history"]) > 5:
                self.stats["rate_history"].pop(0)
            
            self.last_check_time = current_time
            self.packets_in_window = 0

    def update_interval(self, current_time: float) -> None:
        """记录包间隔时间"""
        if self.last_packet_time is not None:
            interval = current_time - self.last_packet_time
            self.stats["interval_history"].append(interval)
            # 保留最近100个间隔，防止内存泄露
            if len(self.stats["interval_history"]) > 100:
                self.stats["interval_history"].pop(0)
        self.last_packet_time = current_time

    def _evaluate_result(self) -> bool:
        """评估检测结果，返回是否稳定且响应时间小于设定阈值"""
        if len(self.stats["rate_history"]) < 3:  # 至少需要3个速率样本
            return False
        
        # 计算指标
        rate_std = np.std(self.stats["rate_history"])
        loss_rate = self.stats["lost_packets"] / self.stats["total_packets"] if self.stats["total_packets"] > 0 else 0.0
        avg_response_time = np.mean(self.stats["response_times"]) if self.stats["response_times"] else float('inf')
        
        # 判断条件：速率稳定且响应时间小于设定阈值
        is_stable = rate_std < 5 and loss_rate < 0.01
        is_fast_response = avg_response_time < self.response_time_threshold
        
        logger.info(f"TS流检测结果 - 速率稳定性: {rate_std:.2f}, 丢包率: {loss_rate:.4f}, 平均响应时间: {avg_response_time:.2f} ms")
        
        return is_stable and is_fast_response

    def _check_ts_stream(self, url: str) -> bool:
        """检测单个TS流的内部方法，返回检测结果"""
        self._reset_stats()
        start_time = time.time()
        
        try:
            parsed_url = urlparse(url)
            if parsed_url.scheme not in ['http', 'https']:
                return False

            session = get_session()
            
            while (time.time() - start_time) < self.check_duration:
                # 检查是否已超时
                elapsed = time.time() - start_time
                if elapsed >= self.check_duration:
                    break

                # 记录请求开始时间
                req_start_time = time.time()
                
                # 设置Range头，支持断点续传
                headers = {"Range": f"bytes={self.current_position}-"} if self.current_position > 0 else {}
                
                try:
                    # 发送HTTP GET请求，流式获取数据
                    response = session.get(url, headers=headers, stream=True, timeout=self.request_timeout)
                    response.raise_for_status()
                    
                    # 计算响应时间（毫秒） - 这里的响应时间是获取TS数据的时间
                    response_time = (time.time() - req_start_time) * 1000
                    self._add_response_time(response_time)
                    
                    # 处理接收到的TS数据流
                    buffer = b""
                    chunk_count = 0
                    
                    try:
                        for chunk in response.iter_content(chunk_size=self.buffer_size):
                            # 检查是否需要停止
                            if (time.time() - start_time) >= self.check_duration:
                                break
                                
                            if chunk:
                                buffer += chunk
                                chunk_count += 1
                                
                                # 按188字节分割TS包
                                while len(buffer) >= 188:
                                    packet = buffer[:188]
                                    buffer = buffer[188:]
                                    self.current_position += 188
                                    self.stats["total_packets"] += 1
                                    
                                    current_time = time.time()
                                    
                                    # 解析并检查TS包
                                    parsed = self.parse_ts_packet(packet)
                                    if not parsed:
                                        self.stats["invalid_packets"] += 1
                                        continue
                                    
                                    # 检查连续性
                                    self.check_continuity(parsed["pid"], parsed["continuity"])
                                    # 更新时间间隔
                                    self.update_interval(current_time)
                                    # 计数当前窗口包数
                                    self.packets_in_window += 1
                                
                                # 更新速率
                                self.update_rate()
                                
                                # 防止无限循环，如果收到足够数据则继续下一次请求
                                if chunk_count > 10:  # 收到一定数量的数据块后继续
                                    break
                    
                    except Exception as stream_e:
                        logger.debug(f"数据流处理异常: {str(stream_e)}")
                        continue
                    
                    finally:
                        # 确保关闭响应流
                        response.close()

                except requests.exceptions.RequestException as e:
                    logger.debug(f"请求失败: {str(e)}，继续检测...")
                    continue
                except Exception as e:
                    logger.error(f"请求异常: {str(e)}")
                    continue

        except Exception as e:
            logger.debug(f"TS流检测异常: {str(e)}")
            return False
            
        # 评估最终结果
        return self._evaluate_result()

    def check_stream(self, url: str) -> bool:
        """
        检测流是否稳定且响应时间小于设定阈值
        支持TS流和M3U/M3U8索引文件，自动识别
        :return: 稳定且响应快返回True，否则返回False
        """
        # 判断是否为M3U或M3U8文件
        lower_url = url.lower()
        if lower_url.endswith(('.m3u', '.m3u8')):
            logger.info(f"检测到{lower_url.split('.')[-1].upper()}文件，正在解析TS片段...")
            ts_urls = self.parse_playlist(url)
            
            if not ts_urls:
                logger.debug("未找到有效的TS片段")
                return False
                
            logger.info(f"找到{len(ts_urls)}个TS片段，开始检测...")
            results = []
            
            # 检测每个TS片段
            for i, ts_url in enumerate(ts_urls, 1):
                logger.info(f"正在检测第{i}个TS片段: {ts_url}")
                result = self._check_ts_stream(ts_url)
                results.append(result)
                logger.info(f"第{i}个TS片段检测结果: {'合格' if result else '不合格'}")
                
            # 多数合格则认为整体合格
            qualified_count = sum(results)
            total_count = len(results)
            logger.info(f"检测完成，{qualified_count}/{total_count}个TS片段合格")
            return qualified_count > total_count / 2
        else:
            # 直接检测TS流
            return self._check_ts_stream(url)

    def parse_playlist(self, url: str) -> List[str]:
        """解析M3U/M3U8播放列表，获取TS片段地址，支持HTTP和HTTPS"""
        try:
            session = get_session()
            response = session.get(url, timeout=self.request_timeout)
            response.raise_for_status()
            
            ts_urls = []
            base_url = url.rsplit('/', 1)[0] + '/' if '/' in url else url
            
            for line in response.text.splitlines():
                line = line.strip()
                if line and not line.startswith('#'):
                    if line.startswith(('http://', 'https://')):
                        # 已经是完整URL
                        ts_urls.append(line)
                    else:
                        # 相对路径，拼接成完整URL
                        ts_url = urljoin(base_url, line)
                        ts_urls.append(ts_url)
            
            # 去重并返回前5个TS片段地址（避免过多片段检测耗时）
            unique_ts_urls = list(dict.fromkeys(ts_urls))
            return unique_ts_urls[:5]
        except Exception as e:
            logger.debug(f"解析播放列表失败: {e}")
            return []

def clean_channel_name(name):
    """清理频道名称，统一格式"""
    # 将名称转换为大写
    name = name.upper()
    # 定义所有替换规则
    replacement_rules = {
        # 基础清理规则
        "basic": {
            "cctv": "CCTV", 
            "中央": "CCTV", 
            "央视": "CCTV",
            "高清": "", 
            "超高": "", 
            "HD": "", 
            "标清": "",
            "频道": "", 
            "快乐购":"",
            "*": "", 
            "-": "", 
            " ": "", 
            "PLUS": "+", 
            "＋": "+",
            "(": "", 
            ")": "",
            "超":"",
            "KAKU少儿"："卡酷动画",
            "卡通动画": "卡酷动画",
            "酷卡动画": "卡酷动画",
            "北京少儿": "卡酷动画",
            "北京卡通": "卡酷动画",
            "嘉佳卡": "嘉佳卡通",

        },
        # CCTV频道专用替换规则
        "cctv_channels": {
            "CCTV1综合": "CCTV1",
            "CCTV2财经": "CCTV2", 
            "CCTV3综艺": "CCTV3",
            "CCTV4国际": "CCTV4", 
            "CCTV4中文国际": "CCTV4", 
            "CCTV4欧洲": "CCTV4",
            "CCTV5体育": "CCTV5", 
            "CCTV6电影": "CCTV6", 
            "CCTV7军事": "CCTV7",
            "CCTV7军农": "CCTV7", 
            "CCTV7农业": "CCTV7", 
            "CCTV7国防军事": "CCTV7",
            "CCTV17军事": "CCTV7",
            "CCTV8电视剧": "CCTV8", 
            "CCTV9记录": "CCTV9", 
            "CCTV9纪录": "CCTV9",
            "CCTV10科教": "CCTV10", 
            "CCTV11戏曲": "CCTV11", 
            "CCTV12社会与法": "CCTV12",
            "CCTV13新闻": "CCTV13", 
            "CCTV新闻": "CCTV13", 
            "CCTV14少儿": "CCTV14",
            "CCTV15音乐": "CCTV15", 
            "CCTV16奥林匹克": "CCTV16",
            "CCTV17农业农村": "CCTV17", 
            "CCTV17农业": "CCTV17",
            "CCTV5+体育赛视": "CCTV5+", 
            "CCTV5+体育赛事": "CCTV5+", 
            "CCTV5+体育": "CCTV5+"
        }
    }
    
    # 正则替换规则
    regex_rules = [
        (r"CCTV(\d+)台", r"CCTV\1")
    ]
    
    # 执行所有替换规则
    for rule_type, rules in replacement_rules.items():
        for old, new in rules.items():
            name = name.replace(old, new)
    
    # 执行正则替换
    for pattern, replacement in regex_rules:
        name = re.sub(pattern, replacement, name)
    
    return name

urls = [
"http://1.87.218.1:7878",
"http://1.195.130.1:9901",
"http://1.195.131.1:9901",
"http://1.197.250.1:9901",
"http://39.152.171.1:9901",
"http://47.109.181.1:88",
"http://47.116.70.1:9901",
"http://49.232.48.1:9901",
"http://58.19.133.1:9901",
"http://58.57.40.1:9901",
"http://59.38.45.1:8090",
"http://60.255.47.1:8801",
"http://61.136.172.1:9901",
"http://61.156.228.1:8154",
"http://101.66.194.1:9901",
"http://101.66.195.1:9901",
"http://101.66.198.1:9901",
"http://101.66.199.1:9901",
"http://101.74.28.1:9901",
"http://103.39.222.1:9999",
"http://106.42.34.1:888",
"http://106.42.35.1:888",
"http://106.118.70.1:9901",
"http://110.253.83.1:888",
"http://111.8.242.1:8085",
"http://111.9.163.1:9901",
"http://112.14.1:9901",
"http://112.16.14.1:9901",
"http://112.26.18.1:9901",
"http://112.27.145.1:9901",
"http://112.91.103.1:9919",
"http://112.99.193.1:9901",
"http://112.234.23.1:9901",
"http://112.132.160.1:9901",
"http://113.57.93.1:9900",
"http://113.195.162.1:9901",
"http://113.201.61.1:9901",
"http://115.48.160.1:9901",
"http://115.59.9.1:9901",
"http://116.128.242.1:9901",
"http://117.174.99.1:9901",
"http://119.125.131.1:9901",
"http://121.19.134.1:808",
"http://121.29.191.1:8000",
"http://121.43.180.1:9901",
"http://121.56.39.1:808",
"http://122.227.100.1:9901",
"http://123.13.247.1:7000",
"http://123.54.220.1:9901",
"http://123.129.70.1:9901",
"http://123.130.84.1:8154",
"http://123.139.57.1:9901",
"http://123.182.60.1:9002",
"http://124.152.247.1:2001",
"http://125.42.148.1:9901",
"http://125.42.228.1:9999",
"http://125.43.244.1:9901",
"http://125.125.236.1:9901",
"http://159.75.75.1:8888",
"http://171.9.68.1:8099",
"http://180.213.174.1:9901",
"http://182.114.48.1:9901",
"http://182.114.49.1:9901",
"http://182.114.214.1:9901",
"http://182.120.229.1:9901",
"http://183.10.180.1:9901",
"http://183.131.246.1:9901",
"http://183.166.62.1:81",
"http://183.255.41.1:9901",
"http://211.142.224.1:2023",
"http://218.13.170.1:9901",
"http://218.77.81.1:9901",
"http://218.87.237.1:9901",
"http://220.248.173.1:9901",
"http://221.2.148.1:8154",
"http://221.13.235.1:9901",
"http://222.172.183.1:808",
"http://222.243.221.1:9901",
"http://223.241.247.1:9901"
]

async def modify_urls(url):
    modified_urls = []
    ip_start_index = url.find("//") + 2
    ip_end_index = url.find(":", ip_start_index)
    base_url = url[:ip_start_index]
    ip_address = url[ip_start_index:ip_end_index]
    port = url[ip_end_index:]
    ip_end = "/iptv/live/1000.json?key=txiptv"
    for i in range(1, 254):
        modified_ip = f"{ip_address[:-1]}{i}"
        modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
        modified_urls.append(modified_url)
    return modified_urls

async def is_url_accessible(session, url, semaphore):
    async with semaphore:
        try:
            timeout = aiohttp.ClientTimeout(total=5)  # 按规范设置5秒超时
            async with session.get(url, timeout=timeout) as response:
                if response.status == 200:
                    logger.info(f"发现可用URL: {url}")
                    return url
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug(f"URL不可访问: {url}, 错误: {str(e)}")
        except Exception as e:
            logger.debug(f"检测URL时发生异常: {url}, 错误: {str(e)}")
    return None

async def check_urls(session, urls, semaphore):
    tasks = []
    for url in urls:
        url = url.strip()
        modified_urls = await modify_urls(url)
        for modified_url in modified_urls:
            task = asyncio.create_task(is_url_accessible(session, modified_url, semaphore))
            tasks.append(task)
            logger.debug(f"Checking {modified_url} ...")
        logger.info(f"Checking {url} ...")
    results = await asyncio.gather(*tasks)
    valid_urls = [result for result in results if result]
    return valid_urls

async def fetch_json(session, url, semaphore):
    async with semaphore:
        try:
            ip_start_index = url.find("//") + 2
            ip_dot_start = url.find(".") + 1
            ip_index_second = url.find("/", ip_dot_start)
            base_url = url[:ip_start_index]
            ip_address = url[ip_start_index:ip_index_second]
            url_x = f"{base_url}{ip_address}"

            timeout = aiohttp.ClientTimeout(total=5)  # 按规范设置5秒超时
            async with session.get(url, timeout=timeout) as response:
                json_data = await response.json()
                results = []
                try:
                    for item in json_data.get('data', []):
                        if isinstance(item, dict):
                            name = item.get('name')
                            urlx = item.get('url')
                            
                            # 跳过包含逗号的URL（可能有格式问题）
                            if not name or not urlx or ',' in urlx:
                                continue
                                
                            # 构建完整URL
                            if urlx.startswith(('http://', 'https://')):
                                urld = urlx
                            else:
                                urld = f"{url_x}{urlx}"

                            name = clean_channel_name(name)
                            results.append(f"{name},{urld}")
                            
                except (KeyError, TypeError) as e:
                    logger.debug(f"解析JSON数据失败: {url}, 错误: {str(e)}")
                    
                return results
                
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.debug(f"获取JSON失败: {url}, 错误: {str(e)}")
            return []
        except Exception as e:
            logger.debug(f"处理JSON时发生异常: {url}, 错误: {str(e)}")
            return []

async def main():
    x_urls = []
    for url in urls:
        url = url.strip()
        ip_start_index = url.find("//") + 2
        ip_end_index = url.find(":", ip_start_index)
        ip_dot_start = url.find(".") + 1
        ip_dot_second = url.find(".", ip_dot_start) + 1
        ip_dot_three = url.find(".", ip_dot_second) + 1
        base_url = url[:ip_start_index]
        ip_address = url[ip_start_index:ip_dot_three]
        port = url[ip_end_index:]
        ip_end = "1"
        modified_ip = f"{ip_address}{ip_end}"
        x_url = f"{base_url}{modified_ip}{port}"
        x_urls.append(x_url)
    unique_urls = set(x_urls)

    # 提高并发数和配置连接池参数，按照最佳实践优化
    semaphore = asyncio.Semaphore(10)
    
    # 配置连接器，优化网络性能
    connector = aiohttp.TCPConnector(
        limit=100,           # 总连接数
        limit_per_host=10,   # 每主机连接数
        ttl_dns_cache=300,   # DNS缓存时间
        use_dns_cache=True,
        keepalive_timeout=30 # Keep-alive超时
    )
    
    timeout = aiohttp.ClientTimeout(total=30)  # 总超时时间
    
    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout
    ) as session:
        valid_urls = await check_urls(session, unique_urls, semaphore)
        all_results = []
        tasks = []
        for url in valid_urls:
            task = asyncio.create_task(fetch_json(session, url, semaphore))
            tasks.append(task)
        results = await asyncio.gather(*tasks)
        for sublist in results:
            all_results.extend(sublist)

    task_queue = Queue()
    results_lock = threading.Lock()  # 线程安全锁
    results = []
    error_channels = []

    def print_progress(status, channel_name, channel_url=None, error_msg=None):
        """打印检测进度信息"""
        numberx = (len(results) + len(error_channels)) / len(all_results) * 100
        
        if status == "稳定":
            logger.debug(f"稳定频道：{channel_name} - {channel_url}")
        elif status == "不稳定":
            logger.debug(f"不稳定频道（已剔除）：{channel_name} - {channel_url}")
        elif status == "异常":
            logger.debug(f"检测异常频道（已剔除）：{channel_name} - {error_msg}")
        
        logger.info(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(all_results)} 个 ,总进度：{numberx:.2f} %。")

    def worker():
        while True:
            try:
                # 从队列中获取一个任务
                channel_name, channel_url = task_queue.get(timeout=5)
                logger.debug(f"正在检测频道：{channel_name}, URL：{channel_url}")
                
                # 检测流稳定性 - 使用TSStreamChecker进行真正的TS流解析
                checker = TSStreamChecker(
                    check_duration=5,          # 5秒检测时间
                    response_time_threshold=120,  # 响应时间阈值120ms
                    request_timeout=5           # 按规范设置5秒超时
                )
                is_stable = checker.check_stream(channel_url)
                
                # 线程安全地更新结果
                with results_lock:
                    if is_stable:
                        # 稳定的流，保留并添加到结果中
                        result = channel_name, channel_url, "稳定"
                        results.append(result)
                        print_progress("稳定", channel_name, channel_url)
                    else:
                        # 不稳定的流，剔除
                        error_channel = channel_name, channel_url
                        error_channels.append(error_channel)
                        print_progress("不稳定", channel_name, channel_url)
                        
            except Exception as e:
                # 发生异常的流，也剔除
                with results_lock:
                    error_channel = channel_name, channel_url
                    error_channels.append(error_channel)
                    print_progress("异常", channel_name, error_msg=str(e))
            finally:
                # 确保任务标记完成
                task_queue.task_done()

    def channel_key(channel_name):
        match = re.search(r'\d+', channel_name)
        if match:
            return int(match.group())
        else:
            return float('inf')

    # 使用ThreadPoolExecutor管理线程池，更安全和高效
    num_workers = 10
    threads = []
    
    for _ in range(num_workers):
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        threads.append(t)

    # 将all_results中的数据放入任务队列
    for result in all_results:
        channel_name, channel_url = result.split(',')
        task_queue.put((channel_name, channel_url))


    # 等待所有任务完成
    task_queue.join()

    # 对结果进行排序（按频道名称排序）
    results.sort(key=lambda x: channel_key(x[0]))

    result_counter = 12  # 每个频道最多个数

    def write_channel_to_m3u(file, channel_name, channel_url, group_title):
        """写入单个频道到M3U文件"""
        file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="https://gitee.com/mytv-android/myTVlogo/raw/main/img/{channel_name}.png" group-title="{group_title}",{channel_name}\n')
        file.write(f"{channel_url}\n")

    def match_channel_category(channel_name, keywords, exclude_keywords=None):
        """判断频道是否匹配指定的关键词数组"""
        if exclude_keywords:
            # 如果有排除关键词，先检查是否包含排除关键词
            if any(exclude_word in channel_name for exclude_word in exclude_keywords):
                return False
        
        # 检查是否包含任何匹配关键词
        return any(keyword in channel_name for keyword in keywords)

    def write_channels_by_category(file, results, keywords, group_title, channel_counters, exclude_keywords=None):
        """按分类写入频道"""
        for result in results:
            channel_name, channel_url, speed = result
            if match_channel_category(channel_name, keywords, exclude_keywords):
                if channel_name in channel_counters:
                    if channel_counters[channel_name] >= result_counter:
                        continue
                    else:
                        write_channel_to_m3u(file, channel_name, channel_url, group_title)
                        channel_counters[channel_name] += 1
                else:
                    write_channel_to_m3u(file, channel_name, channel_url, group_title)
                    channel_counters[channel_name] = 1

    # 定义频道分类配置
    channel_categories = [
        {"name": "央视频道","keywords": ["CCTV"]},
        {"name": "卫视频道","keywords": ["卫视"]},
        {"name": "电影频道","keywords": ["电影", "影院", "影视"]},
        {"name": "IPTV频道","keywords": ["IPTV"]},
        {"name": "卡通频道","keywords": ["少儿", "卡通", "动画", "儿童","宝贝","哈哈"]},
        {"name": "体育频道","keywords": ["体育", "赛事", "奥运", "英超", "NBA"]},
        {"name": "其他频道","keywords": [""],"exclude_keywords": ["CCTV","卫视","体育", "赛事", "奥运", "英超", "NBA",
        "IPTV","电影", "影院", "影视","少儿", "卡通", "动画", "儿童","宝贝","测试"]} # exclude_keywords 是排除的关键字
    ]

    with open("itvlist.m3u", 'w', encoding='utf-8') as file:
        file.write('#EXTM3U\n')
        
        # 遍历所有频道分类
        for category in channel_categories:
            channel_counters = {}
            exclude_keywords = category.get("exclude_keywords", None)
            write_channels_by_category(
                file, 
                results, 
                category["keywords"], 
                category["name"], 
                channel_counters, 
                exclude_keywords
            )
        
        # 添加更新时间频道
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        file.write(f'#EXTINF:-1 tvg-name="{current_time}" tvg-logo="https://gitee.com/mytv-android/myTVlogo/raw/main/img/Dog狗频道.png" group-title="更新时间",{current_time}\n')
        file.write(f"http://example.com/update_time.mp4\n")


if __name__ == "__main__":
    asyncio.run(main())
