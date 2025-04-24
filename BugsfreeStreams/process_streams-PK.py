import os
import re
import requests
import shutil
import logging
import hashlib
import concurrent.futures
import time
from urllib.parse import urlparse

# Setup logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Configuration
REPO_OWNER = "bugsfreeweb"
REPO_NAME = "LiveTVCollector"
BRANCH = "main"
BASE_PATH = os.path.abspath("BugsfreeStreams/StreamsTV-PK")
FINAL_M3U_FILE = os.path.abspath("BugsfreeStreams/Output/StreamLinks-PK.m3u")
MAX_STREAMS = 1000
MAX_STREAMS_PER_SOURCE = 1000
DEFAULT_LOGO = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeLogo/default-logo.png"

# Default single source
DEFAULT_SOURCE = "https://iptv-org.github.io/iptv/countries/pk.m3u"

# Source M3U playlist(s) - primary and fallbacks
SOURCES = [DEFAULT_SOURCE]
FALLBACK_SOURCES = [
    "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/main/LiveTV/Pakistan/LiveTV.m3u",
]

# Static fallback M3U if all sources fail
STATIC_M3U = """
#EXTM3U
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Channel
http://iptv-org.github.io/iptv/sample.m3u8
"""

# Fallback test stream
FALLBACK_STREAM = {
    "extinf": f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" group-title="TEST",Test Stream',
    "url": "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
    "name": "test_stream"
}

# Validate a source URL
def validate_source(url):
    for attempt in range(3):
        try:
            response = requests.head(url, timeout=7, allow_redirects=True)
            content_type = response.headers.get("content-type", "").lower()
            logger.debug(f"Source {url}: status={response.status_code}, content-type={content_type}")
            return response.status_code == 200 and ("text" in content_type or "m3u" in content_type)
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt+1} failed for source {url}: {e}")
            if attempt < 2:
                time.sleep(1)
    logger.error(f"Source {url} unreachable after retries")
    return False

# Check if a URL is likely an active .m3u8 stream
def is_stream_active(url):
    if url.lower().endswith(".m3u8"):
        logger.debug(f"Skipping validation for .m3u8: {url}")
        return True
    for attempt in range(3):
        try:
            response = requests.get(url, timeout=5, stream=True)
            logger.debug(f"Checking stream {url}: status={response.status_code}")
            return response.status_code in (200, 206)
        except requests.RequestException as e:
            logger.warning(f"Attempt {attempt+1} failed for {url}: {e}")
            if attempt < 2:
                time.sleep(1)
    logger.debug(f"Stream inactive after retries: {url}")
    return False

# Fetch variant streams from a master M3U8
def get_variant_streams(master_url):
    variants = [
        {"resolution": "Original", "url": master_url, "bandwidth": 2560000}
    ]
    try:
        response = requests.get(master_url, timeout=5)
        if response.status_code != 200:
            return variants
        content = response.text
        if "#EXT-X-STREAM-INF" in content:
            lines = content.splitlines()
            for i, line in enumerate(lines):
                if line.startswith("#EXT-X-STREAM-INF"):
                    match = re.search(r'BANDWIDTH=(\d+).*?RESOLUTION=(\d+x\d+)', line)
                    if match:
                        bandwidth = int(match.group(1))
                        resolution = match.group(2)
                        variant_url = lines[i + 1].strip() if i + 1 < len(lines) else None
                        if variant_url and variant_url.startswith("http"):
                            variants.append({
                                "resolution": resolution,
                                "url": variant_url,
                                "bandwidth": bandwidth
                            })
                    elif "BANDWIDTH" in line:
                        bandwidth = int(re.search(r'BANDWIDTH=(\d+)', line).group(1))
                        variant_url = lines[i + 1].strip() if i + 1 < len(lines) else None
                        if variant_url and variant_url.startswith("http"):
                            variants.append({
                                "resolution": f"Variant_{len(variants)}",
                                "url": variant_url,
                                "bandwidth": bandwidth
                            })
        return [v for v in variants if is_stream_active(v["url"])]
    except Exception as e:
        logger.warning(f"Failed to fetch variants for {master_url}: {e}")
        return variants

# Clean channel name for filename
def clean_channel_name(name, url):
    if not name:
        return f"channel_{hashlib.md5(url.encode()).hexdigest()[:8]}"
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower().replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    return f"{name}_{hashlib.md5(url.encode()).hexdigest()[:8]}" if name else f"channel_{hashlib.md5(url.encode()).hexdigest()[:8]}"

# Add default logo to EXTINF if missing
def ensure_logo(extinf):
    if 'tvg-logo="' not in extinf or 'tvg-logo=""' in extinf:
        match = re.search(r'(#EXTINF:-?\d+\s+)(.*?),(.+)$', extinf)
        if match:
            return f'{match.group(1)}tvg-logo="{DEFAULT_LOGO}" {match.group(2)},{match.group(3)}'
        return extinf.replace('#EXTINF:', f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" ')
    return extinf

# Parse M3U content
def parse_m3u(content):
    entries = []
    lines = content.splitlines()
    extinf = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTINF:"):
            extinf = line
        elif line.startswith("http") and extinf:
            entries.append((extinf, line))
            extinf = None
    logger.info(f"Parsed {len(entries)} entries")
    return entries[:MAX_STREAMS_PER_SOURCE]

# Fetch and parse a single source
def process_source(source):
    if not validate_source(source):
        logger.error(f"Source {source} invalid, skipping")
        return []
    try:
        logger.info(f"Fetching {source}")
        response = requests.get(source, timeout=7)
        if response.status_code == 200:
            content = response.text
            entries = parse_m3u(content)
            logger.info(f"Found {len(entries)} entries in {source}")
            return entries
        else:
            logger.warning(f"Source {source} returned status {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {source}: {e}")
    return []

# Fetch sources concurrently
def fetch_all_sources(sources):
    all_entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_source = {executor.submit(process_source, source): source for source in sources}
        for future in concurrent.futures.as_completed(future_to_source):
            source = future_to_source[future]
            try:
                entries = future.result()
                all_entries.extend(entries)
            except Exception as e:
                logger.error(f"Source {source} failed: {e}")
    return all_entries

# Main processing logic
def main():
    logger.info("Starting stream processing")
    
    # Clean up old files
    if os.path.exists(BASE_PATH):
        shutil.rmtree(BASE_PATH)
        logger.info(f"Deleted old files in {BASE_PATH}")
    os.makedirs(BASE_PATH, exist_ok=True)
    os.makedirs(os.path.dirname(FINAL_M3U_FILE), exist_ok=True)

    # Fetch sources
    all_entries = fetch_all_sources(SOURCES + FALLBACK_SOURCES)
    logger.info(f"Total entries collected: {len(all_entries)}")

    # If no entries, use static M3U
    if not all_entries:
        logger.warning("No entries from sources, using static M3U")
        all_entries = parse_m3u(STATIC_M3U)

    logger.info(f"Processing {len(all_entries)} entries for uniqueness")

    # Validate streams and remove duplicates
    unique_streams = {}
    for extinf, url in all_entries:
        if len(unique_streams) >= MAX_STREAMS:
            logger.info(f"Reached MAX_STREAMS limit: {MAX_STREAMS}")
            break
        if not is_stream_active(url):
            logger.debug(f"Stream inactive: {url}")
            continue
        match = re.search(r',(.+)$', extinf)
        channel_name = clean_channel_name(match.group(1) if match else "", url)
        if channel_name in unique_streams:
            logger.debug(f"Skipping duplicate stream: {channel_name}")
            continue
        variants = get_variant_streams(url)
        unique_streams[channel_name] = (ensure_logo(extinf), url, variants)
        logger.info(f"Added valid stream: {channel_name} with {len(variants)} variants")

    logger.info(f"Total unique valid streams: {len(unique_streams)}")

    # Add fallback if no streams
    if not unique_streams:
        logger.warning("No valid streams found, adding fallback")
        variants = get_variant_streams(FALLBACK_STREAM["url"])
        unique_streams[FALLBACK_STREAM["name"]] = (FALLBACK_STREAM["extinf"], FALLBACK_STREAM["url"], variants)

    logger.info(f"Final unique streams: {len(unique_streams)}")

    # Prepare outputs
    final_m3u_content = ["#EXTM3U"]
    individual_files = {}
    for channel_name, (extinf, original_url, variants) in unique_streams.items():
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeStreams/StreamsTV-PK/{channel_name}.m3u8"
        file_path = os.path.join(BASE_PATH, f"{channel_name}.m3u8")
        # Create multi-resolution M3U8
        m3u8_content = ["#EXTM3U", "#EXT-X-VERSION:3"]
        for variant in variants:
            resolution = variant["resolution"]
            bandwidth = variant["bandwidth"]
            variant_url = variant["url"]
            m3u8_content.append(f"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={bandwidth},RESOLUTION={resolution}")
            m3u8_content.append(variant_url)
        individual_files[file_path] = "\n".join(m3u8_content)
        final_m3u_content.append(f"{extinf}\n{github_url}")

    # Write all files
    for file_path, content in individual_files.items():
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info(f"Wrote {file_path}")
        except OSError as e:
            logger.error(f"Failed to write {file_path}: {e}")
    try:
        with open(FINAL_M3U_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(final_m3u_content))
        logger.info(f"Wrote {FINAL_M3U_FILE} with {len(final_m3u_content)-1} entries")
    except OSError as e:
        logger.error(f"Failed to write {FINAL_M3U_FILE}: {e}")
    logger.info(f"Total files in {BASE_PATH}: {len(individual_files)}")

if __name__ == "__main__":
    main()
