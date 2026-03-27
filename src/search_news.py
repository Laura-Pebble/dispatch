"""Stage 1b: Search the web for news beyond RSS feeds using Gemini grounding."""

import os
import json
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

        # Deduplicate against RSS results
        unique_articles = []
        for art in articles:
            url = art.get("url", "")
            if url and url not in existing_urls:
                existing_urls.add(url)
                unique_articles.append({
                    "title": art.get("title", "Untitled"),
                    "description": art.get("description", ""),
                    "url": url,
                    "source": art.get("source", "Web Search"),
                    "published": "",
                })

        unique_articles = unique_articles[:max_results]
        print(f"  [Web Search] Found {len(unique_articles)} unique articles")
        return unique_articles

    except Exception as e:
        print(f"  Warning: Web search failed: {e}")
        return []
