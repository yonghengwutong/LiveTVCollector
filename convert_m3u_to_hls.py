import ffmpeg
import requests
import os
import re
from urllib.parse import urlparse
from multiprocessing import Pool, cpu_count

# Configuration
input_m3u_urls = [
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/us.m3u",
]
output_dir = "iptv_hls_output"
final_m3u_file = os.path.join(output_dir, "final_output.m3u")
github_base_url = "https://raw.githubusercontent.com/bugsfreeweb/LiveTVCollector/main/iptv_hls_output/"  # Adjust for your repo

# Create output directory
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Store processed streams to avoid duplicates
processed_urls = set()
final_m3u_entries = []

def process_stream(args):
    extinf, stream_url = args
    if not stream_url or stream_url in processed_urls:
        print(f"Skipping duplicate or invalid stream: {stream_url}")
        return None, None
    
    channel_name_match = re.search(r',(.+)$', extinf)
    channel_name = channel_name_match.group(1).strip() if channel_name_match else f"Stream_{len(processed_urls)}"
    safe_channel_name = re.sub(r'[^\w\-]', '_', channel_name)
    
    tvg_id = re.search(r'tvg-id="([^"]*)"', extinf)
    tvg_id = tvg_id.group(1) if tvg_id else ""
    
    tvg_logo = re.search(r'tvg-logo="([^"]*)"', extinf)
    tvg_logo = tvg_logo.group(1) if tvg_logo else ""
    
    group_title = re.search(r'group-title="([^"]*)"', extinf)
    group_title = group_title.group(1) if group_title else "Uncategorized"
    
    print(f"Processing stream: {channel_name} ({stream_url})")
    
    output_m3u8 = os.path.join(output_dir, f"{safe_channel_name}.m3u8")
    segment_pattern = os.path.join(output_dir, f"{safe_channel_name}_segment%d.ts")
    
    try:
        print(f"Checking stream availability: {stream_url}")
        response = requests.get(stream_url, stream=True, timeout=10)
        if response.status_code != 200:
            print(f"Stream unavailable: {stream_url} (Status: {response.status_code})")
            return None, None
        response.close()
        
        stream = ffmpeg.input(stream_url, t='5')  # Limit to 5 seconds
        stream = ffmpeg.output(
            stream,
            output_m3u8,
            format='hls',
            hls_time=2,  # Smaller segments
            hls_list_size=0,
            hls_segment_filename=segment_pattern,
            c_v='libx264',
            c_a='aac'
        )
        print(f"Converting to HLS: {output_m3u8}")
        ffmpeg.run(stream, quiet=False)
        print(f"Converted to {output_m3u8}")
        
        extinf_line = f'#EXTINF:-1 tvg-id="{tvg_id}" tvg-logo="{tvg_logo}" group-title="{group_title}",{channel_name}'
        hls_url = f"{github_base_url}{safe_channel_name}.m3u8"
        print(f"Adding to M3U: {extinf_line} -> {hls_url}")
        return extinf_line, hls_url
    
    except ffmpeg.Error as e:
        error_msg = e.stderr.decode('utf-8') if e.stderr else "No error details"
        print(f"FFmpeg error converting {stream_url}: {error_msg}")
        return None, None
    except requests.RequestException as e:
        print(f"Network error for {stream_url}: {str(e)}")
        return None, None
    except Exception as e:
        print(f"Unexpected error for {stream_url}: {str(e)}")
        return None, None

# Fetch and process streams
stream_tasks = [
    ('#EXTINF:-1 tvg-id="Test" tvg-logo="https://example.com/test.jpg" group-title="Test",Big Buck Bunny',
     'http://sample.vodobox.net/shaka_bbb_vp9_enc_30s/main.m3u8')
]

for m3u_url in input_m3u_urls:
    print(f"Fetching M3U: {m3u_url}")
    response = requests.get(m3u_url)
    if response.status_code != 200:
        print(f"Failed to fetch M3U file: {m3u_url} (Status: {response.status_code})")
        continue
    
    m3u_content = response.text.splitlines()
    print(f"Found {len(m3u_content)} lines in {m3u_url}")
    print(f"M3U content sample: {m3u_content[:5]}")
    
    for i in range(len(m3u_content)):
        if m3u_content[i].startswith('#EXTINF:'):
            extinf = m3u_content[i]
            stream_url = m3u_content[i + 1].strip() if i + 1 < len(m3u_content) and not m3u_content[i + 1].startswith('#') else None
            if stream_url:
                print(f"Found stream: {extinf} -> {stream_url}")
                stream_tasks.append((extinf, stream_url))
            else:
                print(f"No stream URL for EXTINF: {extinf}")

print(f"Total streams to process: {len(stream_tasks)}")

# Parallel processing with error tolerance
if stream_tasks:
    with Pool(processes=cpu_count()) as pool:
        results = pool.map(process_stream, stream_tasks[:5])  # Limit to 5 for testing
    
    # Collect results
    for extinf_line, hls_url in results:
        if extinf_line and hls_url:
            final_m3u_entries.append(extinf_line)
            final_m3u_entries.append(hls_url)
            processed_urls.add(hls_url.split('/')[-2])
            print(f"Collected: {extinf_line} -> {hls_url}")
        else:
            print("No valid result returned for a stream")
else:
    print("No streams to process")

# Write the final M3U file
with open(final_m3u_file, 'w') as f:
    f.write("#EXTM3U\n")
    if final_m3u_entries:
        f.write("\n".join(final_m3u_entries))
        f.write("\n")
    else:
        print("Warning: No entries added to final M3U file")

print("\nConversion complete!")
print(f"All HLS files saved to: {output_dir}")
print(f"Final M3U playlist saved to: {final_m3u_file}")
print(f"Total entries in M3U: {len(final_m3u_entries) // 2}")
