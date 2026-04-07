"""Generate and maintain a podcast RSS feed for Dispatch episodes.

Always rebuilds the feed XML from scratch to guarantee clean itunes:
namespace prefixes — Python's ElementTree retains ns0: from parsed files.
"""

import os
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import formatdate
from pathlib import Path


# Feed metadata
FEED_TITLE = "Dispatch"
FEED_DESCRIPTION = (
    "Your daily AI and B2B marketing intelligence briefing, "
    "powered by Pebble Marketing."
)
FEED_AUTHOR = "Laura McAliley"
FEED_EMAIL = "laura@pebble-marketing.com"
FEED_LANGUAGE = "en-us"
FEED_CATEGORY = "Business"
FEED_SUBCATEGORY = "Marketing"

# iTunes namespace
ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)

# Where the feed + episodes are hosted (GitHub Pages)
DEFAULT_BASE_URL = "https://your-github-username.github.io/dispatch"


def _itunes(tag):
    """Helper to create an iTunes-namespaced tag name."""
    return f"{{{ITUNES_NS}}}{tag}"


def generate_feed(mp3_path: str, script_text: str = "", config: dict = None) -> str:
    """Add today's episode to the podcast RSS feed.

    Rebuilds the entire feed XML from scratch every time, migrating
    existing episodes from the old feed. This guarantees clean itunes:
    namespace prefixes instead of ns0:.

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
    shutil.copy2(mp3_path, episode_dest)
    file_size = os.path.getsize(str(episode_dest))

    # ── Collect existing episodes from old feed ──────────────────────
    existing_episodes = []
    if feed_path.exists():
        try:
            old_tree = ET.parse(str(feed_path))
            old_channel = old_tree.getroot().find("channel")
            if old_channel is not None:
                for old_item in old_channel.findall("item"):
                    existing_episodes.append(old_item)
        except ET.ParseError:
            print("  Warning: could not parse old feed, starting fresh")

    # ── Build a brand-new feed from scratch ──────────────────────────
    root = ET.Element("rss")
    root.set("version", "2.0")
    # xmlns:itunes is added automatically by ET.register_namespace

    channel = ET.SubElement(root, "channel")

    # Required RSS channel tags
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = FEED_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = formatdate(localtime=True)

    # Required Apple Podcasts / iTunes tags
    ET.SubElement(channel, _itunes("author")).text = FEED_AUTHOR
    ET.SubElement(channel, _itunes("type")).text = "episodic"
    ET.SubElement(channel, _itunes("explicit")).text = "false"
    ET.SubElement(channel, _itunes("summary")).text = FEED_DESCRIPTION

    itunes_owner = ET.SubElement(channel, _itunes("owner"))
    ET.SubElement(itunes_owner, _itunes("name")).text = FEED_AUTHOR
    ET.SubElement(itunes_owner, _itunes("email")).text = FEED_EMAIL

    itunes_category = ET.SubElement(channel, _itunes("category"))
    itunes_category.set("text", FEED_CATEGORY)
    sub_category = ET.SubElement(itunes_category, _itunes("category"))
    sub_category.set("text", FEED_SUBCATEGORY)

    # Cover art — Apple requires 1400×1400 to 3000×3000
    itunes_image = ET.SubElement(channel, _itunes("image"))
    itunes_image.set("href", f"{base_url}/cover.png")

    image = ET.SubElement(channel, "image")
    ET.SubElement(image, "url").text = f"{base_url}/cover.png"
    ET.SubElement(image, "title").text = FEED_TITLE
    ET.SubElement(image, "link").text = base_url

    # ── Check if today's episode already exists ──────────────────────
    episode_url = f"{base_url}/{episode_filename}"
    episode_exists = False
    for ep in existing_episodes:
        guid = ep.find("guid")
        if guid is not None and guid.text and episode_filename in guid.text:
            episode_exists = True
            break

    # ── Create today's episode (if new) ──────────────────────────────
    if not episode_exists:
        new_item = _build_episode(
            base_url, episode_filename, file_size, script_text
        )
        channel.append(new_item)
        print(f"  Episode added: {episode_filename} ({file_size / 1024:.0f} KB)")

    # ── Migrate old episodes (rebuild each one cleanly) ──────────────
    for old_item in existing_episodes:
        clean_item = _rebuild_item(old_item, base_url)
        if clean_item is not None:
            channel.append(clean_item)

    # Keep only last 30 episodes
    items = channel.findall("item")
    for stale in items[30:]:
        channel.remove(stale)

    # ── Write the feed ───────────────────────────────────────────────
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(feed_path), xml_declaration=True, encoding="utf-8")

    print(f"  Feed updated: {feed_path}")
    print(f"  Feed URL: {base_url}/feed.xml")

    return str(feed_path)


def _build_episode(base_url, filename, file_size, script_text):
    """Build a clean <item> element for a new episode."""
    item = ET.Element("item")

    day_name = datetime.now().strftime("%A, %B %d, %Y")
    ET.SubElement(item, "title").text = f"Dispatch — {day_name}"

    description = (
        script_text[:500] + "..." if len(script_text) > 500 else script_text
    )
    ET.SubElement(item, "description").text = description

    episode_url = f"{base_url}/{filename}"
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

    # Estimate duration: ~150 words/min, ~5 chars/word
    estimated_seconds = max(60, int(len(script_text) / 5 / 150 * 60))
    minutes = estimated_seconds // 60
    seconds = estimated_seconds % 60
    ET.SubElement(item, _itunes("duration")).text = f"{minutes}:{seconds:02d}"

    return item


def _rebuild_item(old_item, base_url):
    """Rebuild an episode <item> with clean namespace prefixes.

    Extracts data from the old element (which may have ns0: tags)
    and creates a fresh element with proper itunes: namespace.
    """
    item = ET.Element("item")

    # Title
    title_el = old_item.find("title")
    title = title_el.text if title_el is not None else ""
    if not title:
        return None  # skip broken episodes
    ET.SubElement(item, "title").text = title

    # Description
    desc_el = old_item.find("description")
    desc = desc_el.text if desc_el is not None else ""
    ET.SubElement(item, "description").text = desc

    # Enclosure
    enc_el = old_item.find("enclosure")
    if enc_el is not None:
        url = enc_el.get("url", "")
        # Fix stale /podcast/ path segments
        bad = f"{base_url}/podcast/"
        good = f"{base_url}/"
        if bad in url:
            url = url.replace(bad, good)
        enclosure = ET.SubElement(item, "enclosure")
        enclosure.set("url", url)
        enclosure.set("length", enc_el.get("length", "0"))
        enclosure.set("type", enc_el.get("type", "audio/mpeg"))

    # GUID
    guid_el = old_item.find("guid")
    guid_text = guid_el.text if guid_el is not None else ""
    if guid_text:
        bad = f"{base_url}/podcast/"
        good = f"{base_url}/"
        if bad in guid_text:
            guid_text = guid_text.replace(bad, good)
    guid = ET.SubElement(item, "guid")
    guid.set("isPermaLink", "true")
    guid.text = guid_text

    # pubDate
    pub_el = old_item.find("pubDate")
    if pub_el is not None and pub_el.text:
        ET.SubElement(item, "pubDate").text = pub_el.text

    # iTunes episode tags (rebuild with proper namespace)
    ET.SubElement(item, _itunes("summary")).text = desc
    ET.SubElement(item, _itunes("episodeType")).text = "full"

    # Duration — try to find it under any namespace prefix
    duration_text = None
    for child in old_item:
        if "duration" in child.tag.lower():
            duration_text = child.text
            break
    if duration_text:
        ET.SubElement(item, _itunes("duration")).text = duration_text
    else:
        ET.SubElement(item, _itunes("duration")).text = "5:00"

    return item
