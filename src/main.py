"""Dispatch — Pipeline Orchestrator.

Runs all stages: Collect → Search → Dedup → Log to Notion → Summarize → Speak → Deliver → Cleanup
"""

import os
import sys
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collect import collect_news
from search_news import search_news
from dedup_themes import deduplicate_by_theme
from log_notion import log_to_notion
from knowledge import load_clusters
from summarize import generate_script
from speak import text_to_speech
from deliver import deliver
from podcast_feed import generate_feed
from weekly_synthesis import generate_weekly_synthesis


def load_config(config_path: str = None) -> dict:
    """Load configuration from YAML file."""
    if config_path is None:
        # Look for config.yaml relative to project root
        config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def run():
    """Execute the full pipeline."""
    print("=" * 50)
    print("Dispatch")
    print("=" * 50)

    # Load config
    print("\n[1/4] Loading configuration...")
    config = load_config()
    topics = config.get("topics", [])
    recap_length = config.get("recap_length", "medium")
    voice = config.get("voice", "en-US-AriaNeural")
    ntfy_topic = config.get("ntfy_topic", "morning-news")

    # Allow env var override for ntfy topic
    ntfy_topic = os.environ.get("NTFY_TOPIC", ntfy_topic)

    print(f"  Topics: {', '.join(t['name'] for t in topics)}")
    print(f"  Length: {recap_length}")
    print(f"  Voice: {voice}")

    # Stage 1: Collect
    print("\n[2/4] Collecting news articles...")
    news_data = collect_news(topics)

    total_articles = sum(len(t["articles"]) for t in news_data)
    if total_articles == 0:
        print("  No articles found. Sending notification and exiting.")
        from deliver import send_notification
        send_notification(ntfy_topic, script_text="No new articles found in your feeds today.")
        return

    print(f"  Total: {total_articles} articles across {len(news_data)} topics")

    # Stage 1b: Web Search
    search_queries = list(config.get("search_queries", []))

    # Append dynamic search queries from active Topic Clusters
    notion_token = os.environ.get("NOTION_TOKEN")
    if notion_token:
        try:
            from notion_client import Client as NotionClient
            notion_tmp = NotionClient(auth=notion_token)
            clusters = load_clusters(notion_tmp)
            for cluster in clusters:
                sq = cluster.get("search_queries", "")
                if sq:
                    for q in [s.strip() for s in sq.split(",") if s.strip()]:
                        if q not in search_queries:
                            search_queries.append(q)
            print(f"  Search queries: {len(search_queries)} total ({len(config.get('search_queries', []))} config + {len(search_queries) - len(config.get('search_queries', []))} from clusters)")
        except Exception as e:
            print(f"  Warning: Could not load cluster search queries: {e}")

    if search_queries:
        print("\n[2b] Searching the web for additional news...")
        existing_urls = set()
        for topic_data in news_data:
            for art in topic_data["articles"]:
                existing_urls.add(art["url"])

        search_results = search_news(
            search_queries,
            max_results=config.get("search_max_results", 5),
            existing_urls=existing_urls,
        )

        if search_results:
            news_data.append({
                "topic": "Web Search Finds",
                "articles": search_results,
            })
            total_articles += len(search_results)
            print(f"  Updated total: {total_articles} articles")

    # Stage 1c: Theme deduplication
    print("\n[2c] Deduplicating by theme...")
    news_data = deduplicate_by_theme(news_data)
    total_articles = sum(len(t["articles"]) for t in news_data)
    print(f"  After dedup: {total_articles} articles")

    # Stage 1.5: Log to Notion
    print("\n[2.5/5] Logging articles to Notion...")
    logged, classified_articles = log_to_notion(news_data)
    print(f"  Logged {logged} new articles to Notion")

    # Stage 2: Summarize
    print("\n[3/5] Generating strategic briefing with Gemini...")
    script = generate_script(news_data, recap_length, classified_articles=classified_articles)

    # Save script to file for reference
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    script_path = output_dir / "recap_script.txt"
    with open(script_path, "w") as f:
        f.write(script)
    print(f"  Script saved: {script_path}")

    # Stage 3: Speak
    print("\n[4/4] Converting to audio...")
    mp3_path = str(output_dir / "recap.mp3")
    tts_ok = False
    try:
        text_to_speech(script, voice=voice, output_path=mp3_path)
        tts_ok = True
    except Exception as e:
        print(f"  TTS failed: {e}")

    # Stage 4: Podcast Feed (even if TTS failed, rebuild_feed.py will handle it)
    if tts_ok:
        print("\n[5/6] Updating podcast feed...")
        try:
            generate_feed(mp3_path, script_text=script, config=config)
        except Exception as e:
            print(f"  Podcast feed error: {e}")
    else:
        print("\n[5/6] Skipping podcast feed — no audio generated")

    # Stage 5: Deliver notification
    print("\n[6/6] Delivering notification...")
    deliver(mp3_path, ntfy_topic, script_text=script)

    # Stage 7: Weekly synthesis (Fridays only)
    if datetime.now(timezone.utc).weekday() == 4:  # Friday
        print("\n[7/8] Generating weekly synthesis...")
        try:
            generate_weekly_synthesis()
        except Exception as e:
            print(f"  Weekly synthesis error: {e}")
    else:
        print("\n[7/8] Weekly synthesis — skipped (not Friday)")

    # Stage 8: Cleanup stale articles
    print("\n[8/8] Cleaning up stale articles...")
    cleanup_stale_articles()

    print("\n" + "=" * 50)
    print("Done! Check your podcast app or phone for the notification.")
    print("=" * 50)


def cleanup_stale_articles():
    """Archive stale articles from the Notion database.

    Rules:
    1. Status = "To Review" AND Date Found > 14 days ago → Archive
    2. Relevance = "Dispose" AND Date Found > 3 days ago → Archive
    3. Relevance = "FYI" AND Date Found > 30 days ago → Archive
    4. PROTECT articles with Topic Clusters relation set (they're reference material)
    """
    from log_notion import DATABASE_ID

    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        return

    from notion_client import Client
    notion = Client(auth=notion_token)

    today = datetime.now(timezone.utc)
    archived = 0

    cleanup_rules = [
        {
            "label": "Stale To Review (>14d)",
            "filter": {
                "and": [
                    {"property": "Status", "select": {"equals": "To Review"}},
                    {"property": "Date Found", "date": {"before": (today - timedelta(days=14)).strftime("%Y-%m-%d")}},
                ]
            },
        },
        {
            "label": "Dispose (>3d)",
            "filter": {
                "and": [
                    {"property": "Relevance", "select": {"equals": "Dispose"}},
                    {"property": "Date Found", "date": {"before": (today - timedelta(days=3)).strftime("%Y-%m-%d")}},
                ]
            },
        },
        {
            "label": "FYI (>30d)",
            "filter": {
                "and": [
                    {"property": "Relevance", "select": {"equals": "FYI"}},
                    {"property": "Date Found", "date": {"before": (today - timedelta(days=30)).strftime("%Y-%m-%d")}},
                ]
            },
        },
    ]

    for rule in cleanup_rules:
        try:
            has_more = True
            start_cursor = None
            while has_more:
                kwargs = {"database_id": DATABASE_ID, "page_size": 100, "filter": rule["filter"]}
                if start_cursor:
                    kwargs["start_cursor"] = start_cursor
                response = notion.databases.query(**kwargs)
                for page in response.get("results", []):
                    # PROTECT articles with Topic Clusters relation
                    clusters_rel = page.get("properties", {}).get("Topic Clusters", {}).get("relation", [])
                    if clusters_rel:
                        continue  # Skip — this is reference material

                    try:
                        notion.pages.update(
                            page_id=page["id"],
                            properties={"Status": {"select": {"name": "Archived"}}},
                        )
                        archived += 1
                    except Exception as e:
                        print(f"    Warning: Could not archive page: {e}")

                has_more = response.get("has_more", False)
                start_cursor = response.get("next_cursor")
        except Exception as e:
            print(f"    Warning: Cleanup rule '{rule['label']}' failed: {e}")

    if archived:
        print(f"  Archived {archived} stale article(s)")
    else:
        print("  No stale articles to archive")


if __name__ == "__main__":
    run()
