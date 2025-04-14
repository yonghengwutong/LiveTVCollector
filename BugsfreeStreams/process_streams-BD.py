import os
import re
import requests
import shutil
import logging

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

# Default single source
DEFAULT_SOURCE = "https://aynaxpranto.vercel.app/files/playlist.m3u"

# Static fallback M3U if all sources fail
STATIC_M3U = """
#EXTM3U
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Channel
http://sample-stream.com/stream.m3u8
"""

# Source M3U playlist(s) - single URL or list
SOURCES = DEFAULT_SOURCE
MULTI_SOURCES = [
    "https://raw.githubusercontent.com/MohammadJoyChy/BDIXTV/refs/heads/main/Aynaott",
    "https://aynaxpranto.vercel.app/files/playlist.m3u"
]

# Fallback test stream
FALLBACK_STREAM = {
    "extinf": f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" group-title="TEST",Test Stream',
    "url": "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
    "name": "Test_Stream"
}

# Validate a source URL
def validate_source(url):
    try:
        response = requests.head(url, timeout=5, allow_redirects=True)
        logger.info(f"Source {url}: status={response.status_code}, headers={response.headers}")
        return response.status_code == 200
    except requests.RequestException as e:
        logger.warning(f"Source {url} unreachable: {e}")
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
            logger.info(f"Content sample: {content[:200]}")
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
    
    # Clean up old files
    if os.path.exists(BASE_PATH):
        shutil.rmtree(BASE_PATH)
        logger.info(f"Deleted old files in {BASE_PATH}")
    os.makedirs(BASE_PATH, exist_ok=True)

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

    # Add fallback if no streams
    if not unique_streams:
        logger.warning("No valid streams found, adding fallback")
        unique_streams[FALLBACK_STREAM["name"]] = (FALLBACK_STREAM["extinf"], FALLBACK_STREAM["url"])

    logger.info(f"Total unique valid streams: {len(unique_streams)}")

    # Prepare outputs
    final_m3u_content = ["#EXTM3U"]
    individual_files = {}
    for channel_name, (extinf, original_url) in unique_streams.items():
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeStreams/LiveTV/{channel_name}.m3u8"
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
