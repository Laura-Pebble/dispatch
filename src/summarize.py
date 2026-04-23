"""Stage 2: Generate the spoken brief from classified articles using Gemini.

Structure: 6 podcast segments + close. Articles are routed to segments by the
`podcast_segment` field set during classification (log_notion.py). Segments
with no qualifying articles are skipped — never padded.

Target length: 5-7 minutes total on an average news day; longer on big news
days, shorter when light.
"""

import os
from collections import defaultdict

from google import genai

from knowledge import load_ripple_context, load_watchlist, format_watchlist_for_prompt


# Per-segment soft length budgets (words on an average news day).
# These are guidance for the model, not hard caps. Big news days override.
SEGMENT_BUDGETS = {
    "content_news":       "180-240 words",
    "thought_leadership": "180-240 words",
    "landscape_shift":    "120-160 words",
    "release":            "100-140 words (~15s per item)",
    "adjacent_topic":     "60-90 words",
    "fun_fact":           "60-90 words",
}

SEGMENT_TITLES = {
    "content_news":       "CONTENT & AI",
    "thought_leadership": "THOUGHT LEADERSHIP",
    "landscape_shift":    "LANDSCAPE SHIFTS",
    "release":            "AI RELEASES",
    "adjacent_topic":     "ADJACENT TOPICS",
    "fun_fact":           "FUN FACTS",
}

# Ordered list — the brief follows this order
SEGMENT_ORDER = [
    "content_news",
    "thought_leadership",
    "landscape_shift",
    "release",
    "adjacent_topic",
    "fun_fact",
]


BRIEF_PROMPT = """You are Dispatch, Laura's strategic intelligence briefer.

<RIPPLE POSITIONING CONTEXT>
{ripple_context}
</RIPPLE POSITIONING CONTEXT>

<LAURA'S CURRENT WATCHLIST>
{formatted_watchlist}
</LAURA'S CURRENT WATCHLIST>

Today's articles, organized by Podcast Segment:

{articles_by_segment}

Write a spoken brief — target 5-7 minutes total on an average news day. Big news day → let depth dictate length (8-10 min OK). Quiet day → shorter is fine; never pad.

STRUCTURE — six segments + close, in this exact order. Skip any segment whose article list is empty.

1. CONTENT & AI ({budget_content_news})
   Commentary on articles about AI-generated content quality, B2B buyer behavior, or content craft. Connect to Pebble's positioning ("this validates / contradicts / extends our thesis on..."). Mention sources by name. Smooth narrative, not a list.

2. THOUGHT LEADERSHIP ({budget_thought_leadership})
   Deeper take on 1-2 flagship POV pieces. Surface quote-worthy phrases Laura could repurpose in her own writing. Identify the strongest argument, and the strongest counterargument if there is one.

3. LANDSCAPE SHIFTS ({budget_landscape_shift})
   Structural changes — AI cost economics, model pricing, platform consolidation, infrastructure moves. Always answer: "what does this mean for someone running an AI-powered fCMO practice at $1M-$15M ARR scale?"

4. AI RELEASES ({budget_release})
   Quick hits on new tools / models / capability drops. Lead each with the lab name + what changed. No commentary unless the release directly affects how Pebble operates.

5. ADJACENT TOPICS ({budget_adjacent_topic})
   Security, energy, regulation, broader concerns Laura tracks. One sentence per item. Frame as "worth tracking, not acting on today."

6. FUN FACTS ({budget_fun_fact})
   The cocktail-party material. The stuff that makes Laura sound smart at dinner. Just the fact + brief context. No analysis.

7. CLOSE (~30-50 words)
   1-2 specific actions Laura could take today, framed in her voice.

CROSS-SOURCE ROLLUP — factual only, never exaggerate. Use the Signal data provided per article:
  - source_count = 1 → don't mention other sources
  - source_count 2-3 → "and a couple of other outlets touched on this"
  - source_count 4+ AND tier_diversity >= 2 → "this was reported extensively — [lead source] had the most substantive take"
  - Cluster includes a Primary tier source + others → "[Lab name] announced it; [N] outlets covered it"
  - NEVER claim 'many sources' if it's just one. NEVER invent counts.

DELIVERY RULES:
- Plain spoken prose. No markdown, no bullet points, no segment headers spoken aloud — but DO label segments naturally in transitions ("On the content side today...", "One release worth noting...", "Quick fun fact...").
- Mention sources by name.
- Smooth transitions between segments.
- Don't say "good morning" or reference time of day.
- Start immediately with Segment 1's content.
- This is meant to be heard, not read."""


def generate_script(news_data: list, recap_length: str = "medium",
                    classified_articles: list = None) -> str:
    """Generate the spoken brief from classified articles.

    Args:
        news_data: Output from collect.collect_news() (used as fallback only).
        recap_length: Kept for backward compatibility — ignored in v2 (length
            is now driven by segment budgets + actual article volume).
        classified_articles: Output from log_to_notion() — articles with the
            `podcast_segment` and other classification fields.

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

    # Build per-segment article block (excludes db_only and missing-segment articles)
    if classified_articles:
        articles_by_segment = _format_by_segment(classified_articles)
    else:
        articles_by_segment = _format_articles(news_data)

    if not articles_by_segment.strip():
        return "No strategic signals today. Check back tomorrow."

    prompt = BRIEF_PROMPT.format(
        ripple_context=ripple_context,
        formatted_watchlist=formatted_watchlist,
        articles_by_segment=articles_by_segment,
        budget_content_news=SEGMENT_BUDGETS["content_news"],
        budget_thought_leadership=SEGMENT_BUDGETS["thought_leadership"],
        budget_landscape_shift=SEGMENT_BUDGETS["landscape_shift"],
        budget_release=SEGMENT_BUDGETS["release"],
        budget_adjacent_topic=SEGMENT_BUDGETS["adjacent_topic"],
        budget_fun_fact=SEGMENT_BUDGETS["fun_fact"],
    )

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        script = response.text.strip()
        print(f"  Generated brief ({len(script)} chars)")
        return script
    except Exception as e:
        print(f"  Error calling Gemini: {e}")
        print("  Falling back to headline list")
        return _fallback_script(news_data)


def _format_by_segment(classified_articles: list) -> str:
    """Group classified articles by podcast_segment, in podcast order.

    Skips db_only entirely (those articles log to Notion but don't speak).
    Also skips Dispose-relevance articles defensively (they should already
    be filtered by log_notion).
    """
    by_seg = defaultdict(list)
    for art in classified_articles:
        if art.get("relevance") == "Dispose":
            continue
        seg = art.get("podcast_segment") or "db_only"
        if seg == "db_only":
            continue
        by_seg[seg].append(art)

    if not by_seg:
        return ""

    sections = []
    for seg in SEGMENT_ORDER:
        items = by_seg.get(seg, [])
        if not items:
            continue
        sections.append(f"\n=== Segment: {SEGMENT_TITLES[seg]} ({len(items)} article(s)) ===")
        for art in items:
            sections.extend(_render_article(art))

    # Anything routed to a segment we don't recognize gets dumped at the end
    extras = [
        art for art in classified_articles
        if art.get("podcast_segment") not in SEGMENT_ORDER + ["db_only", None, ""]
        and art.get("relevance") != "Dispose"
    ]
    if extras:
        sections.append("\n=== Segment: UNCATEGORIZED (place at narrator's discretion) ===")
        for art in extras:
            sections.extend(_render_article(art))

    return "\n".join(sections)


def _render_article(art: dict) -> list:
    """Format a single article for the segment block of the prompt."""
    lines = []
    lines.append(f"\nHeadline: {art.get('title', '')}")
    lines.append(f"Source: {art.get('source', 'Unknown')}")
    tiers = art.get("source_tiers", [])
    if tiers:
        lines.append(f"Source Tiers: {', '.join(tiers)}")
    lines.append(
        f"Signal: {art.get('signal_strength', 'Single')} "
        f"({art.get('source_count', 1)} outlet(s))"
    )
    outlets = art.get("source_names") or []
    if outlets and len(outlets) > 1:
        lines.append(f"All outlets: {', '.join(outlets)}")
    if art.get("relevance"):
        lines.append(f"Relevance: {art['relevance']}")
    if art.get("cluster_match"):
        lines.append(f"Cluster: {art['cluster_match']}")
    if art.get("ripple_angle"):
        lines.append(f"Ripple Angle: {art['ripple_angle']}")
    if art.get("action_type") or art.get("suggested_action"):
        lines.append(
            f"Action: {art.get('action_type', 'read')} — "
            f"{art.get('suggested_action', 'Review')}"
        )
    if art.get("description"):
        lines.append(f"Summary: {art['description'][:300]}")
    return lines


def _format_articles(news_data: list) -> str:
    """Format raw news data when no classification is available (fallback)."""
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
    """Headline-list script when Gemini is unavailable."""
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
