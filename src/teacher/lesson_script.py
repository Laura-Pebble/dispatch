"""Generate the 20-30 minute teaching script for one Teacher episode.

This is the core IP of the pipeline. The prompt enforces:
  - assume listener has 20 years of marketing experience + 2026 AI familiarity
  - teach the mechanic, define every term on first use, one worked example each
  - explicit ban on "AI is revolutionizing" / "future of marketing" filler
  - source citations woven in naturally
  - 4-act structure: hook → mechanics → application → "try this week"

Returns the spoken script (TTS-ready, no markdown) plus 5 follow-up prompts
the Claude Project will pre-suggest to Laura for deeper conversation.
"""

import os
import json
from pathlib import Path

try:
    from google import genai
except ImportError:  # pragma: no cover
    genai = None

# Reuse Dispatch's positioning context loader so the Teacher inherits Ripple voice
import sys
_SRC = Path(__file__).resolve().parent.parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from knowledge import load_ripple_context  # noqa: E402


LESSON_PROMPT = """You are writing one episode of "Pebble Teacher," a 3-times-a-week teaching podcast for Laura — a fractional CMO at Pebble Marketing with 20 years of B2B marketing experience who is becoming an AI context engineer for the marketing space.

She has 2026-level AI familiarity but no engineering background. She does not need motivation; she needs mechanics. She wants to know more than the average marketer using AI.

<PEBBLE POSITIONING CONTEXT>
{ripple_context}
</PEBBLE POSITIONING CONTEXT>

<TODAY'S LESSON>
Lesson #: {lesson_num}
Topic: {lesson_topic}
Foundational arc? {is_foundational}
Word budget: {word_min}-{word_max} words (≈ {min_min}-{max_min} minutes when spoken)
Gaps to address (from curriculum): {gaps}
Curriculum hypothesis: {hypothesis}
</TODAY'S LESSON>

<CURATED SOURCES — use these as the factual backbone>
{sources_block}
</CURATED SOURCES>

WRITE A SPOKEN SCRIPT. Four acts, in this order. Plain prose. No markdown, no headers spoken aloud, no bullet lists.

ACT 1 — HOOK (≈ 200-300 words)
Open with a concrete moment from one of the sources — a finding, a quote, a feature drop. Name the source. State the question this episode answers. Tell Laura why she'll be glad she listened.

ACT 2 — MECHANICS (≈ {mech_min}-{mech_max} words, the bulk of the episode)
Teach the topic. For each concept you introduce:
  - Define every term on first use ("Context engineering means…")
  - Explain the mechanic — how it actually works, not just what it does
  - Give ONE worked example with specifics (real numbers, real prompts, real tools)
  - Cite the source by name when you use its claim or example
Cover 3-4 connected sub-concepts. Walk through each — do not survey.

ACT 3 — APPLICATION (≈ 400-600 words)
Pivot to: "Here's what this means for the brand work you do every day." Connect to Pebble's positioning. Give 2-3 specific, named applications: a brand artifact, a client conversation, a prompt pattern, a decision rule. Anchor each to a buyer Pebble serves (B2B tech, $1M-$15M ARR, fractional CMO context).

ACT 4 — TRY THIS WEEK (≈ 200-300 words)
One concrete thing Laura can do before the next episode. A test, an experiment, a small artifact she can build. End with the source roll-call: "Today's sources were [name], [name], [name]."

CITATION RULES
- Every factual claim ties to a source by name. "Simon Willison wrote that…" / "In a recent post, Ethan Mollick argued…" / "Anthropic's announcement said…"
- If two sources agree, name both ("Mollick and Willison both flagged…"). If they disagree, surface the disagreement.
- Never claim consensus when there's only one source.

FORBIDDEN PHRASES (if you write any of these, you've failed the episode)
- "AI is revolutionizing…" / "the future of marketing…" / "leverage AI to…" / "in today's landscape…" / "unlock the power of…"
- "Welcome back" / "in this episode, we'll explore" / "let's dive in"
- Generic platitudes about change. Be specific.

VOICE
- Conversational, not academic. Spoken, not written. Contractions OK.
- No "good morning" or time-of-day greetings.
- Start mid-thought with the hook from Act 1 — do NOT preface with show title or intro music cue.
- Total length MUST land between {word_min} and {word_max} words.

After the spoken script, on a new line, write exactly the marker:
===FOLLOW_UP_PROMPTS===

Then return a JSON array of exactly 5 follow-up prompts Laura could ask the Pebble Teacher Claude Project to go deeper. Each prompt should reference something specific from this episode and be phrased as Laura would phrase it ("walk me through…", "what would change if…", "how would you apply this to…"). Example shape:

["walk me through how RAG embeddings differ from fine-tuning for brand voice — using the Mollick example we covered today",
 "what would change about my CMS structure if I implemented machine-readable brand assets at the level Anthropic described?",
 ...]
"""


def _format_sources(curated: list) -> str:
    blocks = []
    for i, s in enumerate(curated, start=1):
        claims = s.get("key_claims") or []
        claims_text = "\n  - " + "\n  - ".join(c[:250] for c in claims) if claims else ""
        quotes = s.get("quotes") or []
        quotes_text = ""
        if quotes:
            qlines = []
            for q in quotes[:2]:
                if isinstance(q, dict) and q.get("text"):
                    qlines.append(f'  - "{q["text"][:250]}"')
            quotes_text = ("\n" + "\n".join(qlines)) if qlines else ""
        mech = s.get("mechanic_summary", "")
        impl = s.get("brand_implication", "")
        blocks.append(
            f"SOURCE {i}: {s.get('title', '')}\n"
            f"  Author: {s.get('author', '')}\n"
            f"  Source: {s.get('source', '')} ({s.get('source_type', '')}, tier {s.get('source_tier', '')})\n"
            f"  URL: {s.get('url', '')}\n"
            f"  One-line take: {s.get('one_line_take', '')}\n"
            f"  Key claims:{claims_text}\n"
            f"  Quotes:{quotes_text}\n"
            f"  Mechanic: {mech[:500]}\n"
            f"  Brand implication: {impl[:500]}"
        )
    return "\n\n".join(blocks)


def generate_lesson_script(
    lesson: dict,
    curated: list,
    word_budget: tuple,
) -> tuple:
    """Return (script_text, follow_up_prompts_list).

    Falls back to a minimal placeholder if Gemini is unavailable.
    """
    word_min, word_max = word_budget
    min_min, max_min = round(word_min / 150), round(word_max / 150)
    mech_min = max(800, int(word_min * 0.50))
    mech_max = max(mech_min + 200, int(word_max * 0.55))

    if not curated:
        return _fallback_script(lesson, word_budget), []

    if genai is None or not os.environ.get("GEMINI_API_KEY"):
        print("  Warning: GEMINI_API_KEY missing — using fallback script")
        return _fallback_script(lesson, word_budget), []

    lesson = lesson or {}
    prompt = LESSON_PROMPT.format(
        ripple_context=load_ripple_context(),
        lesson_num=lesson.get("lesson_num", "(unscheduled)"),
        lesson_topic=lesson.get("topic", "(open — synthesize what the sources teach about AI for marketing)"),
        is_foundational=lesson.get("is_foundational", False),
        word_min=word_min,
        word_max=word_max,
        min_min=min_min,
        max_min=max_min,
        gaps=lesson.get("gaps", "") or "(none)",
        hypothesis=lesson.get("hypothesis", "") or "(none)",
        sources_block=_format_sources(curated),
        mech_min=mech_min,
        mech_max=mech_max,
    )

    try:
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        # gemini-2.5-pro for the long-form lesson — better at sustained
        # reasoning + word-budget adherence than 2.5-flash.
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        raw = (response.text or "").strip()
    except Exception as e:
        print(f"  Lesson generation failed with Pro ({e}) — retrying on Flash")
        try:
            client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            raw = (response.text or "").strip()
        except Exception as e2:
            print(f"  Lesson generation failed on Flash too ({e2}) — falling back")
            return _fallback_script(lesson, word_budget), []

    script, prompts = _split_script_and_prompts(raw)
    word_count = len(script.split())
    print(f"  Lesson script: {word_count} words (target {word_min}-{word_max})")
    if word_count < word_min * 0.75:
        print(f"  Warning: script is below target — model returned a short version")
    return script, prompts


def _split_script_and_prompts(raw: str):
    marker = "===FOLLOW_UP_PROMPTS==="
    if marker in raw:
        script_part, prompts_part = raw.split(marker, 1)
        prompts_part = prompts_part.strip()
        if prompts_part.startswith("```"):
            prompts_part = prompts_part.split("\n", 1)[1] if "\n" in prompts_part else prompts_part[3:]
        if prompts_part.endswith("```"):
            prompts_part = prompts_part[:-3]
        try:
            prompts = json.loads(prompts_part.strip())
            if not isinstance(prompts, list):
                prompts = []
        except Exception:
            prompts = []
        return script_part.strip(), prompts[:5]
    return raw, []


def _fallback_script(lesson: dict, word_budget: tuple) -> str:
    topic = (lesson or {}).get("topic") or "AI for marketing"
    return (
        f"Today's lesson on {topic} couldn't be generated automatically — the script "
        f"generator was unavailable. Please re-run the pipeline once Gemini access is "
        f"restored. In the meantime, the curated sources for this episode are logged "
        f"to your Teacher Sources database in Notion."
    )
