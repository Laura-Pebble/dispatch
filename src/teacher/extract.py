"""Deep-extract each curated source and write a Notion page in Teacher Sources.

For every curated item we ask Gemini to produce:
  - 3-6 key claims (bullets with verbatim phrasing where useful)
  - 1-2 direct quotes (verbatim, with the quoted phrase)
  - a brand-building implication paragraph specific to B2B fCMO work

The page then becomes a first-class source that the Pebble Teacher Claude
Project can query via the Notion connector. We return the list with each
item enriched with `notion_page_id` for the lesson_script and publish stages.
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional

try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None


EXTRACT_PROMPT = """Extract teaching material from this source for an AI-for-marketing podcast.

LESSON CONTEXT
Topic: {lesson_topic}
Audience: a fractional CMO who is becoming an AI context engineer. Has 20 years of marketing experience and 2026-level AI familiarity. Wants to know how things work, not just that they exist.

SOURCE
Title: {title}
Author: {author}
Source: {source} ({source_type}, tier {source_tier})
URL: {url}

CONTENT
{content}

Produce JSON in this exact shape — no markdown fences:

{{
  "key_claims": [
    "claim 1 — phrased crisply, include numbers and named entities when the source provides them",
    "claim 2",
    "claim 3"
  ],
  "quotes": [
    {{"text": "the verbatim quote", "context": "what the author is talking about here"}}
  ],
  "brand_implication": "one paragraph (3-5 sentences) on how this maps to building a B2B brand under $15M ARR. Be specific — what tactic, what artifact, what conversation does this unlock or close off?",
  "mechanic_summary": "if the source explains a mechanic (how an AI feature, model behavior, or technique actually works), summarize it in 2-3 sentences. If the source is opinion/narrative only, return empty string."
}}

RULES
- Return 3-6 key_claims, each one sentence, and reflecting what's actually in the source. Do not invent.
- Return 1-2 quotes. If the content is paraphrased (no clean quotables), return [].
- Brand_implication must be concrete. No "leverages synergies" or "future of marketing" generalities."""


def extract_and_log_sources(
    notion,
    sources_db_id: str,
    intel_db_id: str,
    curated: list,
    lesson_topic: str,
) -> list:
    """Run Gemini extraction per source, write a page to Teacher Sources,
    optionally mirror a row to Industry Intel for trend analysis.

    Returns curated with `notion_page_id` field set on each item that was logged.
    """
    if not curated:
        return []

    if genai is None or not os.environ.get("GEMINI_API_KEY"):
        print("  Warning: GEMINI_API_KEY not set — sources will be logged without extraction")
        client = None
    else:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    enriched = []
    for item in curated:
        extracted = _extract_one(client, item, lesson_topic) if client else {}
        item = {**item, **extracted}

        # Write to Teacher Sources
        page_id = _write_source_page(notion, sources_db_id, item)
        item["notion_page_id"] = page_id

        # Mirror lightweight row to Industry Intel for cross-pipeline trend analysis
        if intel_db_id and page_id:
            _mirror_to_intel(notion, intel_db_id, item)

        enriched.append(item)

    return enriched


def _extract_one(client, item: dict, lesson_topic: str) -> dict:
    """Single-source extraction call."""
    content = (item.get("full_text") or item.get("summary") or "")[:15000]
    if not content:
        return {"key_claims": [], "quotes": [], "brand_implication": "", "mechanic_summary": ""}

    prompt = EXTRACT_PROMPT.format(
        lesson_topic=lesson_topic or "(open — pick what teaches the most about AI for marketing)",
        title=item.get("title", ""),
        author=item.get("author", ""),
        source=item.get("source", ""),
        source_type=item.get("source_type", ""),
        source_tier=item.get("source_tier", ""),
        url=item.get("url", ""),
        content=content,
    )
    try:
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text = (resp.text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        data = json.loads(text.strip())
        if not isinstance(data, dict):
            raise ValueError("extraction response was not a JSON object")
        return {
            "key_claims": data.get("key_claims", []) or [],
            "quotes": data.get("quotes", []) or [],
            "brand_implication": data.get("brand_implication", "") or "",
            "mechanic_summary": data.get("mechanic_summary", "") or "",
        }
    except Exception as e:
        print(f"    extract failed for {item.get('title', '')[:60]}: {e}")
        return {"key_claims": [], "quotes": [], "brand_implication": "", "mechanic_summary": ""}


def _bullets(items: list) -> str:
    """Render a list of strings as a Notion-friendly bulleted block in rich_text."""
    if not items:
        return ""
    return "\n".join(f"• {str(x)[:500]}" for x in items if x)


def _quotes_to_text(quotes: list) -> str:
    lines = []
    for q in quotes or []:
        if isinstance(q, dict):
            txt = q.get("text", "")
            ctx = q.get("context", "")
            if txt:
                lines.append(f"“{txt}” — {ctx}" if ctx else f"“{txt}”")
        elif isinstance(q, str):
            lines.append(f"“{q}”")
    return "\n\n".join(lines)


def _write_source_page(notion, db_id: str, item: dict) -> Optional[str]:
    """Create a Teacher Sources page; return its page_id or None."""
    if not db_id:
        return None
    try:
        title = item.get("title", "(untitled)")[:200]
        props = {
            "Title": {"title": [{"text": {"content": title}}]},
            "URL": {"url": item.get("url") or None},
            "Author": {"rich_text": [{"text": {"content": (item.get("author") or "")[:1500]}}]},
            "Source Type": {"select": {"name": _allowed_source_type(item.get("source_type", "Blog"))}},
            "Source Tier": {"select": {"name": _allowed_source_tier(item.get("source_tier", "Trade Press"))}},
            "Date Captured": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
        }
        if item.get("date_published"):
            props["Date Published"] = {"date": {"start": item["date_published"][:10]}}

        claims_text = _bullets(item.get("key_claims", []))
        if claims_text:
            props["Key Claims"] = {"rich_text": [{"text": {"content": claims_text[:1990]}}]}
        quotes_text = _quotes_to_text(item.get("quotes", []))
        if quotes_text:
            props["Quotes"] = {"rich_text": [{"text": {"content": quotes_text[:1990]}}]}
        impl = item.get("brand_implication", "")
        if impl:
            props["Brand-Building Implication"] = {"rich_text": [{"text": {"content": impl[:1990]}}]}

        # Page body: store the mechanic_summary + the full_text excerpt so the
        # Claude Project can quote from the body when asked.
        children = []
        if item.get("mechanic_summary"):
            children.append(_paragraph_block(f"How it works: {item['mechanic_summary']}"))
        excerpt = (item.get("full_text") or item.get("summary") or "")[:1900]
        if excerpt:
            children.append(_paragraph_block(f"Source excerpt:\n{excerpt}"))

        page = notion.pages.create(
            parent={"database_id": db_id},
            properties=props,
            children=children or None,
        )
        page_id = page.get("id")
        print(f"    [Sources] +{title[:60]}")
        return page_id
    except Exception as e:
        print(f"    [Sources] write failed: {e}")
        return None


def _mirror_to_intel(notion, intel_db_id: str, item: dict):
    """Best-effort mirror — Industry Intel has Dispatch's schema, not the Teacher's.

    We map only the overlapping fields so the row shows up in trend analysis
    without choking on missing options. Schema mismatch is non-fatal.
    """
    try:
        props = {
            "Title": {"title": [{"text": {"content": item.get("title", "(untitled)")[:200]}}]},
            "Source": {"rich_text": [{"text": {"content": (item.get("source") or "")[:200]}}]},
            "URL": {"url": item.get("url") or None},
            "Date Found": {"date": {"start": datetime.now(timezone.utc).strftime("%Y-%m-%d")}},
            "Status": {"select": {"name": "To Review"}},
        }
        notion.pages.create(parent={"database_id": intel_db_id}, properties=props)
    except Exception:
        # Industry Intel schema may not match — silently skip rather than fail the run.
        pass


def _paragraph_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text[:1990]}}]},
    }


_ALLOWED_TYPES = {"Blog", "Podcast", "X", "Newsletter", "Slack", "Doc", "Inbox"}
_ALLOWED_TIERS = {"Primary", "Practitioner", "Trade Press", "Aggregator", "Community"}


def _allowed_source_type(t: str) -> str:
    return t if t in _ALLOWED_TYPES else "Blog"


def _allowed_source_tier(t: str) -> str:
    return t if t in _ALLOWED_TIERS else "Trade Press"
