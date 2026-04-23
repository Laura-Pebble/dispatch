"""Stage 1b: Search the web for news beyond RSS feeds using Gemini grounding."""

import os
import json
import requests
from google import genai
from google.genai import types


def search_news(queries: list, max_results: int = 5, existing_urls: set = None) -> list:
    """Search for recent news articles using Gemini with Google Search grounding.

    Args:
        queries: List of search query strings from config.
        max_results: Max total articles to return from search.
        existing_urls: URLs already collected from RSS (for dedup).

    Returns:
        List of article dicts: [{"title", "description", "url", "source", "published"}]
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, skipping web search")
        return []

    if not queries:
        return []

    if existing_urls is None:
        existing_urls = set()

    client = genai.Client(api_key=api_key)

    prompt = f"""Search for the most important news articles from the last 24 hours on these topics:

{chr(10).join(f'- {q}' for q in queries)}

Return ONLY a JSON array of articles. Each article must have these exact fields:
- "title": the article headline
- "description": 1-2 sentence summary
- "url": the full URL to the article
- "source": the publication name

Return between 3 and {max_results} articles. Only include real, recent articles you find.
Prioritize articles that would be surprising, counterintuitive, or directly relevant to a B2B marketing executive.
Do NOT fabricate articles. Only return articles you can verify exist.

Return ONLY the JSON array, no other text."""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )

        # response.text can be None when grounding returns results differently
        raw_text = response.text
        if raw_text is None:
            # Try extracting text from response parts
            parts = []
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if part.text:
                        parts.append(part.text)
            raw_text = "".join(parts)

        if not raw_text:
            print("  Warning: Web search returned empty response")
            return []

        text = raw_text.strip()

        # Extract JSON from response (handle markdown code blocks)
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        articles = json.loads(text)

        # Resolve Vertex grounding redirects + deduplicate against RSS results
        unique_articles = []
        for art in articles:
            raw_url = art.get("url", "")
            if not raw_url:
                continue
            url = _resolve_url(raw_url)
            if url in existing_urls:
                continue
            existing_urls.add(url)
            unique_articles.append({
                "title": art.get("title", "Untitled"),
                "description": art.get("description", ""),
                "url": url,
                "source": art.get("source", "Web Search"),
                "published": "",
                "tier": _infer_tier(art.get("source", ""), url),
            })

        unique_articles = unique_articles[:max_results]
        print(f"  [Web Search] Found {len(unique_articles)} unique articles")
        return unique_articles

    except Exception as e:
        print(f"  Warning: Web search failed: {e}")
        return []


_TIER_DOMAINS = {
    "Primary": [
        "anthropic.com", "openai.com", "blog.google", "deepmind.com",
        "ai.google", "perplexity.ai", "arxiv.org",
    ],
    "Practitioner": [
        "oneusefulthing.org", "every.to", "bensbites.beehiiv.com",
        "latent.space", "lennysnewsletter.com",
    ],
}


def _infer_tier(source: str, url: str) -> str:
    """Map search-surfaced source/URL to a tier; default Trade Press."""
    haystack = f"{source} {url}".lower()
    for tier, domains in _TIER_DOMAINS.items():
        for d in domains:
            if d in haystack:
                return tier
    return "Trade Press"


def _resolve_url(url: str) -> str:
    """Follow Vertex AI grounding redirect to the real article URL.

    Gemini's grounded search returns wrappers like
    `https://vertexaisearch.cloud.google.com/grounding-api-redirect/<token>`
    instead of the actual article URL. Resolving here means downstream
    (Notion, podcast feed) gets clickable source URLs. Falls back to the
    wrapper if resolution fails — better than dropping the article.
    """
    if "vertexaisearch.cloud.google.com" not in url:
        return url
    try:
        r = requests.head(url, allow_redirects=True, timeout=10)
        final = r.url or url
        return final if "vertexaisearch.cloud.google.com" not in final else url
    except Exception:
        return url
