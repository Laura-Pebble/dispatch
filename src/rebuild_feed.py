"""Standalone feed rebuilder — always produces a clean feed.xml from existing MP3 files.

This runs as a separate workflow step AFTER the main pipeline, ensuring
the feed always has proper iTunes namespace tags regardless of whether
the pipeline completed or exited early.
"""

import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import formatdate
from pathlib import Path
from mutagen.mp3 import MP3


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

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"
ET.register_namespace("itunes", ITUNES_NS)


def _itunes(tag):
    return f"{{{ITUNES_NS}}}{tag}"


def rebuild_feed():
    """Scan output/podcast/ for MP3 files and build a fresh feed.xml."""
    base_url = os.environ.get(
        "PODCAST_BASE_URL", "https://laura-pebble.github.io/dispatch"
    ).rstrip("/")

    podcast_dir = Path(__file__).parent.parent / "output" / "podcast"
    feed_path = podcast_dir / "feed.xml"

    if not podcast_dir.exists():
        print("No podcast directory found — nothing to do.")
        return

    # Find all MP3 files
    mp3_files = sorted(podcast_dir.glob("dispatch-*.mp3"), reverse=True)
    if not mp3_files:
        print("No episode MP3 files found — nothing to do.")
        return

    print(f"Found {len(mp3_files)} episode(s), rebuilding feed.xml from scratch...")

    # ── Try to preserve descriptions from old feed ───────────────────
    old_descriptions = {}
    if feed_path.exists():
        try:
            old_tree = ET.parse(str(feed_path))
            old_channel = old_tree.getroot().find("channel")
            if old_channel is not None:
                for item in old_channel.findall("item"):
                    guid_el = item.find("guid")
                    desc_el = item.find("description")
                    pub_el = item.find("pubDate")
                    if guid_el is not None and guid_el.text:
                        old_descriptions[guid_el.text] = {
                            "description": desc_el.text if desc_el is not None else "",
                            "pubDate": pub_el.text if pub_el is not None else None,
                        }
        except ET.ParseError:
            print("  Warning: could not parse old feed")

    # ── Build brand-new feed ─────────────────────────────────────────
    root = ET.Element("rss")
    root.set("version", "2.0")

    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "link").text = base_url
    ET.SubElement(channel, "language").text = FEED_LANGUAGE
    ET.SubElement(channel, "lastBuildDate").text = formatdate(localtime=True)

    # iTunes channel tags
    ET.SubElement(channel, _itunes("author")).text = FEED_AUTHOR
    ET.SubElement(channel, _itunes("type")).text = "episodic"
    ET.SubElement(channel, _itunes("explicit")).text = "false"
    ET.SubElement(channel, _itunes("summary")).text = FEED_DESCRIPTION

    owner = ET.SubElement(channel, _itunes("owner"))
    ET.SubElement(owner, _itunes("name")).text = FEED_AUTHOR
    ET.SubElement(owner, _itunes("email")).text = FEED_EMAIL

    cat = ET.SubElement(channel, _itunes("category"))
    cat.set("text", FEED_CATEGORY)
    sub = ET.SubElement(cat, _itunes("category"))
    sub.set("text", FEED_SUBCATEGORY)

    img = ET.SubElement(channel, _itunes("image"))
    img.set("href", f"{base_url}/cover.png")

    rss_image = ET.SubElement(channel, "image")
    ET.SubElement(rss_image, "url").text = f"{base_url}/cover.png"
    ET.SubElement(rss_image, "title").text = FEED_TITLE
    ET.SubElement(rss_image, "link").text = base_url

    # ── Add episodes from MP3 files ──────────────────────────────────
    for mp3_file in mp3_files[:30]:  # Keep last 30
        filename = mp3_file.name
        episode_url = f"{base_url}/{filename}"
        file_size = mp3_file.stat().st_size

        # Extract date from filename: dispatch-YYYY-MM-DD.mp3
        date_str = filename.replace("dispatch-", "").replace(".mp3", "")
        try:
            episode_date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue

        # Get duration from MP3 metadata
        try:
            audio = MP3(str(mp3_file))
            total_seconds = int(audio.info.length)
            minutes = total_seconds // 60
            seconds = total_seconds % 60
            duration_str = f"{minutes}:{seconds:02d}"
        except Exception:
            duration_str = "5:00"

        # Retrieve old description/pubDate if available
        old_data = old_descriptions.get(episode_url, {})
        description = old_data.get("description", f"Dispatch briefing for {date_str}")
        pub_date = old_data.get("pubDate")
        if not pub_date:
            pub_date = episode_date.strftime("%a, %d %b %Y 12:00:00 +0000")

        day_name = episode_date.strftime("%A, %B %d, %Y")

        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = f"Dispatch — {day_name}"
        ET.SubElement(item, "description").text = description

        enc = ET.SubElement(item, "enclosure")
        enc.set("url", episode_url)
        enc.set("length", str(file_size))
        enc.set("type", "audio/mpeg")

        guid = ET.SubElement(item, "guid")
        guid.set("isPermaLink", "true")
        guid.text = episode_url

        ET.SubElement(item, "pubDate").text = pub_date

        ET.SubElement(item, _itunes("summary")).text = description
        ET.SubElement(item, _itunes("episodeType")).text = "full"
        ET.SubElement(item, _itunes("duration")).text = duration_str

    # ── Write ────────────────────────────────────────────────────────
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(str(feed_path), xml_declaration=True, encoding="utf-8")

    episode_count = len(channel.findall("item"))
    print(f"  Feed rebuilt: {feed_path}")
    print(f"  Episodes: {episode_count}")
    print(f"  URL: {base_url}/feed.xml")

    # Verify output
    with open(feed_path, "r") as f:
        content = f.read(500)
    if "itunes:" in content and "ns0:" not in content:
        print("  ✓ Namespace check: clean itunes: prefixes")
    else:
        print("  ✗ WARNING: namespace issue detected!")


if __name__ == "__main__":
    rebuild_feed()
