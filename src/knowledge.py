"""Load Ripple positioning context and Topic Clusters from Notion."""

import os
from pathlib import Path


def load_ripple_context() -> str:
    """Load the static positioning knowledge layer."""
    path = Path(__file__).parent.parent / "knowledge" / "ripple_context.md"
    if path.exists():
        return path.read_text()
    print("  Warning: ripple_context.md not found, running without positioning context")
    return ""


def load_clusters(notion_client) -> list:
    """Fetch active Topic Clusters from Notion with their market terms and search queries.

    Returns list of dicts: [{"name": str, "market_terms": str, "search_queries": str, "page_id": str}]
    """
    DATABASE_ID = "4d7d6c1ee95a48c4ba3101ee952fc5c0"
    clusters = []
    try:
        has_more = True
        start_cursor = None
        while has_more:
            kwargs = {
                "database_id": DATABASE_ID,
                "page_size": 100,
                "filter": {"property": "Status", "select": {"equals": "Active"}}
            }
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            response = notion_client.databases.query(**kwargs)
            for page in response.get("results", []):
                props = page.get("properties", {})
                name_parts = props.get("Cluster", {}).get("title", [])
                name = name_parts[0]["text"]["content"] if name_parts else ""
                mt_parts = props.get("Market Terms", {}).get("rich_text", [])
                market_terms = mt_parts[0]["text"]["content"] if mt_parts else ""
                sq_parts = props.get("Search Queries", {}).get("rich_text", [])
                search_queries = sq_parts[0]["text"]["content"] if sq_parts else ""
                clusters.append({
                    "name": name,
                    "market_terms": market_terms,
                    "search_queries": search_queries,
                    "page_id": page["id"],
                })
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
    except Exception as e:
        print(f"  Warning: Could not fetch clusters: {e}")
    return clusters


def format_clusters_for_prompt(clusters: list) -> str:
    """Format cluster data for insertion into the classification prompt."""
    if not clusters:
        return "No clusters loaded."
    lines = []
    for c in clusters:
        lines.append(f"Cluster: {c['name']}")
        lines.append(f"  Market terms: {c['market_terms']}")
        lines.append("")
    return "\n".join(lines)
