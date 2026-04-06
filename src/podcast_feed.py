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
FEED_SUBCATEGORY = "Marketing"

# iTunes namespace — must register this so ElementTree uses 'itunes:' not 'ns0:'
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

# Where the feed + episodes are hosted (GitHub Pages)
DEFAULT_BASE_URL = "https://your-github-username.github.io/dispatch"


def _itunes(tag):
    """Helper to create an iTunes-namespaced tag name."""
    return f"{{{ITUNES_NS}}}{tag}"


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

        # Fix any stale URLs that include /podcast/ path segment
        bad_prefix = f"{base_url}/podcast/"
        good_prefix = f"{base_url}/"
        for item in channel.findall("item"):
            enclosure = item.find("enclosure")
            if enclosure is not None:
                url = enclosure.get("url", "")
                if bad_prefix in url:
                    enclosure.set("url", url.replace(bad_prefix, good_prefix))
            guid = item.find("guid")
            if guid is not None and guid.text and bad_prefix in guid.text:
                guid.text = guid.text.replace(bad_prefix, good_prefix)

        # Ensure required iTunes tags exist (backfill for older feeds)
        _ensure_itunes_tags(channel, base_url)
    else:
        root, channel, tree = _create_new_feed(base_url)

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

    guid = ET.SubElement(item, "guid")
    guid.set("isPermaLink", "true")
    guid.text = episode_url

    ET.SubElement(item, "pubDate").text = formatdate(localtime=True)

    # iTunes episode tags
    ET.SubElement(item, _itunes("summary")).text = description
    ET.SubElement(item, _itunes("episodeType")).text = "full"

    itunes_duration = ET.SubElement(item, _itunes("duration"))
    # Estimate duration: ~150 words per minute, ~5 chars per word
    estimated_seconds = max(60, int(len(script_text) / 5 / 150 * 60))
    minutes = estimated_seconds // 60
    seconds = estimated_seconds % 60
    itunes_duration.text = f"{minutes}:{seconds:02d}"

    # Insert new episode at the top (after channel metadata)
    items = channel.findall("item")
    if items:
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


def _create_new_feed(base_url: str):
    """Create a new podcast feed with all required Apple Podcasts tags."""
    root = ET.Element("rss")
    root.set("version", "2.0")
    root.set("xmlns:itunes", ITUNES_NS)

    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = FEED_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = formatdate(localtime=True)

    # iTunes channel tags — required by Apple Podcasts
    ET.SubElement(channel, _itunes("author")).text = FEED_AUTHOR
    ET.SubElement(channel, _itunes("type")).text = "episodic"
    ET.SubElement(channel, _itunes("explicit")).text = "false"

    itunes_owner = ET.SubElement(channel, _itunes("owner"))
    ET.SubElement(itunes_owner, _itunes("name")).text = FEED_AUTHOR
    ET.SubElement(itunes_owner, _itunes("email")).text = FEED_EMAIL

    itunes_category = ET.SubElement(channel, _itunes("category"))
    itunes_category.set("text", FEED_CATEGORY)
    sub_category = ET.SubElement(itunes_category, _itunes("category"))
    sub_category.set("text", FEED_SUBCATEGORY)

    # Cover art — required by Apple (must be 1400x1400 to 3000x3000)
    itunes_image = ET.SubElement(channel, _itunes("image"))
    itunes_image.set("href", f"{base_url}/cover.png")

    image = ET.SubElement(channel, "image")
    ET.SubElement(image, "url").text = f"{base_url}/cover.png"
    ET.SubElement(image, "title").text = FEED_TITLE
    ET.SubElement(image, "link").text = base_url

    tree = ET.ElementTree(root)
    return root, channel, tree


def _ensure_itunes_tags(channel, base_url: str):
    """Backfill missing iTunes tags on an existing feed so Apple Podcasts is happy."""
    # itunes:type
    if channel.find(_itunes("type")) is None:
        ET.SubElement(channel, _itunes("type")).text = "episodic"

    # itunes:owner
    if channel.find(_itunes("owner")) is None:
        itunes_owner = ET.SubElement(channel, _itunes("owner"))
        ET.SubElement(itunes_owner, _itunes("name")).text = FEED_AUTHOR
        ET.SubElement(itunes_owner, _itunes("email")).text = FEED_EMAIL

    # itunes:image
    if channel.find(_itunes("image")) is None:
        itunes_image = ET.SubElement(channel, _itunes("image"))
        itunes_image.set("href", f"{base_url}/cover.png")

    # itunes:author
    if channel.find(_itunes("author")) is None:
        ET.SubElement(channel, _itunes("author")).text = FEED_AUTHOR

    # itunes:explicit
    if channel.find(_itunes("explicit")) is None:
        ET.SubElement(channel, _itunes("explicit")).text = "false"

    # itunes:category with subcategory
    existing_cat = channel.find(_itunes("category"))
    if existing_cat is not None and existing_cat.find(_itunes("category")) is None:
        sub_category = ET.SubElement(existing_cat, _itunes("category"))
        sub_category.set("text", FEED_SUBCATEGORY)
