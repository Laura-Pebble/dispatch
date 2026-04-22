"""One-off: clean-slate purge of the Industry Intel articles database.

Sets Status = "Archived" on every row that isn't already archived.

Usage:
    python src/purge_articles.py --dry-run    # count only, no changes
    python src/purge_articles.py --execute    # actually archive

Archive method: sets the `Status` select to `"Archived"`. Matches the existing
cleanup pattern in main.py — reversible by editing the field back.
"""

import os
import sys
import time
import argparse

from notion_client import Client

from log_notion import DATABASE_ID


RATE_LIMIT_SLEEP = 0.35  # ~3 req/sec — under Notion's 3/s cap


def fetch_all_pages(notion: Client, only_unarchived: bool = True) -> list:
    """Fetch every page in the Industry Intel DB. Returns list of page dicts."""
    pages = []
    has_more = True
    start_cursor = None
    while has_more:
        kwargs = {"database_id": DATABASE_ID, "page_size": 100}
        if start_cursor:
            kwargs["start_cursor"] = start_cursor
        if only_unarchived:
            kwargs["filter"] = {
                "property": "Status",
                "select": {"does_not_equal": "Archived"},
            }
        response = notion.databases.query(**kwargs)
        pages.extend(response.get("results", []))
        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")
    return pages


def summarize(pages: list) -> dict:
    """Break the page list down by Relevance and Status for the dry-run report."""
    by_relevance = {}
    by_status = {}
    no_relevance = 0
    for page in pages:
        props = page.get("properties", {})
        rel = (props.get("Relevance", {}).get("select") or {}).get("name")
        status = (props.get("Status", {}).get("select") or {}).get("name")
        if rel:
            by_relevance[rel] = by_relevance.get(rel, 0) + 1
        else:
            no_relevance += 1
        if status:
            by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(pages),
        "by_relevance": by_relevance,
        "by_status": by_status,
        "no_relevance": no_relevance,
    }


def archive_pages(notion: Client, pages: list) -> tuple:
    """Set Status = Archived on each page. Returns (archived_count, error_count)."""
    archived = 0
    errors = 0
    total = len(pages)
    for i, page in enumerate(pages, 1):
        try:
            notion.pages.update(
                page_id=page["id"],
                properties={"Status": {"select": {"name": "Archived"}}},
            )
            archived += 1
        except Exception as e:
            errors += 1
            print(f"  [{i}/{total}] Failed: {e}")
        if i % 25 == 0:
            print(f"  [{i}/{total}] archived {archived}, errors {errors}")
        time.sleep(RATE_LIMIT_SLEEP)
    return archived, errors


def main():
    parser = argparse.ArgumentParser(description="Clean-slate purge of Industry Intel DB.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="Count only, no changes.")
    group.add_argument("--execute", action="store_true", help="Actually archive.")
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("ERROR: NOTION_TOKEN env var not set.")
        sys.exit(1)

    notion = Client(auth=token)

    print("Fetching all non-archived pages from Industry Intel DB...")
    pages = fetch_all_pages(notion, only_unarchived=True)
    report = summarize(pages)

    print(f"\n  Total rows to purge: {report['total']}")
    print(f"  By Relevance:")
    for rel, count in sorted(report["by_relevance"].items(), key=lambda x: -x[1]):
        print(f"    {rel}: {count}")
    if report["no_relevance"]:
        print(f"    (no Relevance set): {report['no_relevance']}")
    print(f"  By Status:")
    for status, count in sorted(report["by_status"].items(), key=lambda x: -x[1]):
        print(f"    {status}: {count}")

    if args.dry_run:
        print("\nDry run — no changes made. Rerun with --execute to archive.")
        return

    if not pages:
        print("\nNothing to archive.")
        return

    print(f"\nArchiving {len(pages)} pages at ~3/sec (~{len(pages) * RATE_LIMIT_SLEEP:.0f}s)...")
    archived, errors = archive_pages(notion, pages)
    print(f"\nDone. Archived: {archived}. Errors: {errors}.")


if __name__ == "__main__":
    main()
