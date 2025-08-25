import requests
import threading
import time
from urllib.parse import urlparse
import os
import re

# M3U文件URL列表
M3U_URLS = [
    "https://gitproxy.click/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/result.m3u",
    "https://gitproxy.click/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv6/result.m3u",
    "https://gitproxy.click/https://raw.githubusercontent.com/Guovin/iptv-api/gd/output/ipv4/result.m3u",
    "https://gitproxy.click/https://raw.githubusercontent.com/suxuang/myIPTV/main/ipv4.m3u",
    "https://live.zbds.org/tv/iptv4.m3u",
    "https://live.zbds.org/tv/iptv6.m3u",
]

def download_m3u(url, temp_file):
    """
    下载单个M3U文件并追加到临时文件中
    """
    try:
        print(f"正在下载: {url}")
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        
        with open(temp_file, 'a', encoding='utf-8') as f:
            f.write(response.text)
        print(f"下载完成: {url}")
        return True
    except Exception as e:
        print(f"下载失败 {url}: {str(e)}")
        return False

def download_all_m3u():
    """
    下载所有M3U文件并合并到temp.m3u
    """
    temp_file = "/mnt/temp.m3u"
    
    # 清空或创建temp.m3u文件
    with open(temp_file, 'w', encoding='utf-8') as f:
        f.write("")
    
    threads = []
    for url in M3U_URLS:
        thread = threading.Thread(target=download_m3u, args=(url, temp_file))
        threads.append(thread)
        thread.start()
    
    # 等待所有下载线程完成
    for thread in threads:
        thread.join()
    
    print("所有M3U文件下载完成")
    return temp_file

def check_stream_availability(url):
    """
    检查播放源URL的可用性
    """
    try:
        # 对于不同协议使用不同的检查方式
        parsed_url = urlparse(url)
        if parsed_url.scheme in ['http', 'https']:
            # 对于HTTP/HTTPS流，发送HEAD请求检查
            response = requests.head(url, timeout=0.5, allow_redirects=True)
            return response.status_code == 200
        elif parsed_url.scheme in ['rtmp', 'rtsp']:
            # 对于RTMP/RTSP流，只检查URL格式
            return True
        else:
            # 其他协议默认可用
            return True
    except:
        return False

def parse_m3u_file(filename):
    """
    解析M3U文件，提取频道信息
    """
    channels = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('#EXTINF:'):
                # 获取频道信息行
                info_line = line
                # 获取URL行
                i += 1
                if i < len(lines):
                    url_line = lines[i].strip()
                    if url_line and not url_line.startswith('#'):
                        channels.append({
                            'info': info_line,
                            'url': url_line
                        })
            i += 1
    except Exception as e:
        print(f"解析M3U文件时出错: {str(e)}")
    
    return channels

def remove_duplicates(channels):
    """
    根据频道名称和URL去除重复频道
    """
    unique_channels = []
    seen_channels = set()
    
    for channel in channels:
        # 提取频道名称
        info_line = channel['info']
        # 使用正则表达式从info行提取频道名称
        name_match = re.search(r',(.+?)$', info_line)
        channel_name = name_match.group(1) if name_match else ""
        
        # 使用频道名称和URL组合作为唯一标识
        channel_key = (channel_name, channel['url'])
        
        if channel_key not in seen_channels:
            seen_channels.add(channel_key)
            unique_channels.append(channel)
    
    return unique_channels

def filter_valid_channels(channels):
    """
    使用多线程过滤有效的频道
    """
    valid_channels = []
    
    # 创建线程锁保护共享资源
    lock = threading.Lock()
    
    def check_channel(channel):
        """
        检查单个频道的可用性
        """
        is_available = check_stream_availability(channel['url'])
        if is_available:
            with lock:
                valid_channels.append(channel)
        # print(f"{'✓' if is_available else '✗'} {channel['url']}")
    
    # 创建并启动线程
    threads = []
    for channel in channels:
        thread = threading.Thread(target=check_channel, args=(channel,))
        threads.append(thread)
        thread.start()
    
    # 等待所有线程完成
    for thread in threads:
        thread.join()
    
    return valid_channels

def save_filtered_channels(channels, output_filename):
    """
    将过滤后的频道保存到文件
    """
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write("#EXTM3U\n")  # 写入M3U头部
        for channel in channels:
            f.write(f"{channel['info']}\n")
            f.write(f"{channel['url']}\n")
    print(f"有效频道已保存到 {output_filename}")

def main():
    """
    主函数
    """
    print("开始下载M3U文件...")
    temp_file = download_all_m3u()
    
    print("\n开始解析M3U文件...")
    channels = parse_m3u_file(temp_file)
    print(f"总共找到 {len(channels)} 个频道")
    
    print("\n开始去除重复频道...")
    unique_channels = remove_duplicates(channels)
    print(f"去重后剩余 {len(unique_channels)} 个频道")
    
    print("\n开始检测频道可用性...")
    valid_channels = filter_valid_channels(unique_channels)
    print(f"\n检测完成，有效频道数: {len(valid_channels)}/{len(unique_channels)}")
    
    print("\n保存有效频道...")
    save_filtered_channels(valid_channels, "temp.m3u")
    print("处理完成!")

if __name__ == "__main__":
    main()
