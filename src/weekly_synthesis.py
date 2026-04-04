"""Weekly synthesis: Friday summary of the week's intelligence signals.

Fetches articles from the past 7 days, groups by cluster, summarizes signal
volume per cluster, flags momentum changes, and writes a Notion page.

Usage:
  python src/weekly_synthesis.py        (standalone)
  Called from main.py on Fridays        (automated)
"""

import os
import json
from datetime import datetime, timedelta, timezone

from google import genai
from notion_client import Client

from knowledge import load_ripple_context, load_clusters
from log_notion import DATABASE_ID


SYNTHESIS_PROMPT = """You are generating a weekly intelligence synthesis for Pebble Marketing.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

Here are this week's classified articles grouped by topic cluster:

{articles_by_cluster}

Generate a strategic weekly synthesis. Structure:

1. **Week in Review** (2-3 sentences): What was the dominant signal this week?
2. **Cluster Analysis**: For each active cluster:
   - Signal volume (how many articles)
   - Key signals and their implications for Pebble
   - Momentum: accelerating, steady, or cooling
3. **Emerging Patterns**: Connections between clusters or signals that suggest a market shift
4. **Content Gaps**: Topics Laura should be writing about but hasn't yet
5. **Action Items**: Top 3 things to do next week based on this week's signals

Rules:
- Be specific, not generic. Reference actual articles.
- Flag any potential new clusters (themes appearing that don't fit existing clusters).
- Keep it concise — this is a strategic summary, not a rewrite of every article.

Respond in markdown format suitable for a Notion page."""


# Database ID for the Industry Intel parent (where synthesis pages go)
INTEL_DATABASE_ID = "fe848ba99f874eefbd16d37cfb967cdc"


def generate_weekly_synthesis():
    """Generate and publish the weekly synthesis to Notion."""
    notion_token = os.environ.get("NOTION_TOKEN")
    api_key = os.environ.get("GEMINI_API_KEY")

    if not notion_token:
        print("  Warning: NOTION_TOKEN not set, skipping weekly synthesis")
        return

    notion = Client(auth=notion_token)

    # Fetch articles from the past 7 days
    print("  Fetching articles from the past 7 days...")
    seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
    articles = _fetch_recent_articles(notion, seven_days_ago)

    if not articles:
        print("  No articles found for weekly synthesis")
        return

    print(f"  Found {len(articles)} articles from this week")

    # Load clusters
    clusters = load_clusters(notion)
    cluster_names = {c["page_id"]: c["name"] for c in clusters}

    # Group articles by cluster
    articles_by_cluster = _group_by_cluster(articles, cluster_names)

    # Generate synthesis with Gemini
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, skipping synthesis generation")
        return

    ripple_context = load_ripple_context()
    synthesis_text = _generate_synthesis(api_key, ripple_context, articles_by_cluster)

    if not synthesis_text:
        print("  Failed to generate synthesis")
        return

    # Write to Notion as a new page (subpage of the Industry Intel database)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"Weekly Synthesis — {today}"

    try:
        notion.pages.create(
            parent={"database_id": INTEL_DATABASE_ID},
            properties={
                "Title": {"title": [{"text": {"content": title}}]},
                "Status": {"select": {"name": "To Review"}},
                "Category": {"select": {"name": "Thought Leadership"}},
                "Relevance": {"select": {"name": "HIGH"}},
                "Date Found": {"date": {"start": today}},
                "Tags": {"multi_select": [{"name": "methodology"}]},
                "Why It Matters": {
                    "rich_text": [{"text": {"content": "Weekly intelligence synthesis — cluster analysis and momentum tracking"}}]
                },
            },
            children=_markdown_to_blocks(synthesis_text),
        )
        print(f"  Published: {title}")
    except Exception as e:
        print(f"  Failed to publish synthesis: {e}")

    # Update cluster Signal Strength based on volume
    _update_signal_strengths(notion, clusters, articles_by_cluster)


def _fetch_recent_articles(notion: Client, since_date: str) -> list:
    """Fetch articles from the database since the given date."""
    articles = []
    has_more = True
    start_cursor = None

    while has_more:
        kwargs = {
            "database_id": DATABASE_ID,
            "page_size": 100,
            "filter": {
                "and": [
                    {"property": "Date Found", "date": {"on_or_after": since_date}},
                    {"property": "Status", "select": {"does_not_equal": "Archived"}},
                    {"property": "Relevance", "select": {"does_not_equal": "Dispose"}},
                ]
            },
        }
        if start_cursor:
            kwargs["start_cursor"] = start_cursor

        response = notion.databases.query(**kwargs)
        for page in response.get("results", []):
            props = page.get("properties", {})

            title_parts = props.get("Title", {}).get("title", [])
            title = title_parts[0]["text"]["content"] if title_parts else ""

            source_parts = props.get("Source", {}).get("rich_text", [])
            source = source_parts[0]["text"]["content"] if source_parts else ""

            relevance = props.get("Relevance", {}).get("select", {})
            relevance_name = relevance.get("name", "") if relevance else ""

            action_type = props.get("Action Type", {}).get("select", {})
            action_name = action_type.get("name", "") if action_type else ""

            ripple_parts = props.get("Ripple Angle", {}).get("rich_text", [])
            ripple_angle = ripple_parts[0]["text"]["content"] if ripple_parts else ""

            wim_parts = props.get("Why It Matters", {}).get("rich_text", [])
            why_it_matters = wim_parts[0]["text"]["content"] if wim_parts else ""

            cluster_rels = props.get("Topic Clusters", {}).get("relation", [])
            cluster_ids = [r["id"] for r in cluster_rels] if cluster_rels else []

            articles.append({
                "title": title,
                "source": source,
                "relevance": relevance_name,
                "action_type": action_name,
                "ripple_angle": ripple_angle,
                "why_it_matters": why_it_matters,
                "cluster_ids": cluster_ids,
            })

        has_more = response.get("has_more", False)
        start_cursor = response.get("next_cursor")

    return articles


def _group_by_cluster(articles: list, cluster_names: dict) -> dict:
    """Group articles by their cluster assignment."""
    grouped = {"Unclustered": []}
    for art in articles:
        if art["cluster_ids"]:
            for cid in art["cluster_ids"]:
                name = cluster_names.get(cid, "Unknown Cluster")
                grouped.setdefault(name, []).append(art)
        else:
            grouped["Unclustered"].append(art)

    # Remove empty unclustered
    if not grouped["Unclustered"]:
        del grouped["Unclustered"]

    return grouped


def _generate_synthesis(api_key: str, ripple_context: str, articles_by_cluster: dict) -> str:
    """Generate the weekly synthesis text using Gemini."""
    # Format articles by cluster for the prompt
    sections = []
    for cluster_name, arts in sorted(articles_by_cluster.items()):
        section = f"\n## {cluster_name} ({len(arts)} articles)\n"
        for art in arts:
            section += f"- [{art['relevance']}] {art['title']} ({art['source']})\n"
            if art["ripple_angle"]:
                section += f"  Ripple Angle: {art['ripple_angle']}\n"
            if art["action_type"]:
                section += f"  Action: {art['action_type']}\n"
        sections.append(section)

    articles_text = "\n".join(sections)

    prompt = SYNTHESIS_PROMPT.format(
        ripple_context=ripple_context,
        articles_by_cluster=articles_text,
    )

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        return response.text.strip()
    except Exception as e:
        print(f"  Gemini synthesis failed: {e}")
        return ""


def _update_signal_strengths(notion: Client, clusters: list, articles_by_cluster: dict):
    """Update cluster Signal Strength based on weekly article volume."""
    for cluster in clusters:
        name = cluster["name"]
        count = len(articles_by_cluster.get(name, []))

        # Simple heuristic: 0 = Low, 1-2 = Medium, 3+ = High
        if count >= 3:
            strength = "High"
        elif count >= 1:
            strength = "Medium"
        else:
            strength = "Low"

        try:
            notion.pages.update(
                page_id=cluster["page_id"],
                properties={
                    "Signal Strength": {"select": {"name": strength}},
                },
            )
        except Exception:
            pass  # Signal Strength field may not exist yet — that's fine


def _markdown_to_blocks(markdown_text: str) -> list:
    """Convert simple markdown to Notion blocks (basic headings + paragraphs)."""
    blocks = []
    for line in markdown_text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("### "):
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]},
            })
        elif line.startswith("## "):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]},
            })
        elif line.startswith("# "):
            blocks.append({
                "object": "block",
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]},
            })
        elif line.startswith("- ") or line.startswith("* "):
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]},
            })
        elif line.startswith("1. ") or line.startswith("2. ") or line.startswith("3. "):
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]},
            })
        else:
            # Strip bold markdown for Notion (would need rich_text formatting)
            clean = line.replace("**", "")
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": clean}}]},
            })

    return blocks[:100]  # Notion limit per request


if __name__ == "__main__":
    generate_weekly_synthesis()
