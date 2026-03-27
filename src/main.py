"""Dispatch — Pipeline Orchestrator.

Runs all stages: Collect → Search → Log to Notion → Summarize → Speak → Deliver
"""

import os
import sys
import yaml
from pathlib import Path

from collect import collect_news
from search_news import search_news
from log_notion import log_to_notion
from summarize import generate_script
from speak import text_to_speech
from deliver import deliver
from podcast_feed import generate_feed


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
    search_queries = config.get("search_queries", [])
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

    # Stage 1.5: Log to Notion
    print("\n[2.5/5] Logging articles to Notion...")
    logged = log_to_notion(news_data)
    print(f"  Logged {logged} new articles to Notion")

    # Stage 2: Summarize
    print("\n[3/5] Generating script with Gemini...")
    script = generate_script(news_data, recap_length)

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
    try:
        text_to_speech(script, voice=voice, output_path=mp3_path)
    except Exception as e:
        print(f"  TTS failed: {e}")
        print("  Sending text-only notification...")
        deliver(mp3_path, ntfy_topic, script_text=script)
        return

    # Stage 4: Podcast Feed
    print("\n[5/6] Updating podcast feed...")
    try:
        generate_feed(mp3_path, script_text=script, config=config)
    except Exception as e:
        print(f"  Podcast feed error: {e}")

    # Stage 5: Deliver notification
    print("\n[6/6] Delivering notification...")
    deliver(mp3_path, ntfy_topic, script_text=script)

    print("\n" + "=" * 50)
    print("Done! Check your podcast app or phone for the notification.")
    print("=" * 50)


if __name__ == "__main__":
    run()
