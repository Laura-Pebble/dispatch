"""Stage 2: Generate a strategic briefing script from classified news using Google Gemini."""

import os
from google import genai

from knowledge import load_ripple_context, load_watchlist, format_watchlist_for_prompt


# Per-slot word budgets for each recap length — density only, slot count is fixed at 4.
LENGTH_BUDGETS = {
    "short": {"words_per_slot": "40-60", "duration": "~2 minutes"},
    "medium": {"words_per_slot": "80-120", "duration": "~5 minutes"},
    "deep": {"words_per_slot": "150-220", "duration": "~10 minutes"},
}


BRIEF_PROMPT = """You are Dispatch, Laura's strategic intelligence briefer.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

<LAURA'S CURRENT WATCHLIST>
{formatted_watchlist}
</LAURA'S CURRENT WATCHLIST>

Write a spoken strategic briefing ({duration} when read aloud). Target {words_per_slot} words per slot.

Structure — exactly 4 slots, in this order. Skip any slot that has no qualifying material rather than padding with filler.

1. THE IDEA
   The single most surprising, contrarian, or game-changing item from today. Must genuinely shift how Laura thinks about marketing, AI, or positioning. If nothing qualifies, skip this slot.

2. STEAL THIS
   One tactical AI workflow Laura could try this week. Must be specific enough to act on (a prompt pattern, a tool stack, a concrete workflow).
   Prioritize, in this order:
   (a) Ripple-aligned: tactics that fit Pebble's delivery model — evidence-based buyer research, confidence tagging, AI-structured brand output, fractional operating model.
   (b) Under-discussed over trending: a tactic almost nobody is using that aligns with Laura beats a tactic everyone is already writing about.
   (c) Adjacent-domain transplants: workflows built for consulting, sales enablement, research, or product that could be adapted to strengthen Ripple.
   If nothing qualifies, skip this slot — do NOT fall back to a generic "top ChatGPT tip."

3. CONFIRMED TRENDS
   Up to 2 themes where multiple independent sources are reporting the same thing (look for "Signal: Confirmed" or "Signal: Multi-Source" in the article data). One sentence each: what the trend is, who's reporting it, why it matters to Pebble's positioning. Skip if no qualifying multi-source themes exist.

4. CONTENT ANGLE
   One thought-leadership hook drawn from today's material that Laura could write or post about. Frame it in her voice and Ripple's positioning.

Rules:
- Start immediately with Slot 1 content — do NOT say "good morning" or reference time of day.
- Label each slot plainly as you speak ("The idea today is...", "Here's one to steal...", "Confirmed trend...", "Content angle...").
- Skip LOW and Dispose articles entirely.
- Use natural conversational language — this will be read aloud.
- NO markdown, bullet points, or formatting — plain spoken text only.
- Mention sources by name.
- Maximum 4 slots total. Never pad. If 2 slots have no material, deliver a 2-slot brief — short is fine.

{articles}"""


def generate_script(news_data: list, recap_length: str = "medium",
                    classified_articles: list = None) -> str:
    """Generate a strategic briefing script from collected news articles.

    Args:
        news_data: Output from collect.collect_news() (fallback if no classified data)
        recap_length: "short", "medium", or "deep" — controls density per slot only.
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

    # Load positioning context and watchlist
    ripple_context = load_ripple_context()
    watchlist = load_watchlist()
    formatted_watchlist = format_watchlist_for_prompt(watchlist)

    # Format articles — prefer classified data if available
    if classified_articles:
        articles_text = _format_classified_articles(classified_articles)
    else:
        articles_text = _format_articles(news_data)

    if not articles_text.strip():
        return "No strategic signals today. Check back tomorrow."

    budget = LENGTH_BUDGETS.get(recap_length, LENGTH_BUDGETS["medium"])
    prompt = BRIEF_PROMPT.format(
        ripple_context=ripple_context,
        formatted_watchlist=formatted_watchlist,
        duration=budget["duration"],
        words_per_slot=budget["words_per_slot"],
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
    """Format classified articles with strategic + cross-source context for the brief prompt."""
    high = [a for a in classified_articles if a.get("relevance") == "HIGH"]
    medium = [a for a in classified_articles if a.get("relevance") == "MEDIUM"]
    fyi = [a for a in classified_articles if a.get("relevance") == "FYI"]

    # Separate stream for the AI Tools and Tactics topic — this powers STEAL THIS
    tactics = [a for a in classified_articles if a.get("topic") == "AI Tools and Tactics"]

    sections = []

    def render(art: dict) -> list:
        lines = []
        lines.append(f"\nHeadline: {art['title']}")
        lines.append(f"Source: {art.get('source', 'Unknown')}")
        tiers = art.get("source_tiers", [])
        if tiers:
            lines.append(f"Source Tiers: {', '.join(tiers)}")
        lines.append(
            f"Signal: {art.get('signal_strength', 'Single')} "
            f"({art.get('source_count', 1)} outlet(s))"
        )
        if art.get("cluster_match"):
            lines.append(f"Cluster: {art['cluster_match']}")
        if art.get("ripple_angle"):
            lines.append(f"Ripple Angle: {art['ripple_angle']}")
        if art.get("action_type") or art.get("suggested_action"):
            lines.append(
                f"Action: {art.get('action_type', 'read')} — {art.get('suggested_action', 'Review')}"
            )
        if art.get("description"):
            lines.append(f"Summary: {art['description'][:300]}")
        return lines

    if high:
        sections.append("\n=== HIGH PRIORITY ===")
        for art in high:
            sections.extend(render(art))

    if medium:
        sections.append("\n=== MEDIUM ===")
        for art in medium:
            sections.extend(render(art))

    if fyi:
        sections.append("\n=== FYI ===")
        for art in fyi:
            sections.extend(render(art))

    if tactics:
        sections.append("\n=== AI TOOLS AND TACTICS (candidates for STEAL THIS) ===")
        for art in tactics:
            sections.extend(render(art))

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
