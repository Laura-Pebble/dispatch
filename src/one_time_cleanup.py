"""One-time database cleanup — run after v2 classification upgrade is in place.

This script:
1. Sets specific articles to FYI, Archived, or Dispose per the handoff doc
2. Reclassifies remaining HIGH/MEDIUM articles with the new positioning-aware prompt
   to backfill Action Type, Suggested Action, Ripple Angle, and Topic Cluster

Usage: python src/one_time_cleanup.py
"""

import os
import sys
import json
from datetime import datetime, timezone

from google import genai
from notion_client import Client

from knowledge import load_ripple_context, load_clusters, format_clusters_for_prompt
from log_notion import CLASSIFY_PROMPT, DATABASE_ID


def run_cleanup():
    notion_token = os.environ.get("NOTION_TOKEN")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not notion_token:
        print("ERROR: NOTION_TOKEN not set")
        sys.exit(1)

    notion = Client(auth=notion_token)

    # === STEP 1: Manual updates ===
    print("\n=== Step 1: Manual article updates ===")

    # Set Relevance = FYI
    fyi_ids = [
        "33603ac6b3898127beabf8d5bec71f7b",  # GPT-4o Fully Retired
        "33603ac6b389810f9111ddc513aa05b3",  # Claude Mythos Model
        "33603ac6b38981f1ae21feef4510eb06",  # Claude Code Source Leak
        "33603ac6b38981faa85beefd65d6a4c2",  # Anthropic Retiring 1M Context
        "33603ac6b38981c896a0ccb8e2c38674",  # ChatGPT Enterprise Write Actions
    ]
    for page_id in fyi_ids:
        try:
            notion.pages.update(
                page_id=page_id,
                properties={"Relevance": {"select": {"name": "FYI"}}},
            )
            print(f"  Set FYI: {page_id[:12]}...")
        except Exception as e:
            print(f"  Failed FYI {page_id[:12]}: {e}")

    # Set Status = Archived (duplicates)
    archive_dup_ids = [
        "32903ac6b38981b9bc2ff729b745857b",  # Vibe Marketing dup
    ]
    for page_id in archive_dup_ids:
        try:
            notion.pages.update(
                page_id=page_id,
                properties={"Status": {"select": {"name": "Archived"}}},
            )
            print(f"  Archived (dup): {page_id[:12]}...")
        except Exception as e:
            print(f"  Failed archive {page_id[:12]}: {e}")

    # Set Status = Archived (generic roundups)
    archive_roundup_ids = [
        "33003ac6b38981b8a278c0cfb9b12844",  # Top 10 B2B Marketing Trends
        "33203ac6b389811e97a8d769f5b6c11b",  # Five B2B Marketing Trends
        "33203ac6b38981289710df6f8e672c6d",  # Top 5 B2B Marketing Trends
    ]
    for page_id in archive_roundup_ids:
        try:
            notion.pages.update(
                page_id=page_id,
                properties={"Status": {"select": {"name": "Archived"}}},
            )
            print(f"  Archived (roundup): {page_id[:12]}...")
        except Exception as e:
            print(f"  Failed archive {page_id[:12]}: {e}")

    # Set Relevance = Dispose
    dispose_ids = [
        "33603ac6b38981cd8533d65fb4c80d99",  # Claude Operon — Life Sciences
        "33603ac6b38981cb971bf8f000d10442",  # Greg Kihlström Named #1
    ]
    for page_id in dispose_ids:
        try:
            notion.pages.update(
                page_id=page_id,
                properties={"Relevance": {"select": {"name": "Dispose"}}},
            )
            print(f"  Set Dispose: {page_id[:12]}...")
        except Exception as e:
            print(f"  Failed dispose {page_id[:12]}: {e}")

    # === STEP 2: Backfill reclassification ===
    print("\n=== Step 2: Backfill classification on HIGH/MEDIUM articles ===")

    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, skipping reclassification")
        return

    gemini_client = genai.Client(api_key=api_key)
    ripple_context = load_ripple_context()
    clusters = load_clusters(notion)
    formatted_clusters = format_clusters_for_prompt(clusters)
    cluster_lookup = {c["name"].lower(): c for c in clusters}

    # Query HIGH and MEDIUM articles that don't have Action Type set yet
    reclassified = 0
    for relevance_level in ["HIGH", "MEDIUM"]:
        has_more = True
        start_cursor = None
        while has_more:
            kwargs = {
                "database_id": DATABASE_ID,
                "page_size": 100,
                "filter": {
                    "and": [
                        {"property": "Relevance", "select": {"equals": relevance_level}},
                        {"property": "Status", "select": {"does_not_equal": "Archived"}},
                    ]
                },
            }
            if start_cursor:
                kwargs["start_cursor"] = start_cursor

            response = notion.databases.query(**kwargs)
            for page in response.get("results", []):
                props = page.get("properties", {})

                # Skip if already has Action Type
                action_type = props.get("Action Type", {}).get("select")
                if action_type:
                    continue

                # Extract article info
                title_parts = props.get("Title", {}).get("title", [])
                title = title_parts[0]["text"]["content"] if title_parts else ""
                source_parts = props.get("Source", {}).get("rich_text", [])
                source = source_parts[0]["text"]["content"] if source_parts else ""
                wim_parts = props.get("Why It Matters", {}).get("rich_text", [])
                description = wim_parts[0]["text"]["content"] if wim_parts else ""

                # Get topic from Category
                category = props.get("Category", {}).get("select", {})
                topic = category.get("name", "General") if category else "General"

                # Classify with new prompt
                prompt = CLASSIFY_PROMPT.format(
                    ripple_context=ripple_context,
                    formatted_clusters=formatted_clusters,
                    title=title,
                    source=source,
                    description=description,
                    topic=topic,
                )

                try:
                    resp = gemini_client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                    )
                    text = resp.text.strip()
                    if text.startswith("```"):
                        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    classification = json.loads(text.strip())
                except Exception as e:
                    print(f"    Reclassify failed for '{title[:40]}': {e}")
                    continue

                # Update the page with new fields
                update_props = {}
                if classification.get("action_type"):
                    update_props["Action Type"] = {"select": {"name": classification["action_type"]}}
                if classification.get("suggested_action"):
                    update_props["Suggested Action"] = {
                        "rich_text": [{"text": {"content": classification["suggested_action"][:2000]}}]
                    }
                if classification.get("ripple_angle"):
                    update_props["Ripple Angle"] = {
                        "rich_text": [{"text": {"content": classification["ripple_angle"][:2000]}}]
                    }

                # Cluster match
                cluster_match = classification.get("cluster_match", "none")
                matched_cluster = None
                if cluster_match and cluster_match.lower() not in ("none", "null", ""):
                    if not cluster_match.lower().startswith("potential new cluster"):
                        matched_cluster = cluster_lookup.get(cluster_match.lower())
                        if matched_cluster:
                            update_props["Topic Clusters"] = {
                                "relation": [{"id": matched_cluster["page_id"]}]
                            }

                if update_props:
                    try:
                        notion.pages.update(page_id=page["id"], properties=update_props)
                        reclassified += 1
                        print(f"    Reclassified [{relevance_level}]: {title[:50]}...")
                    except Exception as e:
                        print(f"    Failed to update '{title[:40]}': {e}")

                    # Update cluster terms if applicable
                    if matched_cluster and classification.get("new_market_terms"):
                        existing = matched_cluster.get("market_terms", "")
                        existing_lower = existing.lower()
                        truly_new = [t for t in classification["new_market_terms"] if t.lower() not in existing_lower]
                        if truly_new:
                            updated = existing + ", " + ", ".join(truly_new) if existing else ", ".join(truly_new)
                            try:
                                notion.pages.update(
                                    page_id=matched_cluster["page_id"],
                                    properties={"Market Terms": {"rich_text": [{"text": {"content": updated[:2000]}}]}},
                                )
                            except Exception:
                                pass
                    if matched_cluster:
                        try:
                            notion.pages.update(
                                page_id=matched_cluster["page_id"],
                                properties={"Last Signal": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}}},
                            )
                        except Exception:
                            pass

            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")

    print(f"\n  Reclassified {reclassified} existing articles")
    print("\nCleanup complete!")


if __name__ == "__main__":
    run_cleanup()
