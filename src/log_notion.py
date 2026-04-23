"""Stage 1.5: Log collected articles to the Notion Industry Intel database."""

import os
import json
from datetime import datetime, timezone

from google import genai
from notion_client import Client

from knowledge import (
    load_ripple_context,
    load_clusters,
    format_clusters_for_prompt,
    load_watchlist,
    format_watchlist_for_prompt,
)


# Notion database ID (Industry Intel — Saved Articles)
DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"

# Valid values for tier-aware fields
TIER_OPTIONS = ["Primary", "Practitioner", "Trade Press", "Aggregator"]
SIGNAL_STRENGTH_OPTIONS = ["Single", "Multi-Source", "Confirmed"]
PODCAST_SEGMENT_OPTIONS = [
    "content_news",
    "thought_leadership",
    "landscape_shift",
    "release",
    "adjacent_topic",
    "fun_fact",
    "db_only",
]


CLASSIFY_PROMPT = """You are classifying a news article for Pebble Marketing's strategic intelligence system.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

<ACTIVE TOPIC CLUSTERS>
{formatted_clusters}
</ACTIVE TOPIC CLUSTERS>

<LAURA'S CURRENT WATCHLIST>
{formatted_watchlist}
</LAURA'S CURRENT WATCHLIST>

Article:
Title: {title}
Source: {source}
Summary: {description}
Topic area: {topic}

Cross-source signal:
  Reported by {source_count} outlet(s): {source_names}
  Tier breakdown: {source_tiers} (tier diversity: {tier_diversity})

Classify this article against Pebble's POSITIONING — not just its topic.

Decision framework:
1. Does this create an opportunity for Laura to be in a conversation, create content, or reach a buyer? → HIGH
2. Could this affect Pebble's positioning in 3-6 months? → MEDIUM
3. Would someone running an AI-powered B2B marketing system look uninformed for NOT knowing this? (major model releases, platform changes, AI methodology shifts, significant industry events) → FYI
4. Is this general news with no Pebble angle? → LOW
5. Is this noise, vendor PR, or a rehash? → Dispose

Signal weighting:
- Multiple independent outlets (tier diversity >= 2) reporting this = real trend, not one take.
- All Trade Press / Aggregator only = likely echo of a press release; weigh accordingly.
- A Primary source (Anthropic, OpenAI, Google AI) + any other tier = capability/market shift worth tracking.
- Article mentions anything on Laura's watchlist = relevant to her current focus.

For FYI articles: set action_type, suggested_action, ripple_angle, and cluster_match to null.
For HIGH and MEDIUM: all fields required.

PODCAST SEGMENT — assign every article to one of these buckets (this controls where it appears in the daily audio brief):
- "content_news": articles about AI-generated content quality, B2B buyer behavior, or content craft (commentary segment).
- "thought_leadership": flagship POV pieces, contrarian takes, arguments worth quoting (deeper segment).
- "landscape_shift": structural changes in AI economics, model pricing, infrastructure, or platform consolidation that affect a $1M-$15M B2B fCMO practice.
- "release": new tool/model/capability drops (quick-hit ~15s each).
- "adjacent_topic": security, energy, regulation, broader concerns Laura tracks but doesn't act on (~30s each).
- "fun_fact": surprising AI anecdotes, oddities, cocktail-party material (brief mention).
- "db_only": enterprise-scale case studies (Shopify, ServiceNow, Unilever-tier), pure market data, or reference material. Saves to DB but does NOT appear in the podcast.

CUSTOMER-SIZE FILTER (CRITICAL):
Pebble serves $1M-$15M ARR B2B tech companies. If an article's insight ONLY applies at enterprise scale ($100M+), set podcast_segment = "db_only". Don't waste airtime on enterprise case studies unless the principle clearly transplants to small-mid-market.

Examples:
- Shopify's AI integration at billions in revenue → db_only (too enterprise)
- Unilever Brand DNAi at global scale → db_only
- ServiceNow $14.7B ARR learnings → db_only
- A tactic Mollick describes that any team could try → content_news or release
- A new model from Anthropic that anyone can use → release

Respond in JSON only, no markdown fences:
{{
  "category": one of ["Platform Update", "Competitor Move", "Thought Leadership", "Influencer Activity", "New Entrant", "Funding/Market", "Market Data", "Methodology"],
  "relevance": one of ["HIGH", "MEDIUM", "FYI", "LOW", "Dispose"],
  "podcast_segment": one of ["content_news", "thought_leadership", "landscape_shift", "release", "adjacent_topic", "fun_fact", "db_only"],
  "tags": array from ["competitor", "content-opportunity", "sales-ammo", "methodology", "tool-update", "market-data", "thought-leadership"],
  "why_it_matters": "one sentence — strategic significance or null for Dispose",
  "action_type": one of ["read", "comment", "write-about", "reach-out", "share", "track"] or null,
  "suggested_action": "one-line recommended action with angle" or null,
  "ripple_angle": "how this connects to Pebble positioning" or null,
  "cluster_match": "exact cluster name from the list above" or "none" or "potential new cluster: [description]",
  "new_market_terms": ["terms from this article not already in the cluster's Market Terms"] or []
}}"""


RELEVANCE_ORDER = ["Dispose", "LOW", "FYI", "MEDIUM", "HIGH"]


def _derive_signal_strength(source_count: int, source_tiers: list, tier_diversity: int) -> str:
    """Bucket the cross-source signal. See plan Change 1 for rules."""
    if source_count <= 1:
        return "Single"
    has_primary = "Primary" in (source_tiers or [])
    if tier_diversity >= 3 or (has_primary and source_count >= 2):
        return "Confirmed"
    return "Multi-Source"


def _raise_relevance(current: str, floor: str) -> str:
    """Return the higher of two relevance values by RELEVANCE_ORDER."""
    try:
        cur_idx = RELEVANCE_ORDER.index(current)
    except ValueError:
        cur_idx = -1
    try:
        floor_idx = RELEVANCE_ORDER.index(floor)
    except ValueError:
        return current
    return floor if floor_idx > cur_idx else current


def _mentions_watchlist(article: dict, watchlist: dict) -> bool:
    """Case-insensitive substring match over title + description."""
    haystack = f"{article.get('title', '')} {article.get('description', '')}".lower()
    for bucket in ("people", "tools", "trends"):
        for item in watchlist.get(bucket, []):
            if item and item.lower() in haystack:
                return True
    return False


def _ensure_schema(notion: Client):
    """Add the 4 tier-tracking fields to the Industry Intel database if missing.

    Idempotent — safe to run every invocation. Waits for Notion's eventual
    consistency so immediate follow-up page writes see the new fields.
    """
    import time

    try:
        db = notion.databases.retrieve(database_id=DATABASE_ID)
    except Exception as e:
        print(f"  Warning: Could not retrieve Notion schema: {e}")
        return

    existing = set(db.get("properties", {}).keys())
    additions = {}

    if "Source Count" not in existing:
        additions["Source Count"] = {"number": {}}
    if "Source Tiers" not in existing:
        additions["Source Tiers"] = {
            "multi_select": {"options": [{"name": n} for n in TIER_OPTIONS]}
        }
    if "Source Outlets" not in existing:
        additions["Source Outlets"] = {"rich_text": {}}
    if "Signal Strength" not in existing:
        additions["Signal Strength"] = {
            "select": {"options": [{"name": n} for n in SIGNAL_STRENGTH_OPTIONS]}
        }
    if "Podcast Segment" not in existing:
        additions["Podcast Segment"] = {
            "select": {"options": [{"name": n} for n in PODCAST_SEGMENT_OPTIONS]}
        }

    if not additions:
        return

    try:
        notion.databases.update(database_id=DATABASE_ID, properties=additions)
        for name in additions:
            print(f"  Added Notion field: {name}")
    except Exception as e:
        print(f"  Warning: Could not add Notion fields {list(additions)}: {e}")
        return

    # Notion schema changes are eventually consistent — poll until the new
    # fields are visible so immediate writes don't fail with
    # "property does not exist".
    expected = set(additions.keys())
    for attempt in range(15):
        time.sleep(2)
        try:
            db = notion.databases.retrieve(database_id=DATABASE_ID)
            current = set(db.get("properties", {}).keys())
            if expected.issubset(current):
                print(f"  Schema propagated after {(attempt + 1) * 2}s")
                return
        except Exception:
            continue
    print("  Warning: schema not confirmed after 30s — this run may fail to write new fields")


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

    # One-time (idempotent) schema migration
    _ensure_schema(notion)

    # Get existing URLs to avoid duplicates
    existing_urls = _get_existing_urls(notion)

    # Load positioning context, clusters, and watchlist ONCE
    ripple_context = load_ripple_context()
    clusters = load_clusters(notion)
    formatted_clusters = format_clusters_for_prompt(clusters)
    cluster_lookup = {c["name"].lower(): c for c in clusters}
    watchlist = load_watchlist()
    formatted_watchlist = format_watchlist_for_prompt(watchlist)
    print(f"  Loaded {len(clusters)} active topic clusters")
    wl_total = sum(len(v) for v in watchlist.values())
    if wl_total:
        print(f"  Loaded watchlist: {wl_total} item(s)")

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

            # Cross-source signal data (attached by dedup_themes.py)
            source_count = article.get("source_count", 1)
            source_names = article.get("source_names", [article.get("source", "Unknown")])
            source_tiers = article.get("source_tiers", [article.get("tier", "Trade Press")])
            tier_diversity = article.get("tier_diversity", 1)

            # Classify with Gemini
            classification = (
                _classify_article(
                    gemini_client,
                    article,
                    topic,
                    ripple_context,
                    formatted_clusters,
                    formatted_watchlist,
                    source_count,
                    source_names,
                    source_tiers,
                    tier_diversity,
                )
                if gemini_available
                else {}
            )

            # Skip Dispose articles entirely
            if classification.get("relevance") == "Dispose":
                print(f"    Disposed: {article['title'][:60]}...")
                continue

            # Python-side promotion rules (layered on top of model classification)
            relevance = classification.get("relevance", "LOW")
            has_primary_or_practitioner = any(
                t in ("Primary", "Practitioner") for t in source_tiers
            )
            if tier_diversity >= 2 and has_primary_or_practitioner:
                relevance = _raise_relevance(relevance, "MEDIUM")
            if _mentions_watchlist(article, watchlist):
                relevance = _raise_relevance(relevance, "MEDIUM")
            classification["relevance"] = relevance

            # Derive signal strength
            signal_strength = _derive_signal_strength(source_count, source_tiers, tier_diversity)

            # Resolve podcast segment with safe default
            segment = classification.get("podcast_segment") or "db_only"
            if segment not in PODCAST_SEGMENT_OPTIONS:
                segment = "db_only"

            # Build Notion page properties
            properties = {
                "Title": {"title": [{"text": {"content": article["title"][:2000]}}]},
                "Source": {"rich_text": [{"text": {"content": article.get("source", "")[:2000]}}]},
                "URL": {"url": url},
                "Date Found": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
                "Status": {"select": {"name": "To Review"}},
                "Scraped": {"checkbox": False},
                "Source Count": {"number": source_count},
                "Source Tiers": {"multi_select": [{"name": t} for t in source_tiers if t in TIER_OPTIONS]},
                "Source Outlets": {
                    "rich_text": [{"text": {"content": ", ".join(source_names)[:2000]}}]
                },
                "Signal Strength": {"select": {"name": signal_strength}},
                "Podcast Segment": {"select": {"name": segment}},
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
                print(f"    Logged [{rel_tag}/{signal_strength}/{segment}]: {article['title'][:60]}...")

                # Store for downstream use (podcast, etc.)
                # Overwrite podcast_segment with the validated value from above so
                # downstream code never sees an unrecognized segment.
                classified_articles.append({
                    **article,
                    "topic": topic,
                    "signal_strength": signal_strength,
                    **classification,
                    "podcast_segment": segment,
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


def _classify_article(
    client,
    article: dict,
    topic: str,
    ripple_context: str,
    formatted_clusters: str,
    formatted_watchlist: str,
    source_count: int,
    source_names: list,
    source_tiers: list,
    tier_diversity: int,
) -> dict:
    """Use Gemini to classify an article with positioning-aware prompt."""
    prompt = CLASSIFY_PROMPT.format(
        ripple_context=ripple_context,
        formatted_clusters=formatted_clusters,
        formatted_watchlist=formatted_watchlist,
        title=article.get("title", ""),
        source=article.get("source", ""),
        description=article.get("description", ""),
        topic=topic,
        source_count=source_count,
        source_names=", ".join(source_names),
        source_tiers=", ".join(source_tiers),
        tier_diversity=tier_diversity,
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
