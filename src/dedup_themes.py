"""Theme-level deduplication: cluster articles by theme and keep only the best source."""

import os
import json

from google import genai


THEME_DEDUP_PROMPT = """These articles were collected for a daily intelligence scan. Group them by theme.
For each theme group with multiple articles, identify the BEST source (most credible, most original reporting).
Mark duplicates.

Articles:
{articles}

Respond in JSON only, no markdown fences:
[
  {{
    "theme": "short theme description",
    "best_article_index": 0,
    "duplicate_indices": [1, 3],
    "reason": "why the best source was chosen"
  }}
]"""


def deduplicate_by_theme(news_data: list) -> list:
    """Batch all articles, cluster by theme, keep only the best per theme.

    Args:
        news_data: List of topic dicts from collect + search.

    Returns:
        Updated news_data with duplicates removed.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, skipping theme dedup")
        return news_data

    # Flatten all articles with a global index
    flat_articles = []
    article_origins = []  # Track (topic_idx, article_idx) for each flat article
    for t_idx, topic_data in enumerate(news_data):
        for a_idx, article in enumerate(topic_data["articles"]):
            flat_articles.append(article)
            article_origins.append((t_idx, a_idx))

    if len(flat_articles) < 3:
        # Not enough articles to meaningfully dedup
        return news_data

    # Build the articles list for the prompt
    articles_text = ""
    for i, art in enumerate(flat_articles):
        articles_text += f"\n[{i}] Title: {art['title']}\n    Source: {art['source']}\n    Summary: {art.get('description', '')[:200]}\n"

    prompt = THEME_DEDUP_PROMPT.format(articles=articles_text)

    try:
        client = genai.Client(api_key=api_key)
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

        theme_groups = json.loads(text.strip())

        # Collect all duplicate indices to remove
        duplicates_to_remove = set()
        for group in theme_groups:
            dup_indices = group.get("duplicate_indices", [])
            for idx in dup_indices:
                if isinstance(idx, int) and 0 <= idx < len(flat_articles):
                    duplicates_to_remove.add(idx)

        if not duplicates_to_remove:
            print("  No theme duplicates found")
            return news_data

        # Remove duplicates from news_data by rebuilding each topic's article list
        # Build a set of (topic_idx, article_idx) to remove
        removals = set()
        for flat_idx in duplicates_to_remove:
            removals.add(article_origins[flat_idx])

        for t_idx, topic_data in enumerate(news_data):
            original_count = len(topic_data["articles"])
            topic_data["articles"] = [
                art for a_idx, art in enumerate(topic_data["articles"])
                if (t_idx, a_idx) not in removals
            ]
            removed = original_count - len(topic_data["articles"])
            if removed:
                print(f"    [{topic_data['topic']}] Removed {removed} theme duplicate(s)")

        total_removed = len(duplicates_to_remove)
        print(f"  Theme dedup: removed {total_removed} duplicate article(s)")
        return news_data

    except Exception as e:
        print(f"  Warning: Theme dedup failed: {e}")
        return news_data
