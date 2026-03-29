"""Generate and maintain a podcast RSS feed for Dispatch episodes."""

import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
import time


# Feed metadata
FEED_TITLE = "Dispatch"
FEED_DESCRIPTION = "Your daily AI and B2B marketing intelligence briefing, powered by Pebble Marketing."
FEED_AUTHOR = "Laura McAliley"
FEED_EMAIL = "laura@pebble-marketing.com"
FEED_LANGUAGE = "en-us"
FEED_CATEGORY = "Business"

# Where the feed + episodes are hosted (GitHub Pages)
# This gets set from config.yaml or env var
DEFAULT_BASE_URL = "https://your-github-username.github.io/dispatch"


def generate_feed(mp3_path: str, script_text: str = "", config: dict = None) -> str:
    """Add today's episode to the podcast RSS feed.

    Args:
        mp3_path: Path to today's MP3 file.
        script_text: Episode description / show notes.
        config: Config dict (for base_url override).

    Returns:
        Path to the updated RSS feed XML file.
    """
    base_url = os.environ.get("PODCAST_BASE_URL", "")
    if not base_url and config:
        base_url = config.get("podcast_base_url", DEFAULT_BASE_URL)
    if not base_url:
        base_url = DEFAULT_BASE_URL

    base_url = base_url.rstrip("/")

    # Paths
    output_dir = Path(mp3_path).parent
    feed_dir = output_dir / "podcast"
    feed_dir.mkdir(exist_ok=True)
    feed_path = feed_dir / "feed.xml"

    # Date-stamp the episode file
    today = datetime.now().strftime("%Y-%m-%d")
    episode_filename = f"dispatch-{today}.mp3"
    episode_dest = feed_dir / episode_filename

    # Copy MP3 to podcast directory with dated name
    import shutil
    shutil.copy2(mp3_path, episode_dest)

    # Get file size for enclosure
    file_size = os.path.getsize(str(episode_dest))

    # Load existing feed or create new one
    if feed_path.exists():
        tree = ET.parse(str(feed_path))
        root = tree.getroot()
        channel = root.find("channel")
    else:
        root = ET.Element("rss")
        root.set("version", "2.0")
        root.set("xmlns:itunes", "http://www.itunes.com/dtds/podcast-1.0.dtd")
        channel = ET.SubElement(root, "channel")
        ET.SubElement(channel, "title").text = FEED_TITLE
        ET.SubElement(channel, "description").text = FEED_DESCRIPTION
        ET.SubElement(channel, "link").text = base_url
        ET.SubElement(channel, "language").text = FEED_LANGUAGE
        ET.SubElement(channel, "lastBuildDate").text = formatdate(localtime=True)

        # iTunes tags
        itunes_author = ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}author")
        itunes_author.text = FEED_AUTHOR
        itunes_category = ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}category")
        itunes_category.set("text", FEED_CATEGORY)
        itunes_explicit = ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}explicit")
        itunes_explicit.text = "false"

        # Podcast cover image
        itunes_image = ET.SubElement(channel, "{http://www.itunes.com/dtds/podcast-1.0.dtd}image")
        itunes_image.set("href", f"{base_url}/cover.png")
        image = ET.SubElement(channel, "image")
        ET.SubElement(image, "url").text = f"{base_url}/cover.png"
        ET.SubElement(image, "title").text = FEED_TITLE
        ET.SubElement(image, "link").text = base_url

        tree = ET.ElementTree(root)

    # Check if today's episode already exists
    for item in channel.findall("item"):
        guid = item.find("guid")
        if guid is not None and guid.text == f"{base_url}/{episode_filename}":
            print(f"  Episode for {today} already exists in feed")
            return str(feed_path)

    # Update lastBuildDate
    build_date = channel.find("lastBuildDate")
    if build_date is not None:
        build_date.text = formatdate(localtime=True)

    # Create new episode item
    item = ET.Element("item")

    day_name = datetime.now().strftime("%A, %B %d, %Y")
    ET.SubElement(item, "title").text = f"Dispatch — {day_name}"

    # Use first 500 chars of script as description
    description = script_text[:500] + "..." if len(script_text) > 500 else script_text
    ET.SubElement(item, "description").text = description

    episode_url = f"{base_url}/{episode_filename}"
    enclosure = ET.SubElement(item, "enclosure")
    enclosure.set("url", episode_url)
    enclosure.set("length", str(file_size))
    enclosure.set("type", "audio/mpeg")

    ET.SubElement(item, "guid").text = episode_url
    ET.SubElement(item, "pubDate").text = formatdate(localtime=True)

    itunes_duration = ET.SubElement(item, "{http://www.itunes.com/dtds/podcast-1.0.dtd}duration")
    # Estimate duration: ~150 words per minute, ~5 chars per word
    estimated_seconds = max(60, int(len(script_text) / 5 / 150 * 60))
    minutes = estimated_seconds // 60
    seconds = estimated_seconds % 60
    itunes_duration.text = f"{minutes}:{seconds:02d}"

    # Insert new episode at the top (after channel metadata)
    items = channel.findall("item")
    if items:
        # Insert before the first existing item
        channel.insert(list(channel).index(items[0]), item)
    else:
        channel.append(item)

    # Keep only last 30 episodes
    items = channel.findall("item")
    for old_item in items[30:]:
        channel.remove(old_item)

    # Write feed
    ET.indent(tree, space="  ")
    tree.write(str(feed_path), xml_declaration=True, encoding="utf-8")

    print(f"  Episode added: {episode_filename} ({file_size / 1024:.0f} KB)")
    print(f"  Feed updated: {feed_path}")
    print(f"  Feed URL: {base_url}/feed.xml")

    return str(feed_path)
