import os
import re
import requests
import shutil
import logging
from time import sleep

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger()

# Configuration
REPO_OWNER = "bugsfreeweb"
REPO_NAME = "LiveTVCollector"
BRANCH = "main"
BASE_PATH = "../BugsfreeStreams/LiveTV"
FINAL_M3U_FILE = "../BugsfreeStreams/FinalStreamLinks.m3u"
MAX_STREAMS = 1000
DEFAULT_LOGO = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeLogo/default-logo.png"

# Variant bitrates (bps)
VARIANTS = {
    "sd": 1000000,  # 1 Mbps, ~10.8 GB/day
    "hd": 2560000   # 2.56 Mbps, ~27.65 GB/day
}

# Default single source
DEFAULT_SOURCE = "https://aynaxpranto.vercel.app/files/playlist.m3u"

# Static fallback M3U if all sources fail
STATIC_M3U = """
#EXTM3U
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Channel
http://sample-stream.com/stream.m3u8
"""

# Source M3U playlist(s)
SOURCES = DEFAULT_SOURCE
MULTI_SOURCES = [
    "https://raw.githubusercontent.com/MohammadJoyChy/BDIXTV/refs/heads/main/Aynaott",
    "https://aynaxpranto.vercel.app/files/playlist.m3u"
]

# Fallback test stream
FALLBACK_STREAM = {
    "extinf": f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" group-title="TEST",Test Stream',
    "url": "https://allinonereborn.com/test.m3u8?id=113",
    "name": "Test_Stream"
}

# Validate a source URL with retries
def validate_source(url, retries=5, delay=3):
    for attempt in range(retries):
        try:
            response = requests.head(url, timeout=5, allow_redirects=True)
            logger.info(f"Source {url}: attempt {attempt+1}/{retries}, status={response.status_code}, headers={response.headers}")
            return response.status_code == 200
        except requests.RequestException as e:
            logger.warning(f"Source {url}: attempt {attempt+1}/{retries} failed: {e}")
            if attempt < retries - 1:
                sleep(delay)
    logger.error(f"Source {url} unreachable after {retries} attempts")
    return False

# Check if a URL is an active .m3u8 stream
def is_stream_active(url):
    try:
        response = requests.get(url, headers={"Range": "bytes=0-1023"}, timeout=3, stream=True)
        logger.info(f"Checking stream {url}: status={response.status_code}")
        if response.status_code in (200, 206):
            content = response.content.decode("utf-8", errors="ignore")
            if "#EXTM3U" in content:
                return True
            else:
                logger.warning(f"No #EXTM3U in stream {url}")
        else:
            logger.warning(f"Invalid status for stream {url}: {response.status_code}")
    except requests.RequestException as e:
        logger.warning(f"Failed to check stream {url}: {e}")
    return False

# Clean channel name for filename
def clean_channel_name(name):
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower().replace(' ', '_')
    return re.sub(r'_+', '_', name)

# Add default logo to EXTINF if missing
def ensure_logo(extinf):
    if 'tvg-logo="' not in extinf:
        match = re.search(r'(#EXTINF:-?\d+\s+)(.*?),(.+)$', extinf)
        if match:
            return f'{match.group(1)}tvg-logo="{DEFAULT_LOGO}" {match.group(2)},{match.group(3)}'
    elif 'tvg-logo=""' in extinf:
        return extinf.replace('tvg-logo=""', f'tvg-logo="{DEFAULT_LOGO}"')
    return extinf

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
    logger.info(f"Parsed {len(entries)} entries")
    return entries

# Fetch and parse a single source
def process_source(source):
    if not validate_source(source):
        logger.error(f"Source {source} invalid, skipping")
        return []
    try:
        logger.info(f"Fetching {source}")
        response = requests.get(source, timeout=5)
        if response.status_code == 200:
            content = response.text
            logger.info(f"Raw content: {content[:500]}")
            entries = parse_m3u(content)
            logger.info(f"Found {len(entries)} entries in {source}")
            return entries
        else:
            logger.warning(f"Source {source} returned status {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {source}: {e}")
    return []

# Main processing logic
def main():
    logger.info("Starting stream processing")
    
    # Validate paths
    try:
        os.makedirs(BASE_PATH, exist_ok=True)
        os.makedirs(os.path.dirname(FINAL_M3U_FILE), exist_ok=True)
        logger.info(f"Paths verified: {BASE_PATH} (writable={os.access(BASE_PATH, os.W_OK)}), {FINAL_M3U_FILE}")
    except Exception as e:
        logger.error(f"Path setup failed: {e}")
        return

    # Write fallback stream first
    try:
        fallback_file = f"{BASE_PATH}/{FALLBACK_STREAM['name']}.m3u8"
        fallback_content = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2560000\n{FALLBACK_STREAM['url']}"
        with open(fallback_file, "w", encoding="utf-8") as f:
            f.write(fallback_content)
        logger.info(f"Wrote fallback: {fallback_file}")
        with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
            f.write(f"#EXTM3U\n{FALLBACK_STREAM['extinf']}\nhttps://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeStreams/LiveTV/{FALLBACK_STREAM['name']}.m3u8")
        logger.info(f"Initialized {FINAL_M3U_FILE} with Test Stream")
    except Exception as e:
        logger.error(f"Failed to write fallback: {e}")
        return

    # Fetch sources
    all_entries = []
    if isinstance(SOURCES, str):
        logger.info("Using single source mode")
        entries = process_source(SOURCES)
        if entries:
            all_entries.extend(entries)
        else:
            logger.warning("Single source failed, trying multi-sources")
            for source in MULTI_SOURCES:
                entries = process_source(source)
                all_entries.extend(entries)
    else:
        for source in SOURCES:
            entries = process_source(source)
            all_entries.extend(entries)

    # If no entries, try static M3U
    if not all_entries:
        logger.warning("No entries from sources, using static M3U")
        all_entries = parse_m3u(STATIC_M3U)

    logger.info(f"Total entries collected: {len(all_entries)}")

    # Validate streams and remove duplicates
    unique_streams = {}
    for extinf, url in all_entries:
        if len(unique_streams) >= MAX_STREAMS:
            logger.info(f"Reached MAX_STREAMS limit: {MAX_STREAMS}")
            break
        if is_stream_active(url):
            match = re.search(r',(.+)$', extinf)
            if match:
                channel_name = clean_channel_name(match.group(1))
                if channel_name not in unique_streams:
                    unique_streams[channel_name] = (ensure_logo(extinf), url)
                    logger.info(f"Added valid stream: {channel_name}")

    # Include fallback stream (already written)
    unique_streams[FALLBACK_STREAM["name"]] = (FALLBACK_STREAM["extinf"], FALLBACK_STREAM["url"])
    logger.info(f"Total unique valid streams: {len(unique_streams)}")

    # Prepare outputs
    final_m3u_content = ["#EXTM3U"]
    individual_files = {}
    for channel_name, (extinf, original_url) in unique_streams.items():
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeStreams/LiveTV/{channel_name}.m3u8"
        # Single stream first, then variants
        single_content = f"#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2560000\n{original_url}"
        variant_content = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={VARIANTS['sd']},RESOLUTION=640x360",
            original_url,
            f"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={VARIANTS['hd']},RESOLUTION=1280x720",
            original_url
        ]
        # Use variants if channel isn't fallback
        content = "\n".join(variant_content) if channel_name != FALLBACK_STREAM["name"] else single_content
        individual_files[f"{BASE_PATH}/{channel_name}.m3u8"] = content
        final_m3u_content.append(f"{extinf}\n{github_url}")
        logger.info(f"Prepared {channel_name}.m3u8: {'with variants' if channel_name != FALLBACK_STREAM['name'] else 'single stream'}")

    # Write all files
    for file_path, content in individual_files.items():
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Wrote {file_path}: {content[:100]}...")
        except Exception as e:
            logger.error(f"Failed to write {file_path}: {e}")
    try:
        with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(final_m3u_content))
        logger.info(f"Wrote {FINAL_M3U_FILE} with {len(final_m3u_content)-1} entries")
    except Exception as e:
        logger.error(f"Failed to write {FINAL_M3U_FILE}: {e}")
    logger.info(f"Total files in {BASE_PATH}: {len(individual_files)}")

if __name__ == "__main__":
    main()
