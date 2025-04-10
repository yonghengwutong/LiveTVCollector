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

# Define output file
OUTPUT_DIR = Path("BugsfreeStreams")
OUTPUT_FILE = OUTPUT_DIR / "FinalStreamLinks.m3u"
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
    """Process all sources and generate the final output file."""
    processed_links = set()

    with open(OUTPUT_FILE, "w") as final_file:
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
                    if is_link_active(line) and line not in processed_links:
                        processed_links.add(line)

                        # Write to the final file
                        final_file.write(f"{current_metadata}\n{line}\n")
                        print(f"Added link: {line}")

if __name__ == "__main__":
    process_sources()
