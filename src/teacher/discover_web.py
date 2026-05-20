"""Discover recent posts from curated expert blogs.

Pulls RSS via feedparser (same pattern as src/collect.py), then enriches each
item with full-text via trafilatura. Returns a list of source dicts ready for
the curate stage.

Lookback window is configurable (default 7 days) — wider than Dispatch's 24h
because the Teacher only runs 3x/week and needs to catch posts across that gap.
"""

import time
from datetime import datetime, timezone, timedelta
from html import unescape

import feedparser
import requests

try:
    import trafilatura  # type: ignore
except ImportError:  # pragma: no cover
    trafilatura = None


def _clean(text: str) -> str:
    """Strip HTML tags + entities from RSS summary."""
    if not text:
        return ""
    # Cheap tag strip — RSS summaries are usually small enough that this is fine.
    import re
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _parsed_published(entry) -> str:
    """Return entry's published time as ISO string, or '' if missing."""
    for key in ("published_parsed", "updated_parsed"):
        t = getattr(entry, key, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return ""


def _is_recent(published_iso: str, cutoff: datetime) -> bool:
    """Treat missing dates as recent — better to over-include than skip a fresh post."""
    if not published_iso:
        return True
    try:
        dt = datetime.fromisoformat(published_iso.replace("Z", "+00:00"))
        return dt >= cutoff
    except Exception:
        return True


def _fetch_full_text(url: str, timeout: int = 15) -> str:
    """Fetch and extract article body with trafilatura. Returns '' on failure."""
    if trafilatura is None:
        return ""
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "PebbleTeacher/1.0 (+https://pebble-marketing.com)"},
        )
        if r.status_code != 200:
            return ""
        extracted = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=False,
            no_fallback=False,
        )
        return extracted or ""
    except Exception:
        return ""


def discover_blog_sources(blog_sources: list, lookback_days: int = 7, max_items_per_blog: int = 3) -> list:
    """Walk the configured blog list and return recent items with full text.

    Returns list of dicts: {title, url, author, source, source_type='Blog', source_tier,
                            date_published, summary, full_text}
    """
    if not blog_sources:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    items = []

    for src in blog_sources:
        name = src.get("name", "Unknown")
        url = src.get("url", "")
        tier = src.get("tier", "Trade Press")
        if not url:
            continue

        print(f"  [Blog] {name}…")
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"    feedparser error: {e}")
            continue

        if getattr(feed, "bozo", False) and not feed.entries:
            print(f"    (feed unreadable, skipping)")
            continue

        count_from_source = 0
        for entry in feed.entries:
            if count_from_source >= max_items_per_blog:
                break
            published_iso = _parsed_published(entry)
            if not _is_recent(published_iso, cutoff):
                continue

            entry_url = getattr(entry, "link", "")
            title = getattr(entry, "title", "Untitled")
            author = getattr(entry, "author", "") or name
            summary = _clean(getattr(entry, "summary", "") or getattr(entry, "description", ""))

            full_text = _fetch_full_text(entry_url) if entry_url else ""
            # Brief politeness delay between requests so we don't hammer any one host.
            if entry_url:
                time.sleep(0.3)

            items.append({
                "title": title,
                "url": entry_url,
                "author": author,
                "source": name,
                "source_type": "Blog",
                "source_tier": tier,
                "date_published": published_iso[:10] if published_iso else "",
                "summary": summary[:1500],
                "full_text": full_text[:20000],  # Cap to keep prompt costs reasonable
            })
            count_from_source += 1

        print(f"    +{count_from_source} item(s)")

    print(f"  [Blog] {len(items)} item(s) total")
    return items
