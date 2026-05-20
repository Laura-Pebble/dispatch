"""Rank discovered items against this episode's curriculum lesson.

Gemini scores each candidate on (a) topic fit with the lesson, (b) technical
depth — does it teach a mechanic or just describe an outcome — and (c) brand-
building applicability for a B2B fCMO. Returns the top N items, where N is
config.target_sources_per_episode.
"""

import os
import json
import time
from typing import Optional

try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None


SCORING_PROMPT = """You are curating sources for one episode of a teaching podcast on AI for B2B marketing.

The listener is a 20-year marketing exec (Laura, fractional CMO) who is becoming an AI context engineer for the marketing space. She wants to know more than the average marketer using AI — actual mechanics, not surface takes.

THIS EPISODE'S LESSON
Topic: {lesson_topic}
Lesson #: {lesson_num}
Foundational arc (1-12)? {is_foundational}
Gaps to address: {gaps}
Hypothesis: {hypothesis}

CANDIDATE SOURCES (one per <SOURCE> block)
{sources_block}

For EACH source, score it 0-10 on each dimension:

- topic_fit: how directly does this source teach the lesson topic above? (10 = teaches the topic head-on; 0 = unrelated)
- technical_depth: does it explain a mechanic, define terms, give a worked example? (10 = teaches the "how"; 0 = vibes-only)
- brand_applicability: can a B2B fCMO use this insight in client brand work this quarter? (10 = directly usable; 0 = academic only)
- originality: is this an original source, or a rehash? Primary sources and practitioner-authored posts score higher than aggregator summaries. (10 = original; 0 = rehash)

Also assign:
- one_line_take: one sentence describing what THIS source uniquely teaches (no marketing-speak)
- skip_reason: if topic_fit + technical_depth combined are below 6, set this; otherwise null

Respond in JSON only, no markdown fences. The output array MUST be in the same order as the input. Schema:

[
  {{
    "id": <integer matching the SOURCE id>,
    "topic_fit": <0-10>,
    "technical_depth": <0-10>,
    "brand_applicability": <0-10>,
    "originality": <0-10>,
    "one_line_take": "<sentence>",
    "skip_reason": "<sentence or null>"
  }},
  ...
]"""


def _format_sources(items: list) -> str:
    """Render the candidate list for the scoring prompt."""
    blocks = []
    for i, it in enumerate(items):
        text_snippet = (it.get("full_text") or it.get("summary") or "")[:1500]
        blocks.append(
            f"<SOURCE id={i}>\n"
            f"Title: {it.get('title', '')}\n"
            f"Source: {it.get('source', '')} ({it.get('source_type', '')}, tier {it.get('source_tier', '')})\n"
            f"Author: {it.get('author', '')}\n"
            f"URL: {it.get('url', '')}\n"
            f"Text:\n{text_snippet}\n"
            f"</SOURCE>"
        )
    return "\n\n".join(blocks)


def curate(
    items: list,
    lesson: Optional[dict],
    target_count: int = 5,
) -> list:
    """Score + rank candidates; return the top `target_count`.

    Each returned item is the original dict with extra fields:
    `score` (composite), `score_breakdown`, `one_line_take`.

    If Gemini is unavailable or the lesson is missing, falls back to a simple
    tier-and-recency heuristic.
    """
    if not items:
        return []

    if genai is None or not os.environ.get("GEMINI_API_KEY"):
        return _fallback_rank(items, target_count)

    lesson = lesson or {}
    prompt = SCORING_PROMPT.format(
        lesson_topic=lesson.get("topic", "(no specific lesson — pick what teaches the most about AI for marketing)"),
        lesson_num=lesson.get("lesson_num", ""),
        is_foundational=lesson.get("is_foundational", False),
        gaps=lesson.get("gaps", "") or "(none specified)",
        hypothesis=lesson.get("hypothesis", "") or "(none specified)",
        sources_block=_format_sources(items),
    )

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        text = (response.text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        scored = json.loads(text.strip())
    except Exception as e:
        print(f"  Warning: curation scoring failed ({e}) — falling back to heuristic rank")
        return _fallback_rank(items, target_count)

    # Merge scores back onto items
    by_id = {s["id"]: s for s in scored if isinstance(s, dict) and "id" in s}
    enriched = []
    for i, it in enumerate(items):
        s = by_id.get(i, {})
        tf = s.get("topic_fit", 0)
        td = s.get("technical_depth", 0)
        ba = s.get("brand_applicability", 0)
        og = s.get("originality", 0)
        # Weighted composite — depth + fit dominate, originality and applicability tie-break.
        composite = (tf * 0.35) + (td * 0.35) + (ba * 0.15) + (og * 0.15)
        enriched.append({
            **it,
            "score": round(composite, 2),
            "score_breakdown": {"topic_fit": tf, "technical_depth": td, "brand_applicability": ba, "originality": og},
            "one_line_take": s.get("one_line_take", ""),
            "skip_reason": s.get("skip_reason"),
        })

    # Filter out items the model said to skip
    kept = [it for it in enriched if not it.get("skip_reason")]
    if not kept:
        # Model rejected everything — fall back so we don't ship an empty episode
        kept = enriched

    kept.sort(key=lambda x: x["score"], reverse=True)
    top = kept[:target_count]
    print(f"  Curated {len(top)} of {len(items)} candidates")
    for t in top:
        print(f"    [{t['score']:.1f}] {t['source']} — {t['title'][:80]}")
    return top


def _fallback_rank(items: list, target_count: int) -> list:
    """Tier + recency heuristic when Gemini isn't available."""
    tier_weight = {"Primary": 4, "Practitioner": 3, "Trade Press": 2, "Aggregator": 1, "Community": 2}
    for it in items:
        it["score"] = tier_weight.get(it.get("source_tier", ""), 1)
        it["one_line_take"] = ""
    items.sort(key=lambda x: (x["score"], x.get("date_published", "")), reverse=True)
    return items[:target_count]
