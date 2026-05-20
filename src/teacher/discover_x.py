"""Discover recent X / Twitter posts from curated handles via Gemini grounding.

X has no clean RSS surface anymore; Nitter instances are unreliable. We reuse
the proven pattern from src/search_news.py: Gemini with Google Search grounding,
constrained to `site:x.com` and the handle.

Each handle becomes a query like:
  "bcherny" site:x.com recent AI marketing engineering

The model returns recent posts with title (first 10-12 words), description,
URL, and source field formatted as "X (@handle)".
"""

import os
import json
import time
from datetime import datetime, timezone

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None


def discover_x_handles(x_handles: list, max_items_per_handle: int = 2, lesson_topic: str = "") -> list:
    """For each handle, run a Gemini-grounded search for their recent posts.

    Returns list of dicts: {title, url, author, source, source_type='X',
                            source_tier='Practitioner', date_published, summary, full_text}
    """
    if not x_handles or genai is None:
        return []

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set — X discovery skipped")
        return []

    client = genai.Client(api_key=api_key)
    items = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Topic hint biases the search toward posts adjacent to this week's lesson;
    # if empty, we fall back to broad AI / marketing relevance.
    topic_hint = lesson_topic.strip() or "AI tools, model capabilities, agent design, marketing"

    for handle in x_handles:
        handle_clean = handle.lstrip("@")
        query = f'"{handle_clean}" site:x.com recent {topic_hint}'
        print(f"  [X] @{handle_clean}…")

        prompt = f"""Search for the most recent {max_items_per_handle} substantive public posts from @{handle_clean} on X (Twitter).

Search query: {query}

Return ONLY a JSON array of {max_items_per_handle} items or fewer. Each item must have these exact fields:
- "title": the first 10-15 words of the post (no truncation marker)
- "description": the substantive content of the post (2-4 sentences)
- "url": the full post URL (x.com/{handle_clean}/status/...)
- "date": YYYY-MM-DD if you can determine it, else ""

Rules:
- ONLY include posts from @{handle_clean} themselves, not replies or retweets.
- ONLY include posts you can verify are real and recent (within the last 14 days).
- Prefer posts that explain a mechanic, share a finding, or argue a position — skip pure self-promotion.
- Do NOT fabricate. If you can't find {max_items_per_handle} qualifying posts, return fewer.

Return ONLY the JSON array, no other text."""

        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            raw_text = response.text or ""
            if not raw_text:
                parts = []
                for cand in response.candidates or []:
                    for p in (cand.content.parts or []):
                        if p.text:
                            parts.append(p.text)
                raw_text = "".join(parts)

            text = raw_text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            parsed = json.loads(text) if text else []
            count = 0
            for post in parsed[:max_items_per_handle]:
                url = post.get("url", "")
                if not url or "x.com" not in url and "twitter.com" not in url:
                    continue
                items.append({
                    "title": post.get("title", "")[:200],
                    "url": url,
                    "author": f"@{handle_clean}",
                    "source": f"X (@{handle_clean})",
                    "source_type": "X",
                    "source_tier": "Practitioner",
                    "date_published": post.get("date", ""),
                    "summary": post.get("description", "")[:1500],
                    "full_text": post.get("description", "")[:2000],
                })
                count += 1
            print(f"    +{count} post(s)")

        except Exception as e:
            print(f"    @{handle_clean} failed: {e}")
            continue

        time.sleep(1.5)  # Be gentle on the API

    print(f"  [X] {len(items)} post(s) total")
    return items
