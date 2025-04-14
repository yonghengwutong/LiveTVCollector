import os
import re
import requests
import shutil
from concurrent.futures import ThreadPoolExecutor
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger()

# Configuration
REPO_OWNER = "bugsfreeweb"
REPO_NAME = "LiveTVCollector"
BRANCH = "main"
BASE_PATH = "BugsfreeStreams/LiveTV"
FINAL_M3U_FILE = "BugsfreeStreams/FinalStreamLinks.m3u"
MAX_STREAMS = 1000  # Cap to avoid GitHub UI truncation

# Source M3U playlists
SOURCES = [    
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"
]

# Fallback test stream
FALLBACK_STREAM = {
    "extinf": '#EXTINF:-1 tvg-logo="https://example.com/test.png" group-title="TEST",Test Stream',
    "url": "https://allinonereborn.com/test.m3u8?id=113",
    "name": "Test_Stream"
}

# Check if a URL is an active .m3u8 stream
def is_stream_active(url):
    try:
        response = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=3, stream=True)
        logger.info(f"Checking {url}: status={response.status_code}")
        if response.status_code in (200, 206):
            content = response.content.decode("utf-8", errors="ignore")
            if "#EXTM3U" in content:
                return True
    except requests.RequestException as e:
        logger.warning(f"Failed to check {url}: {e}")
    return False

# Clean channel name for filename
def clean_channel_name(name):
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower().replace(' ', '_')
    return re.sub(r'_+', '_', name)  # Remove multiple underscores

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
        logger.info(f"Fetching {source}")
        response = requests.get(source, timeout=5)
        if response.status_code == 200:
            entries = parse_m3u(response.text)
            logger.info(f"Found {len(entries)} entries in {source}")
            return entries
        else:
            logger.warning(f"Source {source} returned status {response.status_code}")
    except requests.RequestException as e:
        logger.warning(f"Skipped {source}: {e}")
    return []

# Main processing logic
def main():
    logger.info("Starting stream processing")
    
    # Clean up old files
    if os.path.exists(BASE_PATH):
        shutil.rmtree(BASE_PATH)
        logger.info(f"Deleted old files in {BASE_PATH}")
    os.makedirs(BASE_PATH, exist_ok=True)

    # Fetch sources concurrently
    all_entries = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        results = executor.map(process_source, SOURCES)
        for result in results:
            all_entries.extend(result)
    logger.info(f"Total entries collected: {len(all_entries)}")

    # Validate streams and remove duplicates
    unique_streams = {}
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [(extinf, url, executor.submit(is_stream_active, url)) for extinf, url in all_entries]
        for extinf, url, future in futures:
            if len(unique_streams) >= MAX_STREAMS:
                logger.info(f"Reached MAX_STREAMS limit: {MAX_STREAMS}")
                break
            if future.result():
                match = re.search(r',(.+)$', extinf)
                if match:
                    channel_name = clean_channel_name(match.group(1))
                    if channel_name not in unique_streams:
                        unique_streams[channel_name] = (extinf, url)
                        logger.info(f"Added valid stream: {channel_name}")

    # Add fallback if no streams
    if not unique_streams:
        logger.warning("No valid streams found, adding fallback")
        unique_streams[FALLBACK_STREAM["name"]] = (FALLBACK_STREAM["extinf"], FALLBACK_STREAM["url"])

    logger.info(f"Total unique valid streams: {len(unique_streams)}")

    # Prepare outputs
    final_m3u_content = ["#EXTM3U"]
    individual_files = {}
    for channel_name, (extinf, original_url) in unique_streams.items():
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/{BASE_PATH}/{channel_name}.m3u8"
        individual_files[f"{BASE_PATH}/{channel_name}.m3u8"] = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2560000\n{original_url}"
        final_m3u_content.append(f"{extinf}\n{github_url}")

    # Write all files
    for file_path, content in individual_files.items():
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Wrote {file_path}")
    with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(final_m3u_content))
    logger.info(f"Wrote {FINAL_M3U_FILE} with {len(final_m3u_content)-1} entries")
    logger.info(f"Total files in {BASE_PATH}: {len(individual_files)}")

if __name__ == "__main__":
    main()
