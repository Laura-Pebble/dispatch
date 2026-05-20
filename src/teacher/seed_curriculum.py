"""Seed the Teacher Curriculum Notion DB with the 12 foundational lessons.

Run once after creating the Teacher Curriculum DB and adding its ID to
config_teacher.yaml.

  python src/teacher/seed_curriculum.py

The script is idempotent — it checks each lesson by title and skips ones
that already exist.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from notion_dbs import get_client, ensure_curriculum_schema


# Lessons in podcast order. Dates are computed from a Monday start.
FOUNDATIONAL_LESSONS = [
    # Week 1 — Context as the new strategy
    ("Context engineering — what it is and why it's the next layer beyond prompt engineering", "Mon"),
    ("Prompts, context, and memory — the three layers of how LLMs see the world", "Wed"),
    ("System prompts and personas — the architecture of agent identity", "Fri"),
    # Week 2 — How models work for marketers
    ("Tokens, attention, and hallucination — mechanics in plain language with marketing implications", "Mon"),
    ("RAG for brand voice — retrieval, embeddings, when to use vs. fine-tune", "Wed"),
    ("Fine-tuning vs. context loading — what each costs, when to choose which", "Fri"),
    # Week 3 — Brand assets AI can read
    ("Machine-readable brand assets — schema.org, llms.txt, and structured data for AI consumption", "Mon"),
    ("The brand book as context — positioning that LLMs apply consistently", "Wed"),
    ("Voice files, style guides, and tone matrices — the artifacts agents need", "Fri"),
    # Week 4 — Agents, tools, workflows
    ("What's an agent? — agents vs. workflows vs. one-shot prompts", "Mon"),
    ("Tool use and MCP — how models reach out into the world; what MCP changes", "Wed"),
    ("Building your first marketing agent — putting the foundation together", "Fri"),
]


def next_monday(today: datetime = None) -> datetime:
    today = today or datetime.now(timezone.utc)
    days_ahead = (0 - today.weekday()) % 7
    # If today is Monday, start today; else jump to next Monday.
    return (today + timedelta(days=days_ahead)).replace(hour=11, minute=30, second=0, microsecond=0)


DAY_OFFSET = {"Mon": 0, "Wed": 2, "Fri": 4}


def existing_titles(notion, db_id: str) -> set:
    titles = set()
    try:
        has_more = True
        start_cursor = None
        while has_more:
            kwargs = {"database_id": db_id, "page_size": 100}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            resp = notion.databases.query(**kwargs)
            for page in resp.get("results", []):
                parts = page.get("properties", {}).get("Topic", {}).get("title", [])
                if parts:
                    titles.add(parts[0]["text"]["content"].strip().lower())
            has_more = resp.get("has_more", False)
            start_cursor = resp.get("next_cursor")
    except Exception as e:
        print(f"  Warning: Could not read existing titles: {e}")
    return titles


def run():
    cfg_path = Path(__file__).resolve().parent.parent.parent / "config_teacher.yaml"
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f) or {}
    db_id = (cfg.get("notion") or {}).get("curriculum_db_id", "")
    if not db_id:
        print("Set notion.curriculum_db_id in config_teacher.yaml first.")
        return 1

    notion = get_client()
    if notion is None:
        print("Set NOTION_TOKEN in the environment.")
        return 1

    ensure_curriculum_schema(notion, db_id)
    already = existing_titles(notion, db_id)

    start = next_monday()
    added = 0
    skipped = 0
    for i, (topic, day) in enumerate(FOUNDATIONAL_LESSONS):
        if topic.strip().lower() in already:
            skipped += 1
            continue
        week_index = i // 3
        offset = DAY_OFFSET[day]
        planned_date = (start + timedelta(days=week_index * 7 + offset)).strftime("%Y-%m-%d")
        props = {
            "Topic": {"title": [{"text": {"content": topic[:200]}}]},
            "Lesson #": {"number": i + 1},
            "Planned Date": {"date": {"start": planned_date}},
            "Status": {"select": {"name": "Planned"}},
        }
        try:
            notion.pages.create(parent={"database_id": db_id}, properties=props)
            print(f"  + Lesson {i + 1} ({planned_date}): {topic[:80]}")
            added += 1
        except Exception as e:
            print(f"  ! Lesson {i + 1} failed: {e}")

    print(f"\nDone. Added {added}, skipped {skipped} (already present).")
    return 0


if __name__ == "__main__":
    sys.exit(run())
