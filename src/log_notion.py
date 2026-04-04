"""Stage 1.5: Log collected articles to the Notion Industry Intel database."""

import os
import json
from datetime import datetime, timezone

from google import genai
from notion_client import Client

from knowledge import load_ripple_context, load_clusters, format_clusters_for_prompt


# Notion database ID (Industry Intel — Saved Articles)
DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"

CLASSIFY_PROMPT = """You are classifying a news article for Pebble Marketing's strategic intelligence system.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

<ACTIVE TOPIC CLUSTERS>
{formatted_clusters}
</ACTIVE TOPIC CLUSTERS>

Article:
Title: {title}
Source: {source}
Summary: {description}
Topic area: {topic}

Classify this article against Pebble's POSITIONING — not just its topic.

Decision framework:
1. Does this create an opportunity for Laura to be in a conversation, create content, or reach a buyer? → HIGH
2. Could this affect Pebble's positioning in 3-6 months? → MEDIUM
3. Would someone running an AI-powered B2B marketing system look uninformed for NOT knowing this? (major model releases, platform changes, AI methodology shifts, significant industry events) → FYI
4. Is this general news with no Pebble angle? → LOW
5. Is this noise, vendor PR, or a rehash? → Dispose

For FYI articles: set action_type, suggested_action, ripple_angle, and cluster_match to null.
For HIGH and MEDIUM: all fields required.

Respond in JSON only, no markdown fences:
{{
  "category": one of ["Platform Update", "Competitor Move", "Thought Leadership", "Influencer Activity", "New Entrant", "Funding/Market"],
  "relevance": one of ["HIGH", "MEDIUM", "FYI", "LOW", "Dispose"],
  "tags": array from ["competitor", "content-opportunity", "sales-ammo", "methodology", "tool-update", "market-data"],
  "why_it_matters": "one sentence — strategic significance or null for Dispose",
  "action_type": one of ["read", "comment", "write-about", "reach-out", "share", "track"] or null,
  "suggested_action": "one-line recommended action with angle" or null,
  "ripple_angle": "how this connects to Pebble positioning" or null,
  "cluster_match": "exact cluster name from the list above" or "none" or "potential new cluster: [description]",
  "new_market_terms": ["terms from this article not already in the cluster's Market Terms"] or []
}}"""


def log_to_notion(news_data: list) -> tuple:
    """Log collected articles to the Notion Industry Intel database.

    Args:
        news_data: Output from collect.collect_news()

    Returns:
        Tuple of (number of new articles logged, list of classification results).
        Classification results are dicts with article info + classification fields.
    """
    notion_token = os.environ.get("NOTION_TOKEN")
    if not notion_token:
        print("  Warning: NOTION_TOKEN not set, skipping Notion logging")
        return 0, []

    notion = Client(auth=notion_token)

    # Get existing URLs to avoid duplicates
    existing_urls = _get_existing_urls(notion)

    # Load positioning context and clusters ONCE
    ripple_context = load_ripple_context()
    clusters = load_clusters(notion)
    formatted_clusters = format_clusters_for_prompt(clusters)
    cluster_lookup = {c["name"].lower(): c for c in clusters}
    print(f"  Loaded {len(clusters)} active topic clusters")

    # Set up Gemini for classification
    api_key = os.environ.get("GEMINI_API_KEY")
    gemini_available = False
    if api_key:
        gemini_client = genai.Client(api_key=api_key)
        gemini_available = True

    logged = 0
    classified_articles = []

    for topic_data in news_data:
        topic = topic_data["topic"]
        for article in topic_data["articles"]:
            url = article.get("url", "")
            if not url or url in existing_urls:
                continue

            # Classify with Gemini
            classification = (
                _classify_article(gemini_client, article, topic, ripple_context, formatted_clusters)
                if gemini_available
                else {}
            )

            # Skip Dispose articles entirely
            if classification.get("relevance") == "Dispose":
                print(f"    Disposed: {article['title'][:60]}...")
                continue

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

            # New v2 fields
            if classification.get("action_type"):
                properties["Action Type"] = {"select": {"name": classification["action_type"]}}
            if classification.get("suggested_action"):
                properties["Suggested Action"] = {
                    "rich_text": [{"text": {"content": classification["suggested_action"][:2000]}}]
                }
            if classification.get("ripple_angle"):
                properties["Ripple Angle"] = {
                    "rich_text": [{"text": {"content": classification["ripple_angle"][:2000]}}]
                }

            # Resolve cluster relation
            cluster_match = classification.get("cluster_match", "none")
            matched_cluster = None
            if cluster_match and cluster_match.lower() not in ("none", "null", ""):
                if not cluster_match.lower().startswith("potential new cluster"):
                    matched_cluster = cluster_lookup.get(cluster_match.lower())
                    if matched_cluster:
                        properties["Topic Clusters"] = {
                            "relation": [{"id": matched_cluster["page_id"]}]
                        }

            try:
                notion.pages.create(parent={"database_id": DATABASE_ID}, properties=properties)
                logged += 1
                rel_tag = classification.get("relevance", "?")
                print(f"    Logged [{rel_tag}]: {article['title'][:60]}...")

                # Store for downstream use (podcast, etc.)
                classified_articles.append({
                    **article,
                    "topic": topic,
                    **classification,
                })

                # Post-log: update cluster with new market terms and last signal date
                if matched_cluster and classification.get("new_market_terms"):
                    _update_cluster_terms(notion, matched_cluster, classification["new_market_terms"])
                if matched_cluster:
                    _update_cluster_last_signal(notion, matched_cluster)

            except Exception as e:
                print(f"    Failed to log '{article['title'][:40]}': {e}")

    return logged, classified_articles


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


def _classify_article(client, article: dict, topic: str, ripple_context: str, formatted_clusters: str) -> dict:
    """Use Gemini to classify an article with positioning-aware prompt."""
    prompt = CLASSIFY_PROMPT.format(
        ripple_context=ripple_context,
        formatted_clusters=formatted_clusters,
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


def _update_cluster_terms(notion: Client, cluster: dict, new_terms: list):
    """Append new market terms to a cluster's Market Terms field."""
    if not new_terms:
        return
    try:
        existing = cluster.get("market_terms", "")
        # Avoid duplicates
        existing_lower = existing.lower()
        truly_new = [t for t in new_terms if t.lower() not in existing_lower]
        if not truly_new:
            return
        updated = existing + ", " + ", ".join(truly_new) if existing else ", ".join(truly_new)
        notion.pages.update(
            page_id=cluster["page_id"],
            properties={
                "Market Terms": {"rich_text": [{"text": {"content": updated[:2000]}}]},
            },
        )
        print(f"      Updated cluster '{cluster['name']}' with terms: {truly_new}")
    except Exception as e:
        print(f"      Warning: Could not update cluster terms: {e}")


def _update_cluster_last_signal(notion: Client, cluster: dict):
    """Update a cluster's Last Signal date to today."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        notion.pages.update(
            page_id=cluster["page_id"],
            properties={
                "Last Signal": {"date": {"start": today}},
            },
        )
    except Exception as e:
        print(f"      Warning: Could not update Last Signal: {e}")
