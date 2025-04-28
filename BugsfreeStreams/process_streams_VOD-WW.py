import os
import re
import requests
import shutil
import logging
import hashlib
import concurrent.futures
import time
import json
from datetime import datetime, timedelta
from urllib.parse import urlparse
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Setup logging
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

# Configuration
REPO_OWNER = "bugsfreeweb"
REPO_NAME = "LiveTVCollector"
BRANCH = "main"
BASE_PATH = os.path.abspath("BugsfreeStreams/StreamsVOD-WW")
FINAL_M3U_FILE = os.path.abspath("BugsfreeStreams/Output/Movies/VODLinks-WW.m3u")
PROCESSED_LINKS_FILE = os.path.abspath("BugsfreeStreams/VOD_processed_links-WW.json")
MAX_STREAMS = 600  # Target 500+ streams
MAX_STREAMS_PER_SOURCE = 1000
VALIDATION_TIMEOUT = 60  # Max 60 seconds for validation
REVALIDATION_INTERVAL = 24 * 3600  # Revalidate every 24 hours
DEFAULT_LOGO = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}/BugsfreeLogo/default-logo.png"

# Source M3U playlist
SOURCES = [
    "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/refs/heads/main/Movies/Hollywood/Movies.m3u",  # Replaced 404 URL
]
FALLBACK_SOURCES = [
    "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/refs/heads/main/Movies/Hollywood/Movies.m3u",
]

# Static fallback M3U
STATIC_M3U = """
#EXTM3U
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Movie M3U8
http://iptv-org.github.io/iptv/sample.m3u8
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Movie MP4
https://archive.org/download/ElephantsDream/ed_1024_512kb.mp4
#EXTINF:-1 tvg-logo="https://example.com/logo.png" group-title="TEST",Sample Movie MKV
https://archive.org/download/ElephantsDream/ed_1024.ogv
"""

# Fallback test stream
FALLBACK_STREAM = {
    "extinf": f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" group-title="TEST",Test Movie',
    "url": "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
    "name": "test_movie"
}

# Create a session with retries
def create_session():
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# Load processed links
def load_processed_links():
    if os.path.exists(PROCESSED_LINKS_FILE):
        try:
            with open(PROCESSED_LINKS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load {PROCESSED_LINKS_FILE}: {e}. Deleting corrupted file.")
            try:
                os.remove(PROCESSED_LINKS_FILE)
                logger.info(f"Deleted corrupted {PROCESSED_LINKS_FILE}")
            except OSError as e:
                logger.error(f"Failed to delete {PROCESSED_LINKS_FILE}: {e}")
    return {}

# Save processed links
def save_processed_links(processed_links):
    try:
        with open(PROCESSED_LINKS_FILE, "w", encoding="utf-8") as f:
            json.dump(processed_links, f, indent=2)
        logger.info(f"Saved {len(processed_links)} processed links to {PROCESSED_LINKS_FILE}")
    except Exception as e:
        logger.error(f"Failed to save {PROCESSED_LINKS_FILE}: {e}")

# Validate a source URL
def validate_source(url, session):
    try:
        response = session.head(url, timeout=7, allow_redirects=True)
        content_type = response.headers.get("content-type", "").lower()
        return response.status_code == 200 and ("text" in content_type or "m3u" in content_type)
    except requests.RequestException as e:
        logger.error(f"Source {url} unreachable: {e}")
        return False

# Check if a URL is active
def is_stream_active(url, session):
    valid_extensions = (".m3u8", ".mp4", ".mkv", ".ogv")
    if not url.lower().endswith(valid_extensions):
        logger.debug(f"Skipping invalid extension for {url}")
        return False
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        logger.debug(f"Validating {url} with GET")
        response = session.get(url, timeout=3, allow_redirects=True, stream=True, headers=headers)
        if response.status_code in (200, 206, 301, 302):
            if url.lower().endswith(".m3u8"):
                content = response.text[:100]
                if "#EXTM3U" in content:
                    logger.debug(f"Validated .m3u8 {url}")
                    return True
                logger.debug(f"Failed .m3u8 validation for {url}: no #EXTM3U")
            else:
                logger.debug(f"Validated {url} with GET status {response.status_code}")
                return True
        logger.debug(f"Failed GET validation for {url}: status {response.status_code}, headers: {response.headers}")
        # Fallback to HEAD
        logger.debug(f"Retrying {url} with HEAD")
        response = session.head(url, timeout=3, allow_redirects=True, headers=headers)
        if response.status_code in (200, 206, 301, 302):
            logger.debug(f"Validated {url} with HEAD status {response.status_code}")
            return True
        logger.debug(f"Failed HEAD validation for {url}: status {response.status_code}, headers: {response.headers}")
        return False
    except requests.RequestException as e:
        logger.debug(f"Failed validation for {url}: {e}")
        return False

# Validate streams concurrently
def validate_streams_concurrently(entries, processed_links, session):
    valid_streams = []
    to_validate = []
    now = time.time()
    start_time = now

    for extinf, url in entries:
        if url in processed_links:
            last_checked = processed_links[url].get("last_checked", 0)
            is_active = processed_links[url].get("is_active", False)
            if is_active and (now - last_checked) < REVALIDATION_INTERVAL:
                valid_streams.append((extinf, url))
                logger.info(f"Skipped validation for cached active stream: {url}")
                continue
        to_validate.append((extinf, url))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_entry = {executor.submit(is_stream_active, url, session): (extinf, url) for extinf, url in to_validate}
        for future in concurrent.futures.as_completed(future_to_entry):
            if time.time() - start_time > VALIDATION_TIMEOUT:
                logger.warning("Validation timeout reached")
                break
            extinf, url = future_to_entry[future]
            try:
                if future.result():
                    valid_streams.append((extinf, url))
                    processed_links[url] = {
                        "last_checked": time.time(),
                        "is_active": True
                    }
                else:
                    processed_links[url] = {
                        "last_checked": time.time(),
                        "is_active": False
                    }
            except Exception as e:
                logger.error(f"Validation error for {url}: {e}")
                processed_links[url] = {
                    "last_checked": time.time(),
                    "is_active": False
                }
    return valid_streams

# Fetch variant streams (only for .m3u8)
def get_variant_streams(master_url, session):
    variants = [{"resolution": "Original", "url": master_url, "bandwidth": 2560000}]
    if not master_url.lower().endswith(".m3u8") or not is_stream_active(master_url, session):
        return variants
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = session.get(master_url, timeout=3, headers=headers)
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
        return [v for v in variants if is_stream_active(v["url"], session)] or variants
    except Exception:
        return variants

# Clean channel name
def clean_channel_name(name, url):
    if not name:
        return f"movie_{hashlib.md5(url.encode()).hexdigest()[:8]}"
    name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip().lower().replace(' ', '_')
    name = re.sub(r'_+', '_', name)
    return f"{name}_{hashlib.md5(url.encode()).hexdigest()[:8]}" if name else f"movie_{hashlib.md5(url.encode()).hexdigest()[:8]}"

# Add default logo and last-checked timestamp
def ensure_logo(extinf):
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    if 'tvg-logo="' not in extinf or 'tvg-logo=""' in extinf:
        match = re.search(r'(#EXTINF:-?\d+\s+)(.*?),(.+)$', extinf)
        if match:
            return f'{match.group(1)}tvg-logo="{DEFAULT_LOGO}" tvg-last-checked="{now}" {match.group(2)},{match.group(3)}'
        return extinf.replace('#EXTINF:', f'#EXTINF:-1 tvg-logo="{DEFAULT_LOGO}" tvg-last-checked="{now}" ')
    if 'tvg-last-checked="' not in extinf:
        match = re.search(r'(#EXTINF:-?\d+\s+.*?)(,.*)$', extinf)
        if match:
            return f'{match.group(1)} tvg-last-checked="{now}"{match.group(2)}'
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
            logger.debug(f"Parsed URL: {line}")
            entries.append((extinf, line))
            extinf = None
    logger.info(f"Parsed {len(entries)} entries")
    return entries[:MAX_STREAMS_PER_SOURCE]

# Fetch and parse a source
def process_source(source, session):
    if not validate_source(source, session):
        logger.error(f"Source {source} invalid, skipping")
        return []
    try:
        logger.info(f"Fetching {source}")
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        response = session.get(source, timeout=7, headers=headers)
        if response.status_code == 200:
            content = response.text
            logger.info(f"Fetched {len(content)} bytes from {source}")
            entries = parse_m3u(content)
            logger.info(f"Found {len(entries)} entries in {source}")
            return entries
        else:
            logger.warning(f"Source {source} returned status {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to fetch {source}: {e}")
    return []

# Fetch sources concurrently
def fetch_all_sources(sources, session):
    all_entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        future_to_source = {executor.submit(process_source, source, session): source for source in sources}
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
    
    # Create session with retries
    session = create_session()

    # Load processed links
    processed_links = load_processed_links()

    # Clean up old files
    if os.path.exists(BASE_PATH):
        shutil.rmtree(BASE_PATH)
        logger.info(f"Deleted old files in {BASE_PATH}")
    os.makedirs(BASE_PATH, exist_ok=True)
    os.makedirs(os.path.dirname(FINAL_M3U_FILE), exist_ok=True)

    # Fetch sources
    all_entries = fetch_all_sources(SOURCES + FALLBACK_SOURCES, session)
    logger.info(f"Total entries collected: {len(all_entries)}")

    # If no entries, use static M3U
    if not all_entries:
        logger.warning("No entries from sources, using static M3U")
        all_entries = parse_m3u(STATIC_M3U)

    # Validate streams
    logger.info(f"Validating {len(all_entries)} streams concurrently")
    all_entries = validate_streams_concurrently(all_entries, processed_links, session)
    logger.info(f"Found {len(all_entries)} active streams after validation")

    # Save processed links
    save_processed_links(processed_links)

    # Sort to prioritize .m3u8, then .mp4, then .mkv
    def sort_key(entry):
        url = entry[1].lower()
        if url.endswith(".m3u8"):
            return 0
        elif url.endswith(".mp4"):
            return 1
        elif url.endswith((".mkv", ".ogv")):
            return 2
        return 3
    all_entries.sort(key=sort_key)

    # Process for uniqueness
    logger.info(f"Processing {len(all_entries)} entries for uniqueness")
    m3u8_count = 0
    mp4_count = 0
    mkv_count = 0
    unique_streams = {}
    for i, (extinf, url) in enumerate(all_entries):
        if len(unique_streams) >= MAX_STREAMS:
            logger.info(f"Reached MAX_STREAMS limit: {MAX_STREAMS}")
            break
        if i % 100 == 0:
            logger.info(f"Processed {i} of {len(all_entries)} entries, {len(unique_streams)} valid streams")
        if url.lower().endswith(".m3u8"):
            m3u8_count += 1
        elif url.lower().endswith(".mp4"):
            mp4_count += 1
        elif url.lower().endswith((".mkv", ".ogv")):
            mkv_count += 1
        if url in unique_streams:
            continue
        match = re.search(r',(.+)$', extinf)
        channel_name = clean_channel_name(match.group(1) if match else "", url)
        variants = get_variant_streams(url, session) if url.lower().endswith(".m3u8") else [{"resolution": "Original", "url": url, "bandwidth": 2560000}]
        unique_streams[url] = (ensure_logo(extinf), url, variants, channel_name)
        logger.info(f"Added valid stream: {channel_name} for URL {url}")

    logger.info(f"Processed {m3u8_count} .m3u8 streams, {mp4_count} .mp4 streams, {mkv_count} .mkv streams")
    logger.info(f"Total unique valid streams: {len(unique_streams)}")

    # Add fallback if no streams
    if not unique_streams:
        logger.warning("No valid streams found, adding fallback")
        variants = get_variant_streams(FALLBACK_STREAM["url"], session)
        unique_streams[FALLBACK_STREAM["url"]] = (FALLBACK_STREAM["extinf"], FALLBACK_STREAM["url"], variants, FALLBACK_STREAM["name"])

    logger.info(f"Final unique streams: {len(unique_streams)}")

    # Prepare outputs
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    final_m3u_content = [f'#EXTM3U tvg-updated="{now}"']
    individual_files = {}
    for url, (extinf, original_url, variants, channel_name) in unique_streams.items():
        file_ext = ".m3u"
        github_url = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/refs/heads/{BRANCH}/BugsfreeStreams/StreamsVOD-WW/{channel_name}{file_ext}"
        file_path = os.path.join(BASE_PATH, f"{channel_name}{file_ext}")
        m3u_content = ["#EXTM3U", "#EXT-X-VERSION:3"]
        for variant in variants:
            resolution = variant["resolution"]
            bandwidth = variant["bandwidth"]
            variant_url = variant["url"]
            m3u_content.append(f"#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH={bandwidth},RESOLUTION={resolution}")
            m3u_content.append(variant_url)
        individual_files[file_path] = "\n".join(m3u_content)
        final_m3u_content.append(f"{extinf}\n{github_url}")
        logger.info(f"Prepared file {file_path} for {channel_name}")

    # Write files
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
