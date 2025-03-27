const axios = require('axios');
const m3u8Parser = require('m3u8-parser');
const fs = require('fs').promises;
const path = require('path');
const yaml = require('js-yaml');
const pLimit = require('p-limit');

// Load configuration from YAML file
async function loadConfig() {
    try {
        const configContent = await fs.readFile('config.yml', 'utf8');
        return yaml.load(configContent);
    } catch (error) {
        console.error('Error loading config.yml:', error.message);
        process.exit(1);
    }
}

// Function to fetch M3U content from a URL
async function fetchM3U(url, timeout) {
    try {
        const response = await axios.get(url, { timeout });
        if (response.status !== 200) {
            throw new Error(`Failed to fetch ${url}: Status ${response.status}`);
        }
        return response.data;
    } catch (error) {
        console.error(`Error fetching ${url}:`, error.message);
        return null;
    }
}

// Function to parse M3U content and extract channel links
function parseM3U(content) {
    const parser = new m3u8Parser.Parser();
    parser.push(content);
    parser.end();

    const manifest = parser.manifest;
    const channels = [];

    // Handle EXTINF entries for M3U playlists
    const lines = content.split('\n');
    let currentChannel = null;
    lines.forEach(line => {
        line = line.trim();
        if (line.startsWith('#EXTINF')) {
            const nameMatch = line.match(/,(.+)/);
            currentChannel = {
                name: nameMatch ? nameMatch[1] : 'Unknown',
                url: null
            };
        } else if (line && !line.startsWith('#') && currentChannel) {
            currentChannel.url = line;
            channels.push(currentChannel);
            currentChannel = null;
        }
    });

    return channels.filter(ch => ch.url); // Only return channels with URLs
}

// Function to check if a link is active
async function checkLinkActive(url, timeout) {
    try {
        const response = await axios.head(url, { timeout });
        return response.status >= 200 && response.status < 400;
    } catch (error) {
        console.error(`Link ${url} is inactive:`, error.message);
        return false;
    }
}

// Function to collect and process all M3U links
async function collectActiveLinks(urls, concurrency, fetchTimeout, linkCheckTimeout) {
    const limit = pLimit(concurrency); // Limit concurrent requests
    const allChannels = new Map(); // Use Map to avoid duplicates (keyed by URL)

    // Fetch all M3U playlists concurrently
    const fetchPromises = urls.map(url =>
        limit(async () => {
            console.log(`Fetching M3U from ${url}...`);
            const m3uContent = await fetchM3U(url, fetchTimeout);
            if (!m3uContent) return [];

            console.log(`Parsing M3U from ${url}...`);
            const channels = parseM3U(m3uContent);
            console.log(`Found ${channels.length} channels in ${url}`);
            return channels;
        })
    );

    // Wait for all fetches to complete
    const allChannelsArrays = await Promise.all(fetchPromises);
    const allChannelsList = allChannelsArrays.flat();

    // Check link activity concurrently
    const checkPromises = allChannelsList.map(channel =>
        limit(async () => {
            if (!allChannels.has(channel.url)) {
                console.log(`Checking if ${channel.url} is active...`);
                const isActive = await checkLinkActive(channel.url, linkCheckTimeout);
                if (isActive) {
                    allChannels.set(channel.url, channel);
                    console.log(`Added active link: ${channel.url}`);
                } else {
                    console.log(`Skipped inactive link: ${channel.url}`);
                }
            } else {
                console.log(`Skipped duplicate link: ${channel.url}`);
            }
        })
    );

    await Promise.all(checkPromises);
    return Array.from(allChannels.values());
}

// Function to split channels into chunks of specified size
function splitChannels(channels, channelsPerFile) {
    const chunks = [];
    for (let i = 0; i < channels.length; i += channelsPerFile) {
        chunks.push(channels.slice(i, i + channelsPerFile));
    }
    return chunks;
}

// Function to save active links to multiple formats with splitting
async function saveResults(channels, outputDirPrefix, channelsPerFile) {
    // Split channels into chunks of channelsPerFile
    const channelChunks = splitChannels(channels, channelsPerFile);

    // Process each chunk
    for (let i = 0; i < channelChunks.length; i++) {
        const chunk = channelChunks[i];
        const suffix = i === 0 ? '' : (i + 1); // SpecialLinks, SpecialLinks2, etc.
        const outputDir = `${outputDirPrefix}${suffix}`;
        const baseName = `SpecialLinks${suffix}`;

        // Create output directory if it doesn't exist
        await fs.mkdir(outputDir, { recursive: true });

        // Save as M3U
        let m3uContent = '#EXTM3U\n';
        chunk.forEach(channel => {
            m3uContent += `#EXTINF:-1,${channel.name}\n${channel.url}\n`;
        });
        await fs.writeFile(path.join(outputDir, `${baseName}.m3u`), m3uContent);
        await fs.writeFile(`${baseName}.m3u`, m3uContent); // Also save in root

        // Save as JSON
        const jsonContent = JSON.stringify(chunk, null, 2);
        await fs.writeFile(path.join(outputDir, `${baseName}.json`), jsonContent);
        await fs.writeFile(`${baseName}.json`, jsonContent); // Also save in root

        // Save as TXT
        const txtContent = chunk.map(channel => channel.url).join('\n');
        await fs.writeFile(path.join(outputDir, `${baseName}.txt`), txtContent);
        await fs.writeFile(`${baseName}.txt`, txtContent); // Also save in root

        console.log(`Saved ${chunk.length} active links to ${outputDir}/${baseName}.* and root directory`);
    }
}

// Main function to run the script
async function main() {
    console.log('Starting M3U link collection...');

    // Load configuration
    const config = await loadConfig();
    const { urls, settings } = config;
    const { concurrency, fetchTimeout, linkCheckTimeout, outputDirPrefix, channelsPerFile } = settings;

    // Collect active links
    const activeChannels = await collectActiveLinks(urls, concurrency, fetchTimeout, linkCheckTimeout);

    // Save results with splitting
    if (activeChannels.length > 0) {
        await saveResults(activeChannels, outputDirPrefix, channelsPerFile);
    } else {
        console.log('No active links found.');
    }

    console.log('M3U link collection completed.');
}

main().catch(error => {
    console.error('Script failed:', error.message);
    process.exit(1);
});
