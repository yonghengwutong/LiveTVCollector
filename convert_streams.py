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
    "https://raw.githubusercontent.com/Miraz6755/Bdixtv/refs/heads/main/Livetv.m3u8",
    "https://raw.githubusercontent.com/Yeadee/Toffee/refs/heads/main/toffee_ns_player.m3u",
    "https://raw.githubusercontent.com/MohammadJoyChy/BDIXTV/refs/heads/main/Aynaott",
    "https://raw.githubusercontent.com/Arunjunan20/My-IPTV/refs/heads/main/index.html",
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"
]

async def check_url_active(session, url):
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=3)) as response:
            return response.status == 200
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return False

def process_m3u_content(content):
    lines = content.split('\n')
    processed_entries = {}
    
    for i in range(len(lines)):
        if lines[i].startswith('#EXTINF:'):
            extinf = lines[i]
            if i + 1 < len(lines) and not lines[i + 1].startswith('#'):
                stream_url = lines[i + 1].strip()
                name_match = re.search(r',(.+)$', extinf)
                if name_match:
                    channel_name = name_match.group(1).strip()
                    # Replace only invalid filename characters, preserve spaces with single underscore
                    filename = re.sub(r'[<>:"/\\|?*]', '', channel_name)  # Remove invalid chars
                    filename = re.sub(r'\s+', '_', filename)  # Replace multiple spaces with single underscore
                    
                    if channel_name not in processed_entries:
                        processed_entries[channel_name] = {
                            'extinf': extinf,
                            'filename': f"{filename}.m3u8",
                            'original_url': stream_url
                        }
    return processed_entries

async def fetch_source(session, source):
    try:
        async with session.get(source, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                content = await response.text()
                return process_m3u_content(content)
            return {}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Failed to fetch {source}: {e}")
        return {}

async def check_urls(entries):
    async with aiohttp.ClientSession() as session:
        tasks = []
        for channel_name, data in entries.items():
            tasks.append(check_url_active(session, data['original_url']))
        
        results = await asyncio.gather(*tasks)
        
        active_entries = {}
        for (channel_name, data), is_active in zip(entries.items(), results):
            if is_active:
                active_entries[channel_name] = data
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
    
    active_entries = await check_urls(all_entries)
    
    final_playlist = "#EXTM3U\n"
    
    for channel_name, data in active_entries.items():
        content = "#EXTM3U\n" + data['extinf'] + "\n" + data['original_url'] + "\n"
        with open(f"{LIVE_TV_DIR}/{data['filename']}", 'w', encoding='utf-8') as f:
            f.write(content)
        
        github_url = f"{BASE_GITHUB_URL}/{LIVE_TV_DIR}/{data['filename']}"
        final_playlist += f"{data['extinf']}\n{github_url}\n"
    
    with open(f"{BASE_DIR}/FinalStreamLinks.m3u", 'w', encoding='utf-8') as f:
        f.write(final_playlist)
    
    print(f"Generated {len(active_entries)} active streams")
    print(f"Final playlist saved to {BASE_DIR}/FinalStreamLinks.m3u")

if __name__ == "__main__":
    asyncio.run(generate_m3u_files())
