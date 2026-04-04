"""Stage 2: Generate a strategic briefing script from classified news using Google Gemini."""

import os
from google import genai

from knowledge import load_ripple_context


# Prompt templates by recap length — now strategic briefing format
PROMPTS = {
    "short": """You are Dispatch, Laura's strategic intelligence briefer.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

Write a spoken strategic briefing (~2 minutes when read aloud).

Structure:
1. OPEN: Top strategic signal today and why it matters to Ripple (2-3 sentences)
2. STRATEGIC SIGNALS: HIGH and MEDIUM articles with Ripple angle, grouped by cluster
3. PLATFORM RADAR: FYI items, 1 sentence each
4. CLOSE: One action Laura should take today

Rules:
- Start immediately with the top signal — do NOT say "good morning" or reference a time of day
- Skip LOW and Dispose articles entirely
- Use the Ripple angle and cluster context provided — do not reclassify
- Use natural, conversational language — this will be read aloud
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Mention sources by name

{articles}""",

    "medium": """You are Dispatch, Laura's strategic intelligence briefer.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

Write a spoken strategic briefing (~5 minutes when read aloud).

Structure:
1. OPEN: Top strategic signal today and why it matters to Ripple (2-3 sentences)
2. STRATEGIC SIGNALS: HIGH and MEDIUM articles grouped by cluster, with Ripple angle for each. Explain why each matters to Pebble's positioning.
3. PLATFORM RADAR: FYI items, 1-2 sentences each, at the end
4. CLOSE: One action Laura should take today

Rules:
- Start immediately with the top signal — do NOT say "good morning" or reference a time of day
- Skip LOW and Dispose articles entirely
- Use the Ripple angle and cluster context provided — do not reclassify
- Draw connections between signals in the same cluster
- Use natural, conversational language — this will be read aloud
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Mention sources by name

{articles}""",

    "deep": """You are Dispatch, Laura's strategic intelligence briefer.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

Write a spoken strategic briefing (~10 minutes when read aloud).

Structure:
1. OPEN: Top strategic signal today and why it matters to Ripple (2-3 sentences). Frame the day's theme.
2. STRATEGIC SIGNALS: HIGH and MEDIUM articles grouped by cluster. For each:
   - What happened and who said it
   - The Ripple angle — how this connects to Pebble's positioning
   - The suggested action and why
   - Connections to other signals or patterns from recent days
3. PLATFORM RADAR: FYI items with brief context, 2-3 sentences each
4. CLOSE: Top action Laura should take today, and one pattern to watch this week

Rules:
- Start immediately with the top signal — do NOT say "good morning" or reference a time of day
- Skip LOW and Dispose articles entirely
- Use the Ripple angle and cluster context provided — do not reclassify
- Draw connections between signals across clusters
- Use natural, conversational language — this will be read aloud
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Mention sources by name

{articles}""",
}


def generate_script(news_data: list, recap_length: str = "medium",
                    classified_articles: list = None) -> str:
    """Generate a strategic briefing script from collected news articles.

    Args:
        news_data: Output from collect.collect_news() (fallback if no classified data)
        recap_length: "short", "medium", or "deep"
        classified_articles: Output from log_to_notion() — articles with classification fields.
            If provided, used instead of raw news_data for richer briefing.

    Returns:
        Plain text script ready for TTS.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, falling back to headline list")
        return _fallback_script(news_data)

    client = genai.Client(api_key=api_key)

    # Load positioning context
    ripple_context = load_ripple_context()

    # Format articles — prefer classified data if available
    if classified_articles:
        articles_text = _format_classified_articles(classified_articles)
    else:
        articles_text = _format_articles(news_data)

    if not articles_text.strip():
        return "No strategic signals today. Check back tomorrow."

    prompt_template = PROMPTS.get(recap_length, PROMPTS["medium"])
    prompt = prompt_template.format(
        ripple_context=ripple_context,
        articles=articles_text,
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        script = response.text.strip()
        print(f"  Generated {recap_length} strategic briefing ({len(script)} chars)")
        return script
    except Exception as e:
        print(f"  Error calling Gemini: {e}")
        print("  Falling back to headline list")
        return _fallback_script(news_data)


def _format_classified_articles(classified_articles: list) -> str:
    """Format classified articles with strategic context for the briefing prompt."""
    # Separate by relevance tier
    high = [a for a in classified_articles if a.get("relevance") == "HIGH"]
    medium = [a for a in classified_articles if a.get("relevance") == "MEDIUM"]
    fyi = [a for a in classified_articles if a.get("relevance") == "FYI"]

    sections = []

    if high:
        sections.append("\n=== HIGH PRIORITY — Act Today ===")
        for art in high:
            sections.append(f"\nHeadline: {art['title']}")
            sections.append(f"Source: {art.get('source', 'Unknown')}")
            sections.append(f"Cluster: {art.get('cluster_match', 'none')}")
            sections.append(f"Ripple Angle: {art.get('ripple_angle', 'N/A')}")
            sections.append(f"Action: {art.get('action_type', 'read')} — {art.get('suggested_action', 'Review')}")
            if art.get("description"):
                sections.append(f"Summary: {art['description'][:300]}")

    if medium:
        sections.append("\n=== MEDIUM — Worth Knowing ===")
        for art in medium:
            sections.append(f"\nHeadline: {art['title']}")
            sections.append(f"Source: {art.get('source', 'Unknown')}")
            sections.append(f"Cluster: {art.get('cluster_match', 'none')}")
            sections.append(f"Ripple Angle: {art.get('ripple_angle', 'N/A')}")
            sections.append(f"Action: {art.get('action_type', 'track')} — {art.get('suggested_action', 'Monitor')}")
            if art.get("description"):
                sections.append(f"Summary: {art['description'][:300]}")

    if fyi:
        sections.append("\n=== FYI — Platform Radar ===")
        for art in fyi:
            sections.append(f"\nHeadline: {art['title']}")
            sections.append(f"Source: {art.get('source', 'Unknown')}")
            if art.get("description"):
                sections.append(f"Summary: {art['description'][:200]}")

    return "\n".join(sections)


def _format_articles(news_data: list) -> str:
    """Format raw news data into a readable text block (fallback when no classification)."""
    sections = []
    for topic_data in news_data:
        topic = topic_data["topic"]
        articles = topic_data["articles"]
        if not articles:
            continue

        section = f"\n--- {topic} ---\n"
        for art in articles:
            section += f"\nHeadline: {art['title']}\n"
            section += f"Source: {art['source']}\n"
            if art["description"]:
                section += f"Summary: {art['description']}\n"
        sections.append(section)

    return "\n".join(sections)


def _fallback_script(news_data: list) -> str:
    """Simple headline list when Gemini is unavailable."""
    lines = ["Here are today's headlines.\n"]
    for topic_data in news_data:
        topic = topic_data["topic"]
        articles = topic_data["articles"]
        if not articles:
            continue
        lines.append(f"In {topic}:")
        for art in articles:
            lines.append(f"  {art['title']}, from {art['source']}.")
        lines.append("")
    lines.append("That's your briefing for today.")
    return "\n".join(lines)
