"""Pebble Teacher — orchestrator.

Run: `python src/teacher/main.py` (with NOTION_TOKEN + GEMINI_API_KEY in env).

Stages: discover (web + X + inbox) → curriculum → curate → extract+log →
lesson_script → render audio → publish (feed + Notion episode + Ntfy).
"""

import os
import sys
from pathlib import Path

import yaml

_TEACHER = Path(__file__).resolve().parent
if str(_TEACHER) not in sys.path:
    sys.path.insert(0, str(_TEACHER))

from notion_dbs import get_client, ensure_all_schemas
from curriculum import load_next_lesson, mark_in_production, mark_shipped
from discover_web import discover_blog_sources
from discover_x import discover_x_handles
from discover_inbox import discover_inbox, mark_inbox_used
from curate import curate
from extract import extract_and_log_sources
from lesson_script import generate_lesson_script
from publish import (
    render_audio,
    build_feed,
    deliver_notification,
    resolve_feed_config,
    _next_episode_number,
    _estimate_duration,
    write_episode_page,
)


def load_config(path: str = None) -> dict:
    if path is None:
        path = Path(__file__).resolve().parent.parent.parent / "config_teacher.yaml"
    with open(path, "r") as f:
        return yaml.safe_load(f) or {}


def run():
    print("=" * 60)
    print("Pebble Teacher")
    print("=" * 60)

    config = load_config()
    notion_cfg = config.get("notion") or {}
    voice = config.get("voice", "en-US-AriaNeural")
    ntfy_topic = os.environ.get("NTFY_TOPIC", config.get("ntfy_topic", "laura-teacher"))

    # ── Notion connect + schema migrations ───────────────────────────
    notion = get_client()
    if notion is None:
        print("Aborting: NOTION_TOKEN is required for the Teacher pipeline.")
        return
    print("\n[1/8] Ensuring Notion schemas…")
    ensure_all_schemas(notion, notion_cfg)

    # ── Pick this episode's lesson ───────────────────────────────────
    print("\n[2/8] Loading curriculum lesson…")
    lesson = load_next_lesson(notion, notion_cfg.get("curriculum_db_id", ""))
    if lesson:
        print(
            f"  Lesson {lesson.get('lesson_num') or '?'}: {lesson['topic']} "
            f"(foundational={lesson['is_foundational']})"
        )
        mark_in_production(notion, lesson["page_id"])
    else:
        print("  No lesson configured — pipeline will run on whatever the sources teach.")

    lesson_topic = (lesson or {}).get("topic", "")
    is_foundational = bool((lesson or {}).get("is_foundational"))

    # ── Discover sources ─────────────────────────────────────────────
    print("\n[3/8] Discovering sources…")
    blog_items = discover_blog_sources(
        config.get("blog_sources", []),
        lookback_days=config.get("lookback_days", 7),
        max_items_per_blog=config.get("max_items_per_blog", 3),
    )
    x_items = discover_x_handles(
        config.get("x_handles", []),
        max_items_per_handle=config.get("max_items_per_handle", 2),
        lesson_topic=lesson_topic,
    )
    inbox_items = discover_inbox(
        notion,
        notion_cfg.get("inbox_db_id", ""),
        max_items=config.get("max_inbox_items", 5),
    )
    all_items = blog_items + x_items + inbox_items
    print(f"  Discovered {len(all_items)} candidate sources")

    if not all_items:
        print("\nNo sources discovered — skipping episode. (Lesson stays Planned.)")
        if lesson:
            # Roll the lesson back from In Production so it picks up next time
            try:
                notion.pages.update(
                    page_id=lesson["page_id"],
                    properties={"Status": {"select": {"name": "Planned"}}},
                )
            except Exception:
                pass
        return

    # ── Curate ───────────────────────────────────────────────────────
    print("\n[4/8] Curating against this lesson…")
    target = config.get("target_sources_per_episode", 5)
    curated = curate(all_items, lesson, target_count=target)
    if not curated:
        print("  No sources passed curation — aborting episode.")
        return

    # ── Deep extract + write to Teacher Sources ─────────────────────
    print("\n[5/8] Extracting + logging sources…")
    curated = extract_and_log_sources(
        notion,
        sources_db_id=notion_cfg.get("sources_db_id", ""),
        intel_db_id=notion_cfg.get("intel_db_id", ""),
        curated=curated,
        lesson_topic=lesson_topic,
    )

    # ── Lesson script ────────────────────────────────────────────────
    print("\n[6/8] Writing lesson script…")
    if is_foundational:
        word_budget = tuple(config.get("word_budget_foundational", [3200, 4200]))
    else:
        word_budget = tuple(config.get("word_budget_organic", [2200, 3200]))
    script, follow_ups = generate_lesson_script(lesson, curated, word_budget)

    output_dir = Path(__file__).resolve().parent.parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    script_path = output_dir / "teacher_script.txt"
    script_path.write_text(script)
    print(f"  Script saved: {script_path}")

    # ── Render audio ─────────────────────────────────────────────────
    print("\n[7/8] Rendering audio…")
    mp3_path = str(output_dir / "teacher.mp3")
    audio_ok = render_audio(script, voice=voice, output_path=mp3_path)

    # ── Publish: feed, Notion episode page, Ntfy ────────────────────
    print("\n[8/8] Publishing…")
    audio_url = None
    if audio_ok:
        build_feed(mp3_path, script, feed_config=resolve_feed_config(config.get("feed")))
        audio_url = deliver_notification(mp3_path, ntfy_topic, script)
    else:
        deliver_notification("", ntfy_topic, script)

    duration_str, _ = _estimate_duration(script)
    episode_num = _next_episode_number(notion, notion_cfg.get("episodes_db_id", ""))
    write_episode_page(
        notion,
        notion_cfg.get("episodes_db_id", ""),
        episode_num=episode_num,
        lesson=lesson,
        curated=curated,
        script=script,
        follow_up_prompts=follow_ups,
        audio_url=audio_url,
        duration=duration_str,
    )

    # Mark the curriculum lesson Shipped + cycle inbox items used in this episode
    if lesson:
        mark_shipped(notion, lesson["page_id"])
    used_inbox_ids = [c.get("_inbox_page_id") for c in curated if c.get("_inbox_page_id")]
    if used_inbox_ids:
        mark_inbox_used(notion, used_inbox_ids)

    print("\n" + "=" * 60)
    print(f"Done. Episode {episode_num}: {len(script.split())} words, ~{duration_str}.")
    print("=" * 60)


if __name__ == "__main__":
    run()
