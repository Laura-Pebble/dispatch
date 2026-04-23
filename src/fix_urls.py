"""One-off: resolve Vertex AI grounding redirects already stored in the DB.

Earlier search runs logged Gemini's grounding redirect URLs
(`https://vertexaisearch.cloud.google.com/grounding-api-redirect/<token>`)
instead of the actual article URLs. This script scans the Industry Intel
DB for those rows, follows each redirect to the real URL, and updates
the `URL` field in place.

Usage:
    python3 src/fix_urls.py --dry-run    # count + sample, no changes
    python3 src/fix_urls.py --execute    # actually update URLs

Reversible — every URL change shows up in the Notion page edit history.
"""

import os
import sys
import time
import argparse

import requests
from notion_client import Client

DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"
RATE_LIMIT_SLEEP = 0.35  # match purge_articles.py — ~3 req/sec
WRAPPER = "vertexaisearch.cloud.google.com"


def fetch_pages_with_wrapper_urls(notion: Client) -> list:
    """Pull every page whose URL contains the Vertex grounding wrapper."""
    pages = []
    has_more = True
    cursor = None
    while has_more:
        kwargs = {
            "database_id": DATABASE_ID,
            "page_size": 100,
            "filter": {"property": "URL", "url": {"contains": WRAPPER}},
        }
        if cursor:
            kwargs["start_cursor"] = cursor
        r = notion.databases.query(**kwargs)
        pages.extend(r.get("results", []))
        has_more = r.get("has_more", False)
        cursor = r.get("next_cursor")
    return pages


def resolve_url(url: str) -> str:
    """Follow the redirect; return final URL or original on failure."""
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        final = r.url or url
        return final if WRAPPER not in final else url
    except Exception:
        return url


def page_title(page: dict) -> str:
    parts = page.get("properties", {}).get("Title", {}).get("title", [])
    return parts[0]["text"]["content"] if parts else "(no title)"


def main():
    parser = argparse.ArgumentParser(description="Resolve Vertex grounding redirect URLs in Notion.")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="Count + sample, no changes.")
    g.add_argument("--execute", action="store_true", help="Resolve and update URLs.")
    args = parser.parse_args()

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        print("ERROR: NOTION_TOKEN not set")
        sys.exit(1)

    notion = Client(auth=token)

    print(f"Fetching pages with '{WRAPPER}' in URL...")
    pages = fetch_pages_with_wrapper_urls(notion)
    print(f"  Found {len(pages)} page(s) with wrapper URLs\n")

    if args.dry_run:
        if not pages:
            print("Nothing to fix.")
            return
        print("Sample (first 5):")
        for page in pages[:5]:
            url = page.get("properties", {}).get("URL", {}).get("url", "")
            print(f"  - {page_title(page)[:60]}")
            print(f"    {url[:90]}...")
        print(f"\nDry run — no changes. Rerun with --execute to resolve and update.")
        return

    if not pages:
        print("Nothing to fix.")
        return

    fixed = 0
    skipped = 0
    failed = 0
    for i, page in enumerate(pages, 1):
        title = page_title(page)
        old_url = page.get("properties", {}).get("URL", {}).get("url", "")
        new_url = resolve_url(old_url)
        if new_url == old_url:
            skipped += 1
            print(f"  [{i}/{len(pages)}] SKIP (could not resolve): {title[:55]}")
        else:
            try:
                notion.pages.update(
                    page_id=page["id"],
                    properties={"URL": {"url": new_url}},
                )
                fixed += 1
                print(f"  [{i}/{len(pages)}] FIXED: {title[:55]}")
            except Exception as e:
                failed += 1
                print(f"  [{i}/{len(pages)}] UPDATE FAILED: {title[:40]} — {e}")
        time.sleep(RATE_LIMIT_SLEEP)

    print(f"\nDone. Fixed: {fixed}. Skipped (unresolvable): {skipped}. Update errors: {failed}.")


if __name__ == "__main__":
    main()
