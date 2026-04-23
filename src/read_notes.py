"""One-off: read Reviewed articles + the DB schema from the Industry Intel DB.

Prints:
- Current schema (all property names + options for select/multi-select fields —
  so we can see any renames or new values you've added manually)
- All Reviewed articles with their Notes and Why It Matters fields

Usage:
    python3 src/read_notes.py
"""

import os
import sys

from notion_client import Client

DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"


def extract_text(prop):
    """Extract text from a Notion title or rich_text property."""
    if not prop:
        return ""
    for key in ("title", "rich_text"):
        parts = prop.get(key, [])
        if parts:
            return "".join(
                p.get("plain_text", p.get("text", {}).get("content", ""))
                for p in parts
            )
    return ""


def main():
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("ERROR: NOTION_TOKEN not set")
        sys.exit(1)

    n = Client(auth=token)

    # === Schema dump ===
    print("=" * 70)
    print("CURRENT SCHEMA — all properties with their options")
    print("=" * 70)
    db = n.databases.retrieve(database_id=DATABASE_ID)
    for name, cfg in db.get("properties", {}).items():
        kind = cfg.get("type", "?")
        extra = ""
        if kind in ("select", "status"):
            opts = [o["name"] for o in cfg.get(kind, {}).get("options", [])]
            extra = f"  options: {opts}"
        elif kind == "multi_select":
            opts = [o["name"] for o in cfg.get("multi_select", {}).get("options", [])]
            extra = f"  options: {opts}"
        print(f"  {name:<20} ({kind}){extra}")

    # === Reviewed articles ===
    print()
    print("=" * 70)
    print("REVIEWED ARTICLES (newest first)")
    print("=" * 70)

    articles = []
    has_more = True
    cursor = None
    while has_more:
        kwargs = {
            "database_id": DATABASE_ID,
            "page_size": 100,
            "filter": {"property": "Status", "select": {"equals": "Reviewed"}},
            "sorts": [{"property": "Date Found", "direction": "descending"}],
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        r = n.databases.query(**kwargs)
        articles.extend(r.get("results", []))
        has_more = r.get("has_more", False)
        cursor = r.get("next_cursor")

    print(f"\nTotal Reviewed: {len(articles)}\n")
    for page in articles:
        props = page.get("properties", {})
        title = extract_text(props.get("Title"))
        source = extract_text(props.get("Source"))
        url = props.get("URL", {}).get("url", "")
        rel = (props.get("Relevance", {}).get("select") or {}).get("name", "")
        cat = (props.get("Category", {}).get("select") or {}).get("name", "")
        notes = extract_text(props.get("Notes"))
        why = extract_text(props.get("Why It Matters"))

        print(f"--- {title}")
        print(f"    Source: {source}")
        print(f"    Relevance: {rel}   Category: {cat}")
        print(f"    URL: {url}")
        if why:
            print(f"    Why It Matters: {why}")
        print(f"    NOTES: {notes if notes else '(empty)'}")
        print()


if __name__ == "__main__":
    main()
