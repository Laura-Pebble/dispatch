"""Stage 1: Collect news articles from RSS feeds."""

from datetime import datetime, timedelta, timezone
import feedparser


def collect_news(topics: list, hours_back: int = 24) -> list:
    """Pull recent articles from RSS feeds, grouped by topic.

    Args:
        topics: List of topic dicts from config, each with name, feeds, max_articles.
        hours_back: How far back to look for articles (default 24h).

    Returns:
        List of dicts: [{"topic": str, "articles": [{"title", "description", "url", "source", "published"}]}]
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    seen_urls = set()
    results = []

    for topic in topics:
        topic_name = topic["name"]
        max_articles = topic.get("max_articles", 5)
        articles = []

        for feed_entry in topic.get("feeds", []):
            if isinstance(feed_entry, str):
                feed_url = feed_entry
                tier = "Trade Press"
            else:
                feed_url = feed_entry.get("url", "")
                tier = feed_entry.get("tier", "Trade Press")
            if not feed_url:
                continue

            try:
                feed = feedparser.parse(feed_url)
                source_name = feed.feed.get("title", feed_url)

                for entry in feed.entries:
                    url = entry.get("link", "")
                    if not url or url in seen_urls:
                        continue

                    # Parse publish date
                    published_parsed = entry.get("published_parsed") or entry.get("updated_parsed")
                    if published_parsed:
                        published_dt = datetime(*published_parsed[:6], tzinfo=timezone.utc)
                        if published_dt < cutoff:
                            continue
                    # If no date, include it (better to over-include than miss)

                    seen_urls.add(url)
                    articles.append({
                        "title": entry.get("title", "Untitled"),
                        "description": _clean_description(entry.get("summary", entry.get("description", ""))),
                        "url": url,
                        "source": source_name,
                        "published": entry.get("published", ""),
                        "tier": tier,
                    })

            except Exception as e:
                print(f"  Warning: Failed to fetch {feed_url}: {e}")
                continue

        # Sort by recency (newest first), limit to max
        articles.sort(key=lambda a: a["published"], reverse=True)
        articles = articles[:max_articles]

        results.append({
            "topic": topic_name,
            "articles": articles,
        })

        print(f"  [{topic_name}] Collected {len(articles)} articles")

    return results


def _clean_description(text: str) -> str:
    """Strip HTML tags from description text."""
    import re
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&nbsp;", " ").replace("&amp;", "&")
    clean = clean.replace("&lt;", "<").replace("&gt;", ">")
    return clean.strip()[:500]  # Cap length to avoid bloat
