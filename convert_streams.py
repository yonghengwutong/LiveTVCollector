import aiohttp
import asyncio
import re
import os
from datetime import datetime

# Output directories
BASE_DIR = "BugsfreeStreams"
LIVE_TV_DIR = f"{BASE_DIR}/LiveTV"
BASE_GITHUB_URL = "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/refs/heads/main"

# Sources to check
SOURCES = [
    "https://raw.githubusercontent.com/sydul104/main04/refs/heads/main/my",    
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"    
]

async def check_url_active(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
            if response.status == 200:
                print(f"URL active: {url}")
                return True
            else:
                print(f"URL inactive (status {response.status}): {url}")
                return False
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"URL check failed ({str(e)}): {url}")
        return False

def process_m3u_content(content):
    lines = content.split('\n')
    processed_entries = {}
    
    i = 0
    while i < len(lines):
        if lines[i].startswith('#EXTINF:'):
            extinf = lines[i]
            stream_content = []
            i += 1
            while i < len(lines) and not lines[i].startswith('#EXTINF:'):
                if lines[i].strip():
                    stream_content.append(lines[i])
                i += 1
            
            if stream_content:
                name_match = re.search(r',(.+)$', extinf)
                if name_match:
                    channel_name = name_match.group(1).strip()
                    filename = re.sub(r'[<>:"/\\|?*]', '', channel_name)
                    filename = re.sub(r'\s+', '_', filename)
                    
                    if channel_name not in processed_entries:
                        processed_entries[channel_name] = {
                            'extinf': extinf,
                            'filename': f"{filename}.m3u8",
                            'stream_content': stream_content
                        }
                        print(f"Processed channel: {channel_name}")
        else:
            i += 1
    return processed_entries

async def fetch_source(session, source):
    try:
        async with session.get(source, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                content = await response.text()
                entries = process_m3u_content(content)
                print(f"Fetched source: {source} with {len(entries)} entries")
                return entries
            else:
                print(f"Failed to fetch source (status {response.status}): {source}")
                return {}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Failed to fetch source ({str(e)}): {source}")
        return {}

async def check_urls(session, entries):
    active_entries = {}
    
    for channel_name, data in entries.items():
        urls = []
        stream_lines = []
        i = 0
        while i < len(data['stream_content']):
            line = data['stream_content'][i]
            if line.startswith('#EXT-X-STREAM-INF:'):
                i += 1
                if i < len(data['stream_content']) and not data['stream_content'][i].startswith('#'):
                    urls.append(data['stream_content'][i])
                    stream_lines.append((line, data['stream_content'][i]))
            else:
                stream_lines.append((line, None))
                i += 1
        
        if urls:
            results = await asyncio.gather(*[check_url_active(session, url) for url in urls])
            active_content = []
            url_idx = 0
            for info_line, url in stream_lines:
                if url is None:
                    active_content.append(info_line)
                elif results[url_idx]:
                    active_content.append(info_line)
                    active_content.append(url)
                url_idx += 1 if url else 0
            
            if active_content:
                active_entries[channel_name] = {
                    'extinf': data['extinf'],
                    'filename': data['filename'],
                    'stream_content': '\n'.join(active_content)
                }
                print(f"Channel active: {channel_name} with {len([u for u in urls if results[urls.index(u)]])} active variants")
        else:
            if await check_url_active(session, data['stream_content'][-1]):
                active_entries[channel_name] = {
                    'extinf': data['extinf'],
                    'filename': data['filename'],
                    'stream_content': '\n'.join(data['stream_content'])
                }
                print(f"Single stream channel active: {channel_name}")
            else:
                print(f"Single stream channel inactive: {channel_name}")
    
    return active_entries

async def generate_m3u_files():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(LIVE_TV_DIR, exist_ok=True)
    
    all_entries = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, source) for source in SOURCES]
        results = await asyncio.gather(*tasks)
        
        for entries in results:
            all_entries.update(entries)
        
        if not all_entries:
            print("No entries found from any source")
            return
        
        active_entries = await check_urls(session, all_entries)
    
    final_playlist = "#EXTM3U\n"
    
    for channel_name, data in active_entries.items():
        # Write only stream content to individual files, no #EXTINF:
        content = "#EXTM3U\n" + data['stream_content'] + "\n"
        with open(f"{LIVE_TV_DIR}/{data['filename']}", 'w', encoding='utf-8') as f:
            f.write(content)
        
        github_url = f"{BASE_GITHUB_URL}/{LIVE_TV_DIR}/{data['filename']}"
        final_playlist += f"{data['extinf']}\n{github_url}\n"
    
    # Add timestamp
    timestamp = datetime.now().strftime("%d/%m/%Y %H:%M:%S CEST")
    final_playlist += f"\n#Last refreshed on {timestamp}\n"
    
    with open(f"{BASE_DIR}/FinalStreamLinks.m3u", 'w', encoding='utf-8') as f:
        f.write(final_playlist)
    
    print(f"Generated {len(active_entries)} active streams")
    print(f"Final playlist saved to {BASE_DIR}/FinalStreamLinks.m3u")

if __name__ == "__main__":
    asyncio.run(generate_m3u_files())
