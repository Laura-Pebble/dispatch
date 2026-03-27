"""Stage 1.5: Log collected articles to the Notion Industry Intel database."""

import os
import json
from datetime import datetime, timezone

from google import genai
from notion_client import Client


# Notion database ID (Industry Intel — Saved Articles)
DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"

CLASSIFY_PROMPT = """You are classifying a news article for a B2B marketing consultancy that serves tech companies as a fractional CMO.

Article:
Title: {title}
Source: {source}
Summary: {description}
Topic area: {topic}

Classify this article. Respond in JSON only, no markdown fences:
{{
  "category": one of ["Platform Update", "Competitor Move", "Thought Leadership", "Influencer Activity", "New Entrant", "Funding/Market"],
  "relevance": one of ["HIGH", "MEDIUM", "LOW"] — how directly this affects a B2B marketing consultancy using AI,
  "tags": array of zero or more from ["competitor", "content-opportunity", "sales-ammo", "methodology", "tool-update", "market-data"],
  "why_it_matters": one sentence on strategic significance for a B2B marketing consultancy
}}"""


def log_to_notion(news_data: list) -> int:
    """Log collected articles to the Notion Industry Intel database.

    Args:
        news_data: Output from collect.collect_news()

    Returns:
        Number of new articles logged.
    """
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print("  Warning: NOTION_TOKEN not set, skipping Notion logging")
        return 0

    notion = Client(auth=notion_token)

    # Get existing URLs to avoid duplicates
    existing_urls = _get_existing_urls(notion)

    # Set up Gemini for classification
    api_key = os.environ.get("GEMINI_API_KEY")
    gemini_available = False
    if api_key:
        gemini_client = genai.Client(api_key=api_key)
        gemini_available = True

    logged = 0
    for topic_data in news_data:
        topic = topic_data["topic"]
        for article in topic_data["articles"]:
            url = article.get("url", "")
            if not url or url in existing_urls:
                continue

            # Classify with Gemini
            classification = _classify_article(gemini_client, article, topic) if gemini_available else {}

            # Build Notion page properties
            properties = {
                "Title": {"title": [{"text": {"content": article["title"][:2000]}}]},
                "Source": {"rich_text": [{"text": {"content": article.get("source", "")[:2000]}}]},
                "URL": {"url": url},
                "Date Found": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
                "Status": {"select": {"name": "To Review"}},
                "Scraped": {"checkbox": False},
            }

            if classification.get("category"):
                properties["Category"] = {"select": {"name": classification["category"]}}
            if classification.get("relevance"):
                properties["Relevance"] = {"select": {"name": classification["relevance"]}}
            if classification.get("tags"):
                properties["Tags"] = {"multi_select": [{"name": t} for t in classification["tags"]]}
            if classification.get("why_it_matters"):
                properties["Why It Matters"] = {
                    "rich_text": [{"text": {"content": classification["why_it_matters"][:2000]}}]
                }

            try:
                notion.pages.create(parent={"database_id": DATABASE_ID}, properties=properties)
                logged += 1
                print(f"    Logged: {article['title'][:60]}...")
            except Exception as e:
                print(f"    Failed to log '{article['title'][:40]}': {e}")

    return logged


def _get_existing_urls(notion: Client) -> set:
    """Fetch all existing URLs from the database to avoid duplicates."""
    urls = set()
    try:
        has_more = True
        start_cursor = None
        while has_more:
            kwargs = {"database_id": DATABASE_ID, "page_size": 100}
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            response = notion.databases.query(**kwargs)
            for page in response.get("results", []):
                url_prop = page.get("properties", {}).get("URL", {}).get("url")
                if url_prop:
                    urls.add(url_prop)
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
    except Exception as e:
        print(f"  Warning: Could not fetch existing URLs: {e}")
    return urls


def _classify_article(client, article: dict, topic: str) -> dict:
    """Use Gemini to classify an article for the Notion database."""
    prompt = CLASSIFY_PROMPT.format(
        title=article.get("title", ""),
        source=article.get("source", ""),
        description=article.get("description", ""),
        topic=topic,
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        return json.loads(text.strip())
    except Exception as e:
        print(f"    Classification failed: {e}")
        return {}
