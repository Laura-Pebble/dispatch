"""Read manually-added items from the Teacher Inbox Notion DB.

Laura uses this DB during the week to capture interesting Slack threads, links
people send her, or anything else the automated discovery would miss. Each
inbox row becomes a candidate source for curation, then gets marked Used or
Skip so it isn't picked up again.

Expected DB schema (set up by notion_dbs.ensure_inbox_schema):
  - Note    (title) — short description of what this is
  - URL     (url)
  - Source  (rich text) — where it came from, e.g. "Pavilion Slack #ai-marketing"
  - Status  (select)    — New / Used / Skip
  - Added   (date)
"""

from datetime import datetime, timezone

try:
    import trafilatura  # type: ignore
except ImportError:  # pragma: no cover
    trafilatura = None

import requests


def _title(props, key):
    parts = props.get(key, {}).get("title", [])
    return parts[0]["text"]["content"] if parts else ""


def _rich(props, key):
    parts = props.get(key, {}).get("rich_text", [])
    return parts[0]["text"]["content"] if parts else ""


def _url(props, key):
    return props.get(key, {}).get("url", "") or ""


def _date(props, key):
    d = props.get(key, {}).get("date") or {}
    return d.get("start", "") or ""


def _fetch_text(url: str) -> str:
    if not url or trafilatura is None:
        return ""
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "PebbleTeacher/1.0"})
        if r.status_code != 200:
            return ""
        return trafilatura.extract(r.text) or ""
    except Exception:
        return ""


def discover_inbox(notion, db_id: str, max_items: int = 5) -> list:
    """Pull New inbox items, enrich each with fetched text if URL is present.

    Returns list of source dicts matching the shape produced by discover_web.
    Does NOT mark items Used here — publish.py does that only for items that
    actually made it into the episode (so unused ones cycle to the next run).
    """
    if not db_id:
        return []

    try:
        resp = notion.databases.query(
            database_id=db_id,
            filter={"property": "Status", "select": {"equals": "New"}},
            sorts=[{"property": "Added", "direction": "ascending"}],
            page_size=max_items,
        )
    except Exception as e:
        print(f"  Warning: Could not query Inbox DB: {e}")
        return []

    rows = resp.get("results", [])
    if not rows:
        print(f"  [Inbox] no new items")
        return []

    items = []
    for page in rows:
        props = page.get("properties", {})
        note = _title(props, "Note")
        url = _url(props, "URL")
        source = _rich(props, "Source") or "Manual Inbox"
        added = _date(props, "Added") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if not note and not url:
            continue

        # Source-type heuristic: explicit "Slack" mention wins, otherwise generic Inbox.
        src_type = "Slack" if "slack" in source.lower() else "Inbox"
        full_text = _fetch_text(url) if url else ""

        items.append({
            "title": note or "(untitled inbox item)",
            "url": url,
            "author": source,
            "source": source,
            "source_type": src_type,
            "source_tier": "Community",
            "date_published": added[:10],
            "summary": (note or "")[:1500],
            "full_text": full_text[:20000] if full_text else (note or "")[:2000],
            "_inbox_page_id": page["id"],  # Tracked so publish.py can mark it Used
        })

    print(f"  [Inbox] {len(items)} item(s)")
    return items


def mark_inbox_used(notion, page_ids: list):
    """After publish, mark used inbox items so they don't recycle."""
    for pid in page_ids:
        if not pid:
            continue
        try:
            notion.pages.update(
                page_id=pid,
                properties={"Status": {"select": {"name": "Used"}}},
            )
        except Exception as e:
            print(f"  Warning: Could not mark inbox item Used: {e}")
