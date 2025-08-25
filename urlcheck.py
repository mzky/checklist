import time
import concurrent.futures
import requests
import re
import os
import subprocess
import threading
from queue import Queue
import eventlet
eventlet.monkey_patch()

def main():
    urls = [
    "http://116.128.242.83:9901",
    "http://223.241.247.214:9901",
    "http://36.40.236.183:9999",
    "http://180.213.174.220:9901",
    "http://112.26.18.35:9901",
    "http://113.201.61.98:9901",
    "http://123.139.57.170:9901",
    "http://218.87.237.106:9901",
    "http://218.87.237.105:9901",
    "http://112.132.160.130:9901",
    "http://61.156.228.12:8154",
    "http://221.205.129.39:9999",
    "http://49.232.48.19:9901",
    "http://113.57.93.165:9900",
    "http://113.195.162.70:9901",
    "http://61.136.172.236:9901",
    "http://47.116.70.223:9901",
    "http://123.129.70.178:9901",
    "http://121.19.134.122:808",
    "http://121.19.134.155:808",
    "http://221.205.130.176:9999",
    "http://222.243.221.54:9901",
    "http://112.234.23.227:9901",
    "http://123.130.84.106:8154"
        ]
    def modify_urls(url):
        modified_urls = []
        ip_start_index = url.find("//") + 2
        ip_end_index = url.find(":", ip_start_index)
        base_url = url[:ip_start_index]  # http:// or https://
        ip_address = url[ip_start_index:ip_end_index]
        port = url[ip_end_index:]
        ip_end = "/iptv/live/1000.json?key=txiptv"
        for i in range(1, 256):
            modified_ip = f"{ip_address[:-1]}{i}"
            modified_url = f"{base_url}{modified_ip}{port}{ip_end}"
            modified_urls.append(modified_url)
        return modified_urls
    def is_url_accessible(url):
        try:
            response = requests.get(url, timeout=0.5)
            if response.status_code == 200:
                return url
            else:
                # 如果状态码不是200，认为地址不可访问
                return None
        except requests.exceptions.Timeout:
            # 超时情况，直接剔除地址
            return None
        except requests.exceptions.RequestException:
            # 其他网络请求异常
            return None
        except Exception:
            # 捕获其他所有异常
            return None
    results = []
    x_urls = []
    for url in urls:  # 对urls进行处理，ip第四位修改为1，并去重
        url = url.strip()
        ip_start_index = url.find("//") + 2
        ip_end_index = url.find(":", ip_start_index)
        ip_dot_start = url.find(".") + 1
        ip_dot_second = url.find(".", ip_dot_start) + 1
        ip_dot_three = url.find(".", ip_dot_second) + 1
        base_url = url[:ip_start_index]  # http:// or https://
        ip_address = url[ip_start_index:ip_dot_three]
        port = url[ip_end_index:]
        ip_end = "1"
        modified_ip = f"{ip_address}{ip_end}"
        x_url = f"{base_url}{modified_ip}{port}"
        x_urls.append(x_url)
    urls = set(x_urls)  # 去重得到唯一的URL列表
    valid_urls = []
    #   多线程获取可用url
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = []
        for url in urls:
            url = url.strip()
            modified_urls = modify_urls(url)
            for modified_url in modified_urls:
                futures.append(executor.submit(is_url_accessible, modified_url))
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                valid_urls.append(result)
    for url in valid_urls:
        print(url)
    # 遍历网址列表，获取JSON文件并解析
    for url in valid_urls:
        try:
            # 发送GET请求获取JSON文件，设置超时时间为5秒
            ip_start_index = url.find("//") + 2
            ip_dot_start = url.find(".") + 1
            ip_index_second = url.find("/", ip_dot_start)
            base_url = url[:ip_start_index]  # http:// or https://
            ip_address = url[ip_start_index:ip_index_second]
            url_x = f"{base_url}{ip_address}"
            json_url = f"{url}"
            response = requests.get(json_url, timeout=5)
            json_data = response.json()
            try:
                # 解析JSON文件，获取name和url字段
                for item in json_data['data']:
                    if isinstance(item, dict):
                        name = item.get('name')
                        urlx = item.get('url')
                        if ',' in urlx:
                            urlx=f"aaaaaaaa"
                        #if 'http' in urlx or 'udp' in urlx or 'rtp' in urlx:
                        if 'http' in urlx:
                            urld = f"{urlx}"
                        else:
                            urld = f"{url_x}{urlx}"
                        if name and urlx:
                            # 删除特定文字
                            name = name.replace("cctv", "CCTV")
                            name = name.replace("中央", "CCTV")
                            name = name.replace("央视", "CCTV")
                            name = name.replace("频道", "")
                            name = name.replace("-", "")
                            name = name.replace(" ", "")
                            name = name.replace("PLUS", "+")
                            name = name.replace("＋", "+")
                            name = name.replace("(", "")
                            name = name.replace(")", "")
                            name = re.sub(r"CCTV(\d+)台", r"CCTV\1", name)
                            name = name.replace("CCTV1综合", "CCTV1")
                            name = name.replace("CCTV2财经", "CCTV2")
                            name = name.replace("CCTV3综艺", "CCTV3")
                            name = name.replace("CCTV4国际", "CCTV4")
                            name = name.replace("CCTV4中文国际", "CCTV4")
                            name = name.replace("CCTV4欧洲", "CCTV4")
                            name = name.replace("CCTV5体育", "CCTV5")
                            name = name.replace("CCTV6电影", "CCTV6")
                            name = name.replace("CCTV7军事", "CCTV7")
                            name = name.replace("CCTV7军农", "CCTV7")
                            name = name.replace("CCTV7农业", "CCTV7")
                            name = name.replace("CCTV7国防军事", "CCTV7")
                            name = name.replace("CCTV8电视剧", "CCTV8")
                            name = name.replace("CCTV9记录", "CCTV9")
                            name = name.replace("CCTV9纪录", "CCTV9")
                            name = name.replace("CCTV10科教", "CCTV10")
                            name = name.replace("CCTV11戏曲", "CCTV11")
                            name = name.replace("CCTV12社会与法", "CCTV12")
                            name = name.replace("CCTV13新闻", "CCTV13")
                            name = name.replace("CCTV新闻", "CCTV13")
                            name = name.replace("CCTV14少儿", "CCTV14")
                            name = name.replace("CCTV15音乐", "CCTV15")
                            name = name.replace("CCTV16奥林匹克", "CCTV16")
                            name = name.replace("CCTV17农业农村", "CCTV17")
                            name = name.replace("CCTV17农业", "CCTV17")
                            name = name.replace("CCTV5+体育赛视", "CCTV5+")
                            name = name.replace("CCTV5+体育赛事", "CCTV5+")
                            name = name.replace("CCTV5+体育", "CCTV5+")
                            results.append(f"{name},{urld}")
            except:
                continue
        except:
            continue
    channels = []
    for result in results:
        line = result.strip()
        if result:
            channel_name, channel_url = result.split(',')
            channels.append((channel_name, channel_url))
    # 线程安全的队列，用于存储下载任务
    task_queue = Queue()
    # 线程安全的列表，用于存储结果
    results = []
    error_channels = []
    # 定义工作线程函数
    def worker():
        while True:
            # 从队列中获取一个任务
            channel_name, channel_url = task_queue.get()
            try:
                # 首先测频道播放地址是否可以访问，设置3秒超时
                try:
                    start_time = time.time()
                    response = requests.get(channel_url, timeout=0.5)
                    elapsed_time = time.time() - start_time
                    if response.status_code != 200:
                        raise Exception(f"Invalid response status: {response.status_code}")
                    # print(f"✓ 可用频道: {channel_name} ({channel_url}) - 状态码: {response.status_code}, 响应时间: {elapsed_time:.2f}秒")
                except requests.exceptions.Timeout:
                    # 如果超时，将频道添加到错误列表跳过
                    error_channel = channel_name, channel_url
                    error_channels.append(error_channel)
                    # print(f"✗ 超时频道: {channel_name} ({channel_url}) - 请求超时")
                    numberx = (len(results) + len(error_channels)) / len(channels) * 100
                    # print(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(channels)} 个 ,总进度：{numberx:.2f} %。")
                    task_queue.task_done()
                    continue
                except requests.exceptions.RequestException as e:
                    # 如果其他网络错误，将频道添加到错误列表并跳过
                    error_channel = channel_name, channel_url
                    error_channels.append(error_channel)
                    # print(f"✗ 错误频道: {channel_name} ({channel_url}) - 错误: {str(e)}")
                    numberx = (len(results) + len(error_channels)) / len(channels) * 100
                    # print(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(channels)} 个 ,总进度：{numberx:.2f} %。")
                    task_queue.task_done()
                    continue
                
                # 如果地址可访问，继续处理
                channel_url_t = channel_url.rstrip(channel_url.split('/')[-1])  # m3u8链接前缀
                lines = response.text.strip().split('\n')  # 使用已获取的响应内容
                ts_lists = [line.split('/')[-1] for line in lines if line.startswith('#') == False]  # 获取m3u8文件下视频流后缀
                if not ts_lists:
                    raise Exception("No ts files found")
                ts_lists_0 = ts_lists[0].rstrip(ts_lists[0].split('.ts')[-1])  # m3u8链接前缀
                ts_url = channel_url_t + ts_lists[0]  # 接单个视频片段下载链接
                
                # 多获取的视频数据进行5秒钟限制
                with eventlet.Timeout(3, False):
                    start_time = time.time()
                    content = requests.get(ts_url, timeout = 1).content
                    end_time = time.time()
                    response_time = (end_time - start_time) * 1
                
                if content:
                    with open(ts_lists_0, 'ab') as f:
                        f.write(content)  # 写入文件
                    file_size = len(content)
                    # print(f"文件大小：{file_size} 字节")
                    download_speed = file_size / response_time / 1024
                    # print(f"下载速度：{download_speed:.3f} kB/s")
                    normalized_speed = min(max(download_speed / 1024, 0.001), 100)  # 将速率从kB/s转换为MB/s并限制在1~100之间
                    #print(f"标准化后的速率：{normalized_speed:.3f} MB/s")
                    # 删除下载的文件
                    try:
                        os.remove(ts_lists_0)
                    except:
                        pass  # 忽略删除文件时的错误
                    result = channel_name, channel_url, f"{normalized_speed:.3f} MB/s"
                    results.append(result)
                    numberx = (len(results) + len(error_channels)) / len(channels) * 100
                    # print(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(channels)} 个 ,总进度：{numberx:.2f} %。")
                else:
                    # 如果没有内容，将频道添加到错误列表
                    error_channel = channel_name, channel_url
                    error_channels.append(error_channel)
                    numberx = (len(results) + len(error_channels)) / len(channels) * 100
                    # print(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(channels)} 个 ,总进度：{numberx:.2f} %。")
            except Exception as e:
                error_channel = channel_name, channel_url
                error_channels.append(error_channel)
                numberx = (len(results) + len(error_channels)) / len(channels) * 100
                # print(f"可用频道：{len(results)} 个 , 不可用频道：{len(error_channels)} 个 , 总频道：{len(channels)} 个 ,总进度：{numberx:.2f} %。")
            # 标记任务完成
            task_queue.task_done()
    # 创建多个工作线程
    num_threads = 10
    for _ in range(num_threads):
        t = threading.Thread(target=worker, daemon=True)  # 将工作线程设置为守护线程
        t.start()
    # 添加下载任务到队列
    for channel in channels:
        task_queue.put(channel)
    # 等待所有任务完成
    task_queue.join()
    def channel_key(channel_name):
        match = re.search(r'\d+', channel_name)
        if match:
            return int(match.group())
        else:
            return float('inf')  # 返回一个无穷大的数字作为关键字
    # 对频道进行排序
    results.sort(key=lambda x: (x[0], -float(x[2].split()[0])))
    results.sort(key=lambda x: channel_key(x[0]))
    result_counter = 8  # 每个频道需要的个数
    with open("/mnt/itvlist.m3u", 'w', encoding='utf-8') as file:
        channel_counters = {}
        file.write('#EXTM3U\n')
        for result in results:
            channel_name, channel_url, speed = result
            if 'CCTV' in channel_name:
                if channel_name in channel_counters:
                    if channel_counters[channel_name] >= result_counter:
                        continue
                    else:
                        file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/CCTV/{channel_name.replace("+", "P")}.png" group-title="央视频道",{channel_name}\n')
                        file.write(f"{channel_url}\n")
                        channel_counters[channel_name] += 1
                else:
                    file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/CCTV/{channel_name.replace("+", "P")}.png" group-title="央视频道",{channel_name}\n')
                    file.write(f"{channel_url}\n")
                    channel_counters[channel_name] = 1
        channel_counters = {}
        for result in results:
            channel_name, channel_url, speed = result
            if '卫视' in channel_name:
                if channel_name in channel_counters:
                    if channel_counters[channel_name] >= result_counter:
                        continue
                    else:
                        file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/ws/{channel_name}.png" group-title="卫视频道",{channel_name}\n')
                        file.write(f"{channel_url}\n")
                        channel_counters[channel_name] += 1
                else:
                    file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/ws/{channel_name}.png" group-title="卫视频道",{channel_name}\n')
                    file.write(f"{channel_url}\n")
                    channel_counters[channel_name] = 1
        channel_counters = {}
        for result in results:
            channel_name, channel_url, speed = result
            if 'CCTV' not in channel_name and '卫视' not in channel_name and '测试' not in channel_name:
                if channel_name in channel_counters:
                    if channel_counters[channel_name] >= result_counter:
                        continue
                    else:
                        file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/qt/{channel_name}.png" group-title="其他频道",{channel_name}\n')
                        file.write(f"{channel_url}\n")
                        channel_counters[channel_name] += 1
                else:
                    file.write(f'#EXTINF:-1 tvg-name="{channel_name}" tvg-logo="http://epg.51zmt.top:8000/tb1/qt/{channel_name}.png" group-title="其他频道",{channel_name}\n')
                    file.write(f"{channel_url}\n")
                    channel_counters[channel_name] = 1

    # 追加temp.m3u的内容到/mnt/itvlist.m3u
    try:
        with open("/mnt/temp.m3u", "r", encoding="utf-8") as temp_file:
            # 跳过M3U头部
            lines = temp_file.readlines()
            if lines and lines[0].startswith("#EXTM3U"):
                lines = lines[1:]
            
            # 追加内容到/mnt/itvlist.m3u
            with open("/mnt/itvlist.m3u", "a", encoding="utf-8") as itvlist_file:
                itvlist_file.writelines(lines)
                 # 添加更新时间频道
                import datetime
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                itvlist_file.write(f'#EXTINF:-1 tvg-name="更新时间" tvg-logo="" group-title="系统信息",{current_time}\n')
                itvlist_file.write(f"http://example.com/update_time.mp4\n")
        print("已将/mnt/temp.m3u内容追加到/mnt/itvlist.m3u")
        os.remove("/mnt/temp.m3u")
    except FileNotFoundError:
        print("未找到/mnt/temp.m3u文件，跳过追加操作")
    except Exception as e:
        print(f"追加/mnt/temp.m3u内容时出错: {e}")


if __name__ == '__main__':
    subprocess.run(["python3", "/mnt/m3ucheck.py"])
    print("探测json中的频道可用性...")
    main()
