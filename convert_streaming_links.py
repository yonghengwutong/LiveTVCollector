import os
import requests
from pathlib import Path
import re

# Define input sources
SOURCES = [
    "https://raw.githubusercontent.com/sydul104/main04/refs/heads/main/my",
    "https://raw.githubusercontent.com/Miraz6755/Bdixtv/refs/heads/main/Livetv.m3u8",
    "https://raw.githubusercontent.com/Yeadee/Toffee/refs/heads/main/toffee_ns_player.m3u",
    "https://raw.githubusercontent.com/MohammadJoyChy/BDIXTV/refs/heads/main/Aynaott",
    "https://raw.githubusercontent.com/Arunjunan20/My-IPTV/refs/heads/main/index.html",
    "https://aynaxpranto.vercel.app/files/playlist.m3u",
    "https://iptv-org.github.io/iptv/countries/us.m3u"
]

# Define output directory
OUTPUT_DIR = Path("BugsfreeStreams/LiveTV")
GITHUB_REPO_URL = "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/refs/heads/main"

# Ensure output directory exists
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def is_link_active(url):
    """Check if a link is active."""
    try:
        response = requests.head(url, timeout=10)
        return response.status_code == 200
    except requests.RequestException:
        return False

def sanitize_filename(name):
    """Sanitize string to be a valid filename."""
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name)

def process_sources():
    """Process all sources and generate output files."""
    processed_links = set()

    for source in SOURCES:
        try:
            response = requests.get(source, timeout=10)
            response.raise_for_status()
            lines = response.text.splitlines()
        except requests.RequestException as e:
            print(f"Failed to fetch source {source}: {e}")
            continue

        current_metadata = None
        for line in lines:
            if line.startswith("#EXTINF:"):
                current_metadata = line
            elif line.startswith("http"):
                if is_link_active(line):
                    # Generate file name
                    match = re.search(r"group-title=\"(.*?)\",(.*)", current_metadata)
                    if match:
                        group_title, channel_name = match.groups()
                        file_name = sanitize_filename(channel_name) + ".m3u"
                        file_path = OUTPUT_DIR / file_name

                        # Avoid duplicate links
                        if file_path not in processed_links:
                            processed_links.add(file_path)
                            # Write to file
                            with open(file_path, "w") as f:
                                f.write(f"{current_metadata}\n{GITHUB_REPO_URL}/{OUTPUT_DIR}/{file_name}\n")
                                print(f"Processed {channel_name}")

if __name__ == "__main__":
    process_sources()
