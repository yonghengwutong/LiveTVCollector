import aiohttp
import asyncio
import re
import os
from datetime import datetime

BASE_DIR = "BugsfreeStreams"
LIVE_TV_DIR = f"{BASE_DIR}/LiveTV"
BASE_GITHUB_URL = "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/refs/heads/main"

SOURCES = [    
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"    
]

async def fetch_source(session, source):
    try:
        async with session.get(source, timeout=aiohttp.ClientTimeout(total=10)) as response:
            if response.status == 200:
                content = await response.text()
                entries = process_m3u_content(content)
                print(f"Fetched source: {source} with {len(entries)} entries")
                with open("debug.log", "a") as f:
                    f.write(f"Fetched source: {source} with {len(entries)} entries\n")
                return entries
            else:
                print(f"Failed to fetch source (status {response.status}): {source}")
                with open("debug.log", "a") as f:
                    f.write(f"Failed to fetch source (status {response.status}): {source}\n")
                return {}
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        print(f"Failed to fetch source ({str(e)}): {source}")
        with open("debug.log", "a") as f:
            f.write(f"Failed to fetch source ({str(e)}): {source}\n")
        return {}

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
                        with open("debug.log", "a") as f:
                            f.write(f"Processed channel: {channel_name}\n")
        else:
            i += 1
    return processed_entries

async def generate_m3u_files():
    os.makedirs(BASE_DIR, exist_ok=True)
    os.makedirs(LIVE_TV_DIR, exist_ok=True)
    
    with open("debug.log", "w") as f:
        f.write(f"Debug log started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S PDT')}\n")
    
    all_entries = {}
    
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_source(session, source) for source in SOURCES]
        results = await asyncio.gather(*tasks)
        
        for entries in results:
            all_entries.update(entries)
        
        if not all_entries:
            print("No entries found from any source")
            with open("debug.log", "a") as f:
                f.write("No entries found from any source\n")
            return
    
    # Generate two versions of the playlist
    final_playlist_direct = "#EXTM3U\n"
    final_playlist_github = "#EXTM3U\n"
    
    for channel_name, data in all_entries.items():
        content = "#EXTM3U\n" + '\n'.join(data['stream_content']) + "\n"
        with open(f"{LIVE_TV_DIR}/{data['filename']}", 'w', encoding='utf-8') as f:
            f.write(content)
        
        github_url = f"{BASE_GITHUB_URL}/{LIVE_TV_DIR}/{data['filename']}"
        # Use the last URL as the direct stream URL (simplest approach for now)
        direct_url = data['stream_content'][-1]
        
        final_playlist_direct += f"{data['extinf']}\n{direct_url}\n"
        final_playlist_github += f"{data['extinf']}\n{github_url}\n"
        
        print(f"Added to FinalStreamLinks.m3u (direct): {channel_name} -> {direct_url}")
        print(f"Added to FinalStreamLinks_GitHub.m3u: {channel_name} -> {github_url}")
        with open("debug.log", "a") as f:
            f.write(f"Added to FinalStreamLinks.m3u (direct): {channel_name} -> {direct_url}\n")
            f.write(f"Added to FinalStreamLinks_GitHub.m3u: {channel_name} -> {github_url}\n")
    
    with open(f"{BASE_DIR}/FinalStreamLinks.m3u", 'w', encoding='utf-8') as f:
        f.write(final_playlist_direct)
    with open(f"{BASE_DIR}/FinalStreamLinks_GitHub.m3u", 'w', encoding='utf-8') as f:
        f.write(final_playlist_github)
    
    print(f"Generated {len(all_entries)} streams")
    print(f"Direct playlist saved to {BASE_DIR}/FinalStreamLinks.m3u")
    print(f"GitHub playlist saved to {BASE_DIR}/FinalStreamLinks_GitHub.m3u")
    with open("debug.log", "a") as f:
        f.write(f"Generated {len(all_entries)} streams\n")
        f.write(f"Direct playlist saved to {BASE_DIR}/FinalStreamLinks.m3u\n")
        f.write(f"GitHub playlist saved to {BASE_DIR}/FinalStreamLinks_GitHub.m3u\n")

if __name__ == "__main__":
    asyncio.run(generate_m3u_files())
