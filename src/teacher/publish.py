"""Render, publish, and log a Teacher episode.

  - Renders the script to MP3 via src/speak.py
  - Adds the episode to teacher.xml in output/podcast/ via src/podcast_feed.generate_feed
  - Writes an Episode page to the Teacher Episodes Notion DB with sources linked
  - Uploads the MP3 and sends an Ntfy notification via src/deliver.py
  - Marks the curriculum lesson Shipped and used inbox items Used
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse Dispatch modules
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from speak import text_to_speech  # noqa: E402
from deliver import upload_file, send_notification  # noqa: E402
from podcast_feed import generate_feed  # noqa: E402


# Default values used when config_teacher.yaml's `feed:` section is missing keys.
TEACHER_FEED_DEFAULTS = {
    "title": "Pebble Teacher",
    "description": (
        "A 3x/week teaching podcast for AI context engineers in marketing. "
        "Deep, technical, source-grounded lessons from Pebble Marketing."
    ),
    "author": "Laura McAliley",
    "email": "laura@pebble-marketing.com",
    "category": "Business",
    "subcategory": "Marketing",
    "feed_filename": "teacher.xml",
    "episode_prefix": "teacher",
    "episode_title_prefix": "Pebble Teacher — ",
    "cover_image": "teacher-cover.png",  # Falls back to cover.png in workflow if missing
}


def resolve_feed_config(yaml_feed: dict = None) -> dict:
    """Merge yaml feed section with teacher defaults."""
    cfg = dict(TEACHER_FEED_DEFAULTS)
    if yaml_feed:
        cfg.update({k: v for k, v in yaml_feed.items() if v is not None})
    return cfg


def render_audio(script: str, voice: str, output_path: str) -> Optional[str]:
    """Run TTS — returns the path on success, None on failure."""
    try:
        text_to_speech(script, voice=voice, output_path=output_path)
        return output_path
    except Exception as e:
        print(f"  TTS failed: {e}")
        return None


def build_feed(mp3_path: str, script: str, feed_config: dict = None) -> Optional[str]:
    """Add today's episode to the teacher feed."""
    fc = feed_config or TEACHER_FEED_DEFAULTS
    try:
        return generate_feed(mp3_path, script_text=script, feed_config=fc)
    except Exception as e:
        print(f"  Podcast feed error: {e}")
        return None


def deliver_notification(mp3_path: str, ntfy_topic: str, script: str):
    """Upload MP3 to a temp host + push notification."""
    audio_url = upload_file(mp3_path) if os.path.exists(mp3_path) else None
    if audio_url:
        send_notification(ntfy_topic, audio_url=audio_url, script_text=script)
    else:
        send_notification(ntfy_topic, audio_url=None, script_text=script)
    return audio_url


def _next_episode_number(notion, db_id: str) -> int:
    """Find the highest Episode # already in the DB and return n+1."""
    if not db_id:
        return 1
    try:
        resp = notion.databases.query(
            database_id=db_id,
            sorts=[{"property": "Episode #", "direction": "descending"}],
            page_size=1,
        )
        results = resp.get("results", [])
        if not results:
            return 1
        n = results[0].get("properties", {}).get("Episode #", {}).get("number")
        return int(n) + 1 if n else 1
    except Exception as e:
        print(f"  Warning: Could not find next episode # ({e}) — defaulting to 1")
        return 1


def _estimate_duration(script: str) -> tuple:
    """Return (mm:ss string, total_seconds) at ~150 wpm."""
    words = len(script.split())
    total_seconds = max(60, int(words / 150 * 60))
    return f"{total_seconds // 60}:{total_seconds % 60:02d}", total_seconds


def _follow_up_text(prompts: list) -> str:
    if not prompts:
        return ""
    return "\n".join(f"{i}. {str(p)[:400]}" for i, p in enumerate(prompts, start=1))


def _chunk_rich_text(text: str, chunk_size: int = 1900) -> list:
    """Split long text into Notion rich_text chunks (each ≤ 2000 chars)."""
    text = text or ""
    if len(text) <= chunk_size:
        return [{"text": {"content": text}}]
    chunks = []
    for i in range(0, len(text), chunk_size):
        chunks.append({"text": {"content": text[i:i + chunk_size]}})
    return chunks[:25]  # Notion caps rich_text array length around 100, but stay well under


def write_episode_page(
    notion,
    episodes_db_id: str,
    *,
    episode_num: int,
    lesson: dict,
    curated: list,
    script: str,
    follow_up_prompts: list,
    audio_url: Optional[str],
    duration: str,
) -> Optional[str]:
    """Create one row in Teacher Episodes; return its page_id or None."""
    if not episodes_db_id:
        return None

    air_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    topic = (lesson or {}).get("topic") or "Open-topic episode"
    title = f"Episode {episode_num} — {topic}"
    word_count = len(script.split())

    props = {
        "Title": {"title": [{"text": {"content": title[:200]}}]},
        "Episode #": {"number": episode_num},
        "Air Date": {"date": {"start": air_date}},
        "Status": {"select": {"name": "Shipped"}},
        "Script": {"rich_text": _chunk_rich_text(script)},
        "Word Count": {"number": word_count},
        "Duration": {"rich_text": [{"text": {"content": duration}}]},
    }
    if audio_url:
        props["Audio URL"] = {"url": audio_url}
    if follow_up_prompts:
        props["Follow-up Prompts"] = {"rich_text": [{"text": {"content": _follow_up_text(follow_up_prompts)[:1990]}}]}

    # Sources relation — only items that successfully wrote to Notion
    source_ids = [c["notion_page_id"] for c in curated if c.get("notion_page_id")]
    if source_ids:
        props["Sources"] = {"relation": [{"id": pid} for pid in source_ids]}
    if lesson and lesson.get("page_id"):
        props["Curriculum Lesson"] = {"relation": [{"id": lesson["page_id"]}]}

    try:
        page = notion.pages.create(parent={"database_id": episodes_db_id}, properties=props)
        page_id = page.get("id")
        print(f"  [Episodes] Logged episode {episode_num}")
        return page_id
    except Exception as e:
        print(f"  Warning: Could not write Episodes row: {e}")
        return None
