import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

# Configuration
REPO_OWNER = "bugsfreeweb"
REPO_NAME = "LiveTVCollector"
BRANCH = "main"
BASE_PATH = "BugsfreeStreams/LiveTV"
FINAL_M3U_FILE = "BugsfreeStreams/FinalStreamLinks.m3u"

# Source M3U playlists
SOURCES = [   
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"
]

# Check if a URL is an active .m3u8 stream
def is_stream_active(url):
    try:
        # Use GET with Range header to fetch minimal data
        response = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=3, stream=True)
        if response.status_code in (200, 206) and "m3u" in response.headers.get("content-type", "").lower():
            return True
    except requests.RequestException:
        pass
    return False

# Clean channel name for filename
def clean_channel_name(name):
    return re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().replace(' ', '_')

# Parse M3U content
def parse_m3u(content):
    entries = []
    lines = content.splitlines()
    extinf = None
    for line in lines:
        line = line.strip()
        if line.startswith("#EXTINF:"):
            extinf = line
        elif line.startswith("http") and extinf:
            entries.append((extinf, line))
            extinf = None
    return entries

# Fetch and parse a single source
def process_source(source):
    try:
        response = requests.get(source, timeout=5)
        if response.status_code == 200:
            return parse_m3u(response.text)
    except requests.RequestException:
        print(f"Skipped {source}")
    return []

# Main processing logic
def main():
    os.makedirs(BASE_PATH, exist_ok=True)

    # Fetch sources concurrently
    all_entries = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(process_source, SOURCES)
        for result in results:
            all_entries.extend(result)

    # Validate streams and remove duplicates
    unique_streams = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        for extinf, url in all_entries:
            if executor.submit(is_stream_active, url).result():
                match = re.search(r',(.+)$', extinf)
                if match:
                    channel_name = clean_channel_name(match.group(1))
                    if channel_name not in unique_streams:
                        unique_streams[channel_name] = (extinf, url)

    # Prepare outputs
    final_m3u_content = ["#EXTM3U"]
    individual_files = {}
    for channel_name, (extinf, _) in unique_streams.items():
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/{BASE_PATH}/{channel_name}.m3u8"
        individual_files[f"{BASE_PATH}/{channel_name}.m3u8"] = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2560000\n{github_url}"
        final_m3u_content.append(f"{extinf}\n{github_url}")

    # Write all files at once
    for file_path, content in individual_files.items():
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
    with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(final_m3u_content))

    print(f"Processed {len(unique_streams)} streams.")

if __name__ == "__main__":
    main()
