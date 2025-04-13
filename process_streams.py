import os
import re
import requests
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor
import time

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

# Function to check if a URL is active
def is_stream_active(url, timeout=5):
    try:
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code == 200 and "m3u" in response.headers.get("content-type", "").lower()
    except requests.RequestException:
        return False

# Clean channel name for filename
def clean_channel_name(name):
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().replace(' ', '_')
    return name

# Parse M3U content and extract valid entries
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

# Process a single source
def process_source(source):
    try:
        response = requests.get(source, timeout=10)
        if response.status_code == 200:
            return parse_m3u(response.text)
    except requests.RequestException:
        print(f"Failed to fetch {source}")
    return []

# Main processing logic
def main():
    # Create output directories
    os.makedirs(BASE_PATH, exist_ok=True)

    # Collect all entries
    all_entries = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(process_source, SOURCES)
        for result in results:
            all_entries.extend(result)

    # Validate streams and remove duplicates
    unique_streams = {}
    for extinf, url in all_entries:
        if is_stream_active(url):
            # Extract channel name from EXTINF
            match = re.search(r',(.+)$', extinf)
            if match:
                channel_name = clean_channel_name(match.group(1))
                if channel_name not in unique_streams:
                    unique_streams[channel_name] = (extinf, url)

    # Save individual .m3u8 files and prepare FinalStreamLinks.m3u
    final_m3u_content = ["#EXTM3U"]
    for channel_name, (extinf, _) in unique_streams.items():
        # Generate GitHub raw URL
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/{BASE_PATH}/{channel_name}.m3u8"
        
        # Save individual .m3u8 file
        individual_content = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2560000\n{github_url}"
        with open(f"{BASE_PATH}/{channel_name}.m3u8", "w", encoding="utf-8") as f:
            f.write(individual_content)
        
        # Add to final M3U
        final_m3u_content.append(f"{extinf}\n{github_url}")

    # Save FinalStreamLinks.m3u
    with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(final_m3u_content))

    print(f"Processed {len(unique_streams)} unique active streams.")

if __name__ == "__main__":
    main()
