"""Theme-level deduplication: cluster articles by theme and keep only the best source.

Preserves cluster metadata on the surviving article so downstream stages can
signal cross-source confirmation (source_count, source_tiers, tier_diversity).
"""

import os
import json

from google import genai


THEME_DEDUP_PROMPT = """These articles were collected for a daily intelligence scan. Group them by theme.
For each theme group with multiple articles, identify the BEST source (most credible, most original reporting).
Mark duplicates. Every article must appear in exactly one group (as best_article_index or in duplicate_indices).

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


def _attach_cluster_metadata(article: dict, group_articles: list):
    """Attach source_count, source_names, source_tiers, tier_diversity to an article."""
    source_names = sorted({a.get("source", "Unknown") for a in group_articles if a.get("source")})
    source_tiers = sorted({a.get("tier", "Trade Press") for a in group_articles if a.get("tier")})
    article["source_count"] = len(group_articles)
    article["source_names"] = source_names
    article["source_tiers"] = source_tiers
    article["tier_diversity"] = len(source_tiers)


def _attach_singleton_metadata(article: dict):
    """Attach default cluster metadata for an article that wasn't grouped."""
    article["source_count"] = 1
    article["source_names"] = [article.get("source", "Unknown")]
    article["source_tiers"] = [article.get("tier", "Trade Press")]
    article["tier_diversity"] = 1


def deduplicate_by_theme(news_data: list) -> list:
    """Batch all articles, cluster by theme, keep only the best per theme.

    Attaches source_count, source_names, source_tiers, tier_diversity to each
    surviving article so downstream stages can weigh cross-source signal.

    Args:
        news_data: List of topic dicts from collect + search.

    Returns:
        Updated news_data with duplicates removed and cluster metadata attached.
    """
    api_key = os.environ.get("GEMINI_API_KEY")

    # Flatten all articles with a global index
    flat_articles = []
    article_origins = []  # Track (topic_idx, article_idx) for each flat article
    for t_idx, topic_data in enumerate(news_data):
        for a_idx, article in enumerate(topic_data["articles"]):
            flat_articles.append(article)
            article_origins.append((t_idx, a_idx))

    if not api_key or len(flat_articles) < 3:
        # Too few articles to dedup, or no API — just mark every article as singleton
        for article in flat_articles:
            _attach_singleton_metadata(article)
        if not api_key:
            print("  Warning: GEMINI_API_KEY not set, skipping theme dedup")
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

        # Collect duplicate indices and attach cluster metadata to survivors
        duplicates_to_remove = set()
        grouped_indices = set()

        for group in theme_groups:
            best_idx = group.get("best_article_index")
            dup_indices = group.get("duplicate_indices", []) or []

            # Validate indices
            if not isinstance(best_idx, int) or not (0 <= best_idx < len(flat_articles)):
                continue
            valid_dups = [i for i in dup_indices if isinstance(i, int) and 0 <= i < len(flat_articles) and i != best_idx]

            # Build the full group (best + dups)
            group_members = [flat_articles[best_idx]] + [flat_articles[i] for i in valid_dups]

            # Attach cluster metadata to the surviving article
            _attach_cluster_metadata(flat_articles[best_idx], group_members)

            duplicates_to_remove.update(valid_dups)
            grouped_indices.add(best_idx)
            grouped_indices.update(valid_dups)

        # Any article not assigned to a group is a singleton
        for i, article in enumerate(flat_articles):
            if i not in grouped_indices:
                _attach_singleton_metadata(article)

        if not duplicates_to_remove:
            print("  No theme duplicates found")
            return news_data

        # Remove duplicates from news_data by rebuilding each topic's article list
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
        # On failure, ensure every article has default metadata so downstream doesn't break
        for article in flat_articles:
            if "source_count" not in article:
                _attach_singleton_metadata(article)
        return news_data
