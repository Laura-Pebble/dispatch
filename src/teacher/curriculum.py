"""Load this episode's planned lesson from the Teacher Curriculum Notion DB.

The DB is seeded once with the 12 foundational lessons (see scripts/seed_curriculum.py).
On each run we pick the earliest Planned lesson whose Planned Date is today or earlier,
or — if none qualify — the next Planned lesson regardless of date.

Foundational arc is lessons 1-12. After that the next lesson is whatever Laura has
queued; the discover stages adapt their curation toward that topic.
"""

from datetime import datetime, timezone
from typing import Optional


def _title(props: dict, key: str) -> str:
    parts = props.get(key, {}).get("title", [])
    return parts[0]["text"]["content"] if parts else ""


def _rich(props: dict, key: str) -> str:
    parts = props.get(key, {}).get("rich_text", [])
    return parts[0]["text"]["content"] if parts else ""


def _number(props: dict, key: str):
    return props.get(key, {}).get("number")


def _date(props: dict, key: str) -> str:
    d = props.get(key, {}).get("date") or {}
    return d.get("start", "") or ""


def _select(props: dict, key: str) -> str:
    s = props.get(key, {}).get("select") or {}
    return s.get("name", "") or ""


def load_next_lesson(notion, db_id: str) -> Optional[dict]:
    """Return the next planned lesson, or None if the DB is empty.

    Returns dict: {page_id, lesson_num, topic, planned_date, status, gaps, hypothesis,
                   is_foundational}
    """
    if not db_id:
        print("  Warning: curriculum_db_id not configured — running without a lesson topic")
        return None
    try:
        response = notion.databases.query(
            database_id=db_id,
            filter={"property": "Status", "select": {"equals": "Planned"}},
            sorts=[
                {"property": "Planned Date", "direction": "ascending"},
                {"property": "Lesson #", "direction": "ascending"},
            ],
            page_size=10,
        )
    except Exception as e:
        print(f"  Warning: Could not query Curriculum DB: {e}")
        return None

    results = response.get("results", [])
    if not results:
        print("  No planned lessons in Teacher Curriculum DB — pipeline will generate an organic episode")
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    chosen = None
    for page in results:
        props = page.get("properties", {})
        planned = _date(props, "Planned Date")
        if planned and planned <= today:
            chosen = page
            break
    if chosen is None:
        chosen = results[0]  # Earliest upcoming if none are due yet

    props = chosen.get("properties", {})
    lesson_num = _number(props, "Lesson #")
    return {
        "page_id": chosen["id"],
        "lesson_num": lesson_num,
        "topic": _title(props, "Topic"),
        "planned_date": _date(props, "Planned Date"),
        "status": _select(props, "Status"),
        "gaps": _rich(props, "Gaps"),
        "hypothesis": _rich(props, "Next Lesson Hypothesis"),
        "is_foundational": bool(lesson_num and 1 <= lesson_num <= 12),
    }


def mark_in_production(notion, page_id: str):
    if not page_id:
        return
    try:
        notion.pages.update(
            page_id=page_id,
            properties={"Status": {"select": {"name": "In Production"}}},
        )
    except Exception as e:
        print(f"  Warning: Could not mark lesson In Production: {e}")


def mark_shipped(notion, page_id: str, episode_page_id: str = ""):
    if not page_id:
        return
    props = {"Status": {"select": {"name": "Shipped"}}}
    # Note: Episodes relation lives on the Episodes side, not Curriculum, so we
    # don't write it here — the Episodes row already links back.
    try:
        notion.pages.update(page_id=page_id, properties=props)
    except Exception as e:
        print(f"  Warning: Could not mark lesson Shipped: {e}")
