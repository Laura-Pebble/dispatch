"""Notion database access for the Teacher pipeline.

Three new databases are required; create them once in Laura's workspace and
paste the IDs into config_teacher.yaml. _ensure_schema() adds any missing
fields on each run (idempotent — matches the pattern in src/log_notion.py).

DBs:
  - Teacher Curriculum  — lesson plan + tracker
  - Teacher Sources     — one page per article / X-thread / inbox item extracted
  - Teacher Episodes    — one page per shipped episode
  - Teacher Inbox       — manual seed (Slack threads, clipboard URLs)
"""

import os
import time
from typing import Optional

from notion_client import Client


SOURCE_TYPES = ["Blog", "Podcast", "X", "Newsletter", "Slack", "Doc", "Inbox"]
SOURCE_TIERS = ["Primary", "Practitioner", "Trade Press", "Aggregator", "Community"]
EPISODE_STATUS = ["Planned", "In Production", "Shipped"]
CURRICULUM_STATUS = ["Planned", "In Production", "Shipped"]
DEPTH_LEVELS = ["Intro", "Working", "Deep"]
INBOX_STATUS = ["New", "Used", "Skip"]


def get_client() -> Optional[Client]:
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("  Warning: NOTION_TOKEN not set — Notion stages will be skipped")
        return None
    return Client(auth=token)


def _wait_for_propagation(notion: Client, db_id: str, expected: set, timeout_s: int = 30):
    """Notion schema updates are eventually consistent — poll until visible."""
    for attempt in range(timeout_s // 2):
        time.sleep(2)
        try:
            db = notion.databases.retrieve(database_id=db_id)
            if expected.issubset(set(db.get("properties", {}).keys())):
                return True
        except Exception:
            continue
    return False


def ensure_curriculum_schema(notion: Client, db_id: str):
    """Add missing fields to Teacher Curriculum DB. Title field assumed = 'Topic'."""
    if not db_id:
        return
    try:
        db = notion.databases.retrieve(database_id=db_id)
    except Exception as e:
        print(f"  Warning: Could not retrieve Curriculum DB: {e}")
        return
    existing = set(db.get("properties", {}).keys())
    additions = {}
    if "Lesson #" not in existing:
        additions["Lesson #"] = {"number": {}}
    if "Planned Date" not in existing:
        additions["Planned Date"] = {"date": {}}
    if "Status" not in existing:
        additions["Status"] = {"select": {"options": [{"name": n} for n in CURRICULUM_STATUS]}}
    if "Depth Covered" not in existing:
        additions["Depth Covered"] = {"select": {"options": [{"name": n} for n in DEPTH_LEVELS]}}
    if "Gaps" not in existing:
        additions["Gaps"] = {"rich_text": {}}
    if "Next Lesson Hypothesis" not in existing:
        additions["Next Lesson Hypothesis"] = {"rich_text": {}}
    if not additions:
        return
    try:
        notion.databases.update(database_id=db_id, properties=additions)
        for n in additions:
            print(f"  [Curriculum] Added field: {n}")
        _wait_for_propagation(notion, db_id, set(additions.keys()))
    except Exception as e:
        print(f"  Warning: Could not add Curriculum fields: {e}")


def ensure_sources_schema(notion: Client, db_id: str):
    """Add missing fields to Teacher Sources DB. Title field assumed = 'Title'."""
    if not db_id:
        return
    try:
        db = notion.databases.retrieve(database_id=db_id)
    except Exception as e:
        print(f"  Warning: Could not retrieve Sources DB: {e}")
        return
    existing = set(db.get("properties", {}).keys())
    additions = {}
    if "URL" not in existing:
        additions["URL"] = {"url": {}}
    if "Author" not in existing:
        additions["Author"] = {"rich_text": {}}
    if "Source Type" not in existing:
        additions["Source Type"] = {"select": {"options": [{"name": n} for n in SOURCE_TYPES]}}
    if "Source Tier" not in existing:
        additions["Source Tier"] = {"select": {"options": [{"name": n} for n in SOURCE_TIERS]}}
    if "Date Published" not in existing:
        additions["Date Published"] = {"date": {}}
    if "Date Captured" not in existing:
        additions["Date Captured"] = {"date": {}}
    if "Key Claims" not in existing:
        additions["Key Claims"] = {"rich_text": {}}
    if "Quotes" not in existing:
        additions["Quotes"] = {"rich_text": {}}
    if "Brand-Building Implication" not in existing:
        additions["Brand-Building Implication"] = {"rich_text": {}}
    if not additions:
        return
    try:
        notion.databases.update(database_id=db_id, properties=additions)
        for n in additions:
            print(f"  [Sources] Added field: {n}")
        _wait_for_propagation(notion, db_id, set(additions.keys()))
    except Exception as e:
        print(f"  Warning: Could not add Sources fields: {e}")


def ensure_episodes_schema(notion: Client, db_id: str, sources_db_id: str = "", curriculum_db_id: str = ""):
    """Add missing fields to Teacher Episodes DB. Title field assumed = 'Title'.

    Relations to Sources / Curriculum are added only if their DB IDs are provided.
    """
    if not db_id:
        return
    try:
        db = notion.databases.retrieve(database_id=db_id)
    except Exception as e:
        print(f"  Warning: Could not retrieve Episodes DB: {e}")
        return
    existing = set(db.get("properties", {}).keys())
    additions = {}
    if "Episode #" not in existing:
        additions["Episode #"] = {"number": {}}
    if "Air Date" not in existing:
        additions["Air Date"] = {"date": {}}
    if "Status" not in existing:
        additions["Status"] = {"select": {"options": [{"name": n} for n in EPISODE_STATUS]}}
    if "Audio URL" not in existing:
        additions["Audio URL"] = {"url": {}}
    if "Script" not in existing:
        additions["Script"] = {"rich_text": {}}
    if "Follow-up Prompts" not in existing:
        additions["Follow-up Prompts"] = {"rich_text": {}}
    if "Word Count" not in existing:
        additions["Word Count"] = {"number": {}}
    if "Duration" not in existing:
        additions["Duration"] = {"rich_text": {}}
    if sources_db_id and "Sources" not in existing:
        additions["Sources"] = {"relation": {"database_id": sources_db_id, "single_property": {}}}
    if curriculum_db_id and "Curriculum Lesson" not in existing:
        additions["Curriculum Lesson"] = {"relation": {"database_id": curriculum_db_id, "single_property": {}}}
    if not additions:
        return
    try:
        notion.databases.update(database_id=db_id, properties=additions)
        for n in additions:
            print(f"  [Episodes] Added field: {n}")
        _wait_for_propagation(notion, db_id, set(additions.keys()))
    except Exception as e:
        print(f"  Warning: Could not add Episodes fields: {e}")


def ensure_inbox_schema(notion: Client, db_id: str):
    """Add missing fields to Teacher Inbox DB. Title field assumed = 'Note'."""
    if not db_id:
        return
    try:
        db = notion.databases.retrieve(database_id=db_id)
    except Exception as e:
        print(f"  Warning: Could not retrieve Inbox DB: {e}")
        return
    existing = set(db.get("properties", {}).keys())
    additions = {}
    if "URL" not in existing:
        additions["URL"] = {"url": {}}
    if "Source" not in existing:
        additions["Source"] = {"rich_text": {}}
    if "Status" not in existing:
        additions["Status"] = {"select": {"options": [{"name": n} for n in INBOX_STATUS]}}
    if "Added" not in existing:
        additions["Added"] = {"date": {}}
    if not additions:
        return
    try:
        notion.databases.update(database_id=db_id, properties=additions)
        for n in additions:
            print(f"  [Inbox] Added field: {n}")
        _wait_for_propagation(notion, db_id, set(additions.keys()))
    except Exception as e:
        print(f"  Warning: Could not add Inbox fields: {e}")


def ensure_all_schemas(notion: Client, cfg_notion: dict):
    """Run all schema migrations in order. Call once per pipeline run."""
    ensure_curriculum_schema(notion, cfg_notion.get("curriculum_db_id", ""))
    ensure_sources_schema(notion, cfg_notion.get("sources_db_id", ""))
    ensure_inbox_schema(notion, cfg_notion.get("inbox_db_id", ""))
    # Episodes last — needs the other DB IDs for relations
    ensure_episodes_schema(
        notion,
        cfg_notion.get("episodes_db_id", ""),
        sources_db_id=cfg_notion.get("sources_db_id", ""),
        curriculum_db_id=cfg_notion.get("curriculum_db_id", ""),
    )
