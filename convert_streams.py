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

async def get_stream_content(session, url):
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                return await response.text()
            return None
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return None

def process_m3u_content(content):
    lines = content.split('\n')
    processed_entries = {}
    
    i = 0
    while i < len(lines):
        if lines[i].startswith('#EXTINF:'):
            extinf = lines[i]
            stream_content = []
            i += 1
            # Collect all lines until next #EXTINF or end
            while i < len(lines) and not lines[i].startswith('#EXTINF:'):
                if lines[i].strip():  # Only add non-empty lines
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
                            'stream_content': '\n'.join(stream_content)
                        }
        else:
            i += 1
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

async def check_urls(session, entries):
    tasks = []
    for channel_name, data in entries.items():
        # Check the last URL in stream_content (assuming it's the main stream)
        stream_url = data['stream_content'].split('\n')[-1].strip()
        tasks.append(check_url_active(session, stream_url))
    
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
    
        # Check all URLs
        active_entries = await check_urls(session, all_entries)
    
    final_playlist = "#EXTM3U\n"
    
    for channel_name, data in active_entries.items():
        # Create individual M3U8 file with full stream content
        content = "#EXTM3U\n" + data['extinf'] + "\n" + data['stream_content'] + "\n"
        with open(f"{LIVE_TV_DIR}/{data['filename']}", 'w', encoding='utf-8') as f:
            f.write(content)
        
        # Add GitHub URL to final playlist
        github_url = f"{BASE_GITHUB_URL}/{LIVE_TV_DIR}/{data['filename']}"
        final_playlist += f"{data['extinf']}\n{github_url}\n"
    
    with open(f"{BASE_DIR}/FinalStreamLinks.m3u", 'w', encoding='utf-8') as f:
        f.write(final_playlist)
    
    print(f"Generated {len(active_entries)} active streams")
    print(f"Final playlist saved to {BASE_DIR}/FinalStreamLinks.m3u")

if __name__ == "__main__":
    asyncio.run(generate_m3u_files())
