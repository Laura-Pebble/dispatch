# Dispatch v2 Upgrade — Claude Code Implementation Brief

## WORK ORDER — READ THIS FIRST

**Work through these tasks IN ORDER. Complete each task before starting the next.**

1. **Create files** — Drop the three files from Appendix A into the repo at the specified paths
2. **Upgrade classification** — Rewrite `src/log_notion.py` with the positioning-aware prompt
3. **Add theme deduplication** — Batch articles and cluster by theme before logging
4. **Update search queries** — Replace `config.yaml` search queries with positioning-level ones
5. **Upgrade podcast prompt** — Rewrite `src/summarize.py` to produce a strategic brief
6. **Add cleanup step** — Auto-archive stale articles in `src/main.py`
7. **Database cleanup** — One-time reclassification of existing articles in Notion
8. **(Optional) Weekly synthesis** — Friday summary step

**After completing each task:** Run the pipeline locally to verify nothing broke: `cd src && python main.py`

---

## Context

Dispatch is a daily news intelligence pipeline. GitHub Actions runs it at 7 AM ET: RSS feeds → Gemini web search → Gemini classification → Notion logging → TTS podcast → push notification.

**Problem:** Classification is generic ("is this about AI marketing?") instead of positioning-aware ("does this create an opportunity for Laura?"). Articles are topically correct but strategically dilute.

**This upgrade adds:**
1. A Ripple knowledge layer that informs classification and summarization
2. A Topic Clusters system in Notion for evolving market intelligence
3. Smarter output: action types, suggested actions, FYI tier, theme dedup, strategic podcast

---

## What Already Exists in Notion (Do NOT Rebuild)

### Topic Clusters Database
- **Database ID:** `4d7d6c1ee95a48c4ba3101ee952fc5c0`
- **Data source:** `collection://1f55bdd0-5ab7-473d-8cca-f7ebb1a8e618`
- **Seeded with 8 clusters**, each with Market Terms and Search Queries fields
- **Two-way relation** to Industry Intel articles database already wired

### Updated Articles Database Fields (already added)
- `Action Type` — select: read, comment, write-about, reach-out, share, track
- `Suggested Action` — rich text
- `Ripple Angle` — rich text
- `Relevance` — now includes FYI: HIGH, MEDIUM, FYI, LOW, Dispose
- `Topic Clusters` — relation to clusters database

---

## Task 1: Create Files

Create these three files in the repo. Contents are in **Appendix A** at the bottom of this document.

| File | Path | Purpose |
|------|------|---------|
| Ripple knowledge layer | `knowledge/ripple_context.md` | Positioning context loaded by classification + podcast prompts |
| Project instructions | `knowledge/dispatch_project_instructions.md` | Reference doc for Laura's Claude chat project (not used by pipeline) |
| Knowledge loader | `src/knowledge.py` | Helper to load ripple_context.md + fetch clusters from Notion |

For `src/knowledge.py`, create this module:

```python
"""Load Ripple positioning context and Topic Clusters from Notion."""

import os
from pathlib import Path


def load_ripple_context() -> str:
    """Load the static positioning knowledge layer."""
    path = Path(__file__).parent.parent / "knowledge" / "ripple_context.md"
    if path.exists():
        return path.read_text()
    print("  Warning: ripple_context.md not found, running without positioning context")
    return ""


def load_clusters(notion_client) -> list:
    """Fetch active Topic Clusters from Notion with their market terms and search queries.

    Returns list of dicts: [{"name": str, "market_terms": str, "search_queries": str, "page_id": str}]
    """
    DATABASE_ID = "4d7d6c1ee95a48c4ba3101ee952fc5c0"
    clusters = []
    try:
        has_more = True
        start_cursor = None
        while has_more:
            kwargs = {
                "database_id": DATABASE_ID,
                "page_size": 100,
                "filter": {"property": "Status", "select": {"equals": "Active"}}
            }
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            response = notion_client.databases.query(**kwargs)
            for page in response.get("results", []):
                props = page.get("properties", {})
                name_parts = props.get("Cluster", {}).get("title", [])
                name = name_parts[0]["text"]["content"] if name_parts else ""
                mt_parts = props.get("Market Terms", {}).get("rich_text", [])
                market_terms = mt_parts[0]["text"]["content"] if mt_parts else ""
                sq_parts = props.get("Search Queries", {}).get("rich_text", [])
                search_queries = sq_parts[0]["text"]["content"] if sq_parts else ""
                clusters.append({
                    "name": name,
                    "market_terms": market_terms,
                    "search_queries": search_queries,
                    "page_id": page["id"],
                })
            has_more = response.get("has_more", False)
            start_cursor = response.get("next_cursor")
    except Exception as e:
        print(f"  Warning: Could not fetch clusters: {e}")
    return clusters


def format_clusters_for_prompt(clusters: list) -> str:
    """Format cluster data for insertion into the classification prompt."""
    if not clusters:
        return "No clusters loaded."
    lines = []
    for c in clusters:
        lines.append(f"Cluster: {c['name']}")
        lines.append(f"  Market terms: {c['market_terms']}")
        lines.append("")
    return "\n".join(lines)
```

---

## Task 2: Upgrade Classification in `src/log_notion.py`

Replace the `CLASSIFY_PROMPT` and update `log_to_notion()` to:

1. Call `knowledge.load_ripple_context()` once at the start of the run
2. Call `knowledge.load_clusters(notion)` once at the start (cache the results)
3. Use this expanded classification prompt:

```
You are classifying a news article for Pebble Marketing's strategic intelligence system.

<POSITIONING CONTEXT>
{ripple_context}
</POSITIONING CONTEXT>

<ACTIVE TOPIC CLUSTERS>
{formatted_clusters}
</ACTIVE TOPIC CLUSTERS>

Article:
Title: {title}
Source: {source}
Summary: {description}
Topic area: {topic}

Classify this article against Pebble's POSITIONING — not just its topic.

Decision framework:
1. Does this create an opportunity for Laura to be in a conversation, create content, or reach a buyer? → HIGH
2. Could this affect Pebble's positioning in 3-6 months? → MEDIUM
3. Would someone running an AI-powered B2B marketing system look uninformed for NOT knowing this? (major model releases, platform changes, AI methodology shifts, significant industry events) → FYI
4. Is this general news with no Pebble angle? → LOW
5. Is this noise, vendor PR, or a rehash? → Dispose

For FYI articles: set action_type, suggested_action, ripple_angle, and cluster_match to null.
For HIGH and MEDIUM: all fields required.

Respond in JSON only, no markdown fences:
{{
  "category": one of ["Platform Update", "Competitor Move", "Thought Leadership", "Influencer Activity", "New Entrant", "Funding/Market"],
  "relevance": one of ["HIGH", "MEDIUM", "FYI", "LOW", "Dispose"],
  "tags": array from ["competitor", "content-opportunity", "sales-ammo", "methodology", "tool-update", "market-data"],
  "why_it_matters": "one sentence — strategic significance or null for Dispose",
  "action_type": one of ["read", "comment", "write-about", "reach-out", "share", "track"] or null,
  "suggested_action": "one-line recommended action with angle" or null,
  "ripple_angle": "how this connects to Pebble positioning" or null,
  "cluster_match": "exact cluster name from the list above" or "none" or "potential new cluster: [description]",
  "new_market_terms": ["terms from this article not already in the cluster's Market Terms"] or []
}}
```

4. After classification, write the new fields to Notion: Action Type, Suggested Action, Ripple Angle
5. Set the Topic Clusters relation on the article (match cluster_match to cluster page_id)
6. If new_market_terms is non-empty, append them to the cluster's Market Terms field
7. Update the cluster's Last Signal date to today

---

## Task 3: Theme-Level Deduplication

After collecting all articles (RSS + web search) but BEFORE logging to Notion:

1. URL dedup runs first (already exists — keep it)
2. Then batch all surviving articles and send to Gemini:

```
These articles were collected for a daily intelligence scan. Group them by theme.
For each theme group with multiple articles, identify the BEST source (most credible, most original reporting).
Mark duplicates.

Articles:
{list of title + source + description for each article}

Respond in JSON only:
[
  {
    "theme": "short theme description",
    "best_article_index": 0,
    "duplicate_indices": [1, 3],
    "reason": "why the best source was chosen"
  }
]
```

3. Log the best article per theme with full classification
4. Skip duplicates entirely (do not log them)

---

## Task 4: Update Search Queries in `config.yaml`

Replace the `search_queries` section:

```yaml
search_queries:
  # Narrative 1: Fragmentation
  - "B2B marketing chaos inconsistent messaging"
  - "marketing team misalignment brand 2026"
  # Narrative 2: AI Trap
  - "AI marketing trap generic content"
  - "synthetic content B2B quality"
  # Narrative 3: Confidence Gap
  - "marketing built on assumptions B2B"
  - "strategy execution gap marketing"
  # Narrative 4: Buyer Intelligence
  - "buyer persona problems B2B"
  - "AI buyer simulation marketing"
  # Narrative 5: Humans + AI
  - "AI copilot marketing human oversight"
  # Narrative 6: fCMO
  - "fractional CMO AI tools 2026"
  # Narrative 7: AEO
  - "AEO answer engine optimization brand"
  - "machine readable brand AI"
  # Counter-narrative
  - "vibe marketing criticism B2B"
  # Competitors
  - "fractional CMO AI new entrant"

search_max_results: 5
```

Also update `src/search_news.py` or `src/main.py` to fetch additional search queries from Active clusters at runtime (from the `Search Queries` field) and append them to the config queries.

---

## Task 5: Upgrade Podcast Prompt in `src/summarize.py`

Replace the prompt templates. Key changes:

1. Load `ripple_context.md` via `knowledge.load_ripple_context()`
2. Change persona from "friendly news briefing host" to "Laura's strategic intelligence briefer"
3. Structure the script as:
   - **Open:** Top strategic signal today and why it matters to Ripple (2-3 sentences)
   - **Strategic signals:** HIGH and MEDIUM articles grouped by cluster, with Ripple angle
   - **Platform radar:** FYI items, 1-2 sentences each, at the end
   - **Close:** One action Laura should take today
4. Skip LOW and Dispose articles entirely
5. The show name stays "Dispatch". The voice stays the same.

Pass the classification results (relevance, cluster, ripple_angle) into the summarize prompt so it doesn't have to reclassify. Add a parameter to `generate_script()` for the classified article data.

---

## Task 6: Add Cleanup Step to `src/main.py`

Add a `cleanup_stale_articles()` function that runs at the end of the pipeline:

1. Query Notion: Status = "To Review" AND Date Found older than 14 days → set Status = "Archived"
2. Query Notion: Relevance = "Dispose" AND Date Found older than 3 days → set Status = "Archived"
3. Query Notion: Relevance = "FYI" AND Date Found older than 30 days → set Status = "Archived"
4. **PROTECT** articles that have a Topic Clusters relation set (they're reference material)
5. Log: "Archived X stale articles"

---

## Task 7: One-Time Database Cleanup

Run once after the classification upgrade is working. Reclassify these existing articles:

**Set Relevance = FYI:**
- `33603ac6b3898127beabf8d5bec71f7b` — GPT-4o Fully Retired
- `33603ac6b389810f9111ddc513aa05b3` — Claude Mythos Model
- `33603ac6b38981f1ae21feef4510eb06` — Claude Code Source Leak — Proactive Mode
- `33603ac6b38981faa85beefd65d6a4c2` — Anthropic Retiring 1M Context Window Beta
- `33603ac6b38981c896a0ccb8e2c38674` — ChatGPT Enterprise Write Actions

**Set Status = Archived (duplicates):**
- `32903ac6b38981b9bc2ff729b745857b` — Vibe Marketing Goes Mainstream (dup of MarTech version)

**Set Status = Archived (generic roundups):**
- `33003ac6b38981b8a278c0cfb9b12844` — Top 10 B2B Marketing Trends
- `33203ac6b389811e97a8d769f5b6c11b` — Five B2B Marketing Trends (Think Boldly)
- `33203ac6b38981289710df6f8e672c6d` — Top 5 B2B Marketing Trends (Centerline)

**Set Relevance = Dispose:**
- `33603ac6b38981cd8533d65fb4c80d99` — Claude Operon — Life Sciences
- `33603ac6b38981cb971bf8f000d10442` — Greg Kihlström Named #1 Thought Leader

Then: run the remaining HIGH and MEDIUM articles through the new classification prompt to backfill Action Type, Suggested Action, Ripple Angle, and Topic Cluster assignments.

---

## Task 8: Weekly Synthesis (Optional)

If time permits, add a Friday synthesis step:

1. Fetch articles from past 7 days
2. Group by cluster, summarize signal volume per cluster
3. Flag momentum changes and potential new clusters
4. Output as Notion page: "Weekly Synthesis — [YYYY-MM-DD]"
5. Update cluster Signal Strength based on volume trends

---

## Notion Reference IDs

| Resource | ID |
|----------|-----|
| Industry Intel articles DB | `fe848ba99f874eefbd16d37cfb967cdc` |
| Articles data source | `collection://87bccaad-179e-46cb-b0a8-ca00db533612` |
| Topic Clusters DB | `4d7d6c1ee95a48c4ba3101ee952fc5c0` |
| Clusters data source | `collection://1f55bdd0-5ab7-473d-8cca-f7ebb1a8e618` |
| Asana content ideas project | `1209172840425620` |

---

## Appendix A: Files to Create

### File 1: `knowledge/ripple_context.md`

Create this file at `knowledge/ripple_context.md` with exactly this content:

~~~markdown
# Ripple Context — Dispatch Intelligence Filter

> This file is the **stable core** of Dispatch's knowledge layer.
> It contains Pebble's positioning, buyers, competitors, and scoring logic.
> This file changes only when the BMF changes.
>
> The **adaptive layer** — market vocabulary that evolves with the industry —
> lives in the Notion Topic Clusters database. The classification prompt reads
> from BOTH this file (for positioning) and the clusters (for market language).
>
> **Maintainer:** Laura McAliley
> **Last updated:** 2026-04-04
> **Source of truth:** BMF v3.0 (LOCKED 2026-03-27), ICP v3.0 (LOCKED), CLM v3.0

---

## Who We Are

Pebble Marketing is a fractional CMO practice serving B2B tech companies
($1M–$15M revenue). We build brand foundations that are clear for human teams
and structured for AI tools — research, strategy, and messaging delivered in
weeks, not months.

The system powering this is **RippleOS** (internal) / **The Ripple Method**
(client-facing). It coordinates multiple AI platforms with human oversight:
Claude builds strategy, ChatGPT evaluates quality and simulates buyers, Gemini
executes research. No platform tests its own output.

We are NOT an AI company. We are a new kind of fCMO shop that uses AI to
deliver deeper research and structured output at a price point the
startup/scaleup market can actually afford.

---

## What Problem We Solve

**The fragmentation problem.** Companies at our tier have marketing that tells
three different stories — the website says one thing, the sales team says
another, the CEO pitches a third. Agency output drifts. AI tools generate
generic content because inputs are vague. Everyone is guessing.

**Validated buyer language for this problem:**
- "Same company, three different stories."
- "Our marketing isn't working."
- "Everyone's guessing."
- "We've outgrown what we built."

---

## What Makes Ripple Different

### 1. Clear for Your Team. Structured for AI Tools.
One strategy your team, partners, and AI tools can execute from. The output is
designed for dual consumption — humans read it, AI tools produce on-brand
content from it. Most competitors deliver a deck designed for a human to read.

### 2. Informed Confidence
We tell you how confident you should be in your strategy before you spend
against it. Confidence tags on findings (Proven / Pattern / Needs Testing).
Pebble Buyer Models pressure-test messaging before it goes live.

### 3. Your Strategy Stays Current (expansion-stage only)
Monthly retainer keeps the foundation evolving as the market moves. NOT a
first-touch message.

---

## Our Buyers

### Jake — SaaS Founder / CEO ($2M–$8M ARR)
- Built the company, often did early marketing himself
- Knows something is off but can't articulate what
- Time-starved, skeptical of consultants, needs fast proof
- Decision driver: "Will this actually get used or sit in a drawer?"
- Cold content must be SHORT — dense methodology copy loses him

### Morgan — First Marketing Hire
- Inherited a mess, trying to build structure from scratch
- Needs the playbook the company never had
- Wants to look competent to the founder, afraid of expensive mistakes
- Decision driver: "Will this make my job possible?"

---

## Our Market Position

**Tier:** Done-for-you brand foundation for $1M–$15M B2B tech companies
**Entry point:** $2,500 positioning audit (2-3 weeks)
**Retainer:** ~$5K/mo fractional CMO

**Above us:** brand.ai (Fortune 500, enterprise pricing), big consulting firms
**Below us:** Vibe Marketer ($199 DIY), generic AI tools, template-based agencies
**Adjacent:** Other fCMOs (no structured research or AI-native output),
positioning consultancies (interview-based, no AI layer, higher price)

**Competitive gap we own:** Nobody at our tier does evidence-based buyer models +
confidence tagging + AI-structured output.

---

## Narratives and Market Language

These are the conversations Laura should be in. Each narrative has TWO layers:
- **Ripple's framing** — how we talk about this internally
- **Market language** — how the industry actually discusses it (use these for search queries and classification)

The market language below is the **seed vocabulary**. The Topic Clusters database
in Notion accumulates new terms as they appear in articles. The classification
prompt should check BOTH this file and the clusters for current vocabulary.

### 1. Marketing Fragmentation at the Growth Stage

**Ripple framing:** Companies outgrowing scrappy marketing. Agency output drifting.
AI amplifying bad inputs. Everyone telling a different story.

**Market language (seed):**
- "marketing chaos" / "chaotic environment"
- "inconsistent messaging" / "inconsistent brand voice"
- "misaligned teams" / "disconnected marketing function"
- "brand dilution" / "brands being diluted"
- "unclear vendor messaging"
- "random acts of marketing"
- "different value propositions across channels"
- "fragmentation" (this term IS used — tmp's "Cost of Chaos" report uses it)
- "stalled deals from misalignment"

### 2. AI Making Bad Marketing Worse

**Ripple framing:** AI tools are only as good as their inputs. Garbage strategy
in = garbage content out at scale. AI without strategy is noise.

**Market language (seed):**
- "AI trap" / "how NOT to use AI in marketing"
- "generic AI content" / "generic messaging from automation"
- "synthetic content" flooding channels
- "AI sameness" / "world saturated with sameness"
- "AI slop" / "mass-produced AI copy"
- "AI performance depends on data quality" / "building on sand"
- "automation destroying channels"
- "95% of outbound gets zero engagement"
- "prompt-and-pray marketing"

### 3. The Confidence Gap

**Ripple framing:** Marketers spending against unvalidated assumptions. Nobody
tells you what they're sure of vs. what's a bet. Programs built on guesses.

**Market language (seed):**
- "assumed buyer behavior" / "not verified intelligence"
- "strategy-execution gap"
- "programs built on assumptions"
- "unverified marketing decisions"
- "marketing measurement" / "proving marketing ROI"
- "data-driven decisions" (overused but signals the conversation)
- "83% say strategy matters but only 38% execute well"

### 4. Buyer Research Beyond Personas

**Ripple framing:** Traditional personas are fiction. Evidence-based buyer models
that simulate real decision-making are the next step.

**Market language (seed):**
- "buyer intelligence" / "buyer behavior research"
- "buying committee behavior" / "decision-making research"
- "intent data quality"
- "buyer personas don't work" / "personas are fiction"
- "AI buyer simulation" / "synthetic respondents"
- "audience intelligence"

### 5. The Humans + AI Operating Model

**Ripple framing:** Not AI replacing humans, not humans ignoring AI. Structured
collaboration with quality gates. Human strategy, AI execution.

**Market language (seed):**
- "AI co-pilot not autopilot"
- "human oversight AI" / "human-in-the-loop"
- "AI with guardrails"
- "AI augmenting not replacing marketers"
- "the AI + human question"
- "AI won't replace marketers"

### 6. Fractional CMO Evolution

**Ripple framing:** The fCMO role is changing. AI-native fCMOs can deliver
enterprise-grade work at startup prices. The model is being reinvented.

**Market language (seed):**
- "fractional CMO AI" / "fractional CMO tools"
- "outsourced marketing leadership"
- "part-time CMO"
- "fractional executive" / "fractional C-suite"
- "marketing leadership gap" at startups/scaleups
- "fCMO faster with AI"

### 7. Brand Foundations That AI Tools Can Consume

**Ripple framing:** The shift from "brand guidelines PDF" to structured,
machine-readable brand intelligence. Strategy designed for dual consumption.

**Market language (seed):**
- "AEO" (Answer Engine Optimization)
- "AI-ready brand" / "AI-ready positioning"
- "machine-readable brand" / "machine-readable brand intelligence"
- "positioning for AI search" / "brand for LLMs"
- "AI search visibility" / "AI-powered search brand mentions"
- "clear positioning for AI engines"
- "brand guidelines for AI tools"

---

## Competitors and Adjacent Players to Watch

### Direct Competitors (fCMO / positioning consultancies)
- April Dunford / Ambient Strategy
- Fletch PMM
- House of Revenue
- Kalungi (B2B SaaS marketing)
- Fractional CMO firms launching AI capabilities

### Adjacent / Upstream
- brand.ai (machine-readable brand intelligence, enterprise)
- Jasper, Writer, Copy.ai (AI content platforms)
- HubSpot, Salesforce (marketing platform AI features)

### Methodology Competitors
- "Vibe marketing" movement (opposite of evidence-based — Laura's counterpoint)
- Template-based positioning (StoryBrand, etc.)

### Thought Leaders to Track
- April Dunford (positioning methodology)
- Scott Brinker (martech landscape)
- Marketing AI Institute / Paul Roetzer
- John Winsor (HBR, future of marketing work)
- Anyone writing about fCMO + AI intersection

---

## Relevance Scoring Guide

### HIGH — Laura should act on this today
- Directly validates or challenges one of the 7 narratives above
- Uses language from the narrative's market terms (or new language for the same concept)
- A tracked competitor makes a visible move
- A buyer-type (Jake or Morgan) is quoted describing the fragmentation problem
- A new tool or platform intersects with Ripple's delivery model
- A thought leader says something Laura should respond to publicly
- Evidence the market is moving toward (or away from) what Pebble offers

### MEDIUM — Worth knowing, might become a pattern
- General AI + marketing trends that could affect positioning in 3-6 months
- Market data or research reports relevant to the $1M-$15M tier
- Adjacent competitor moves (not direct, but market-shaping)
- Platform updates to tools Ripple depends on (Claude, ChatGPT, Gemini, Notion, Asana)

### FYI — Practitioner awareness (no positioning angle, but Laura should know)
- Major AI model releases, platform retirements, significant capability changes
- AI methodology shifts, MCP developments, new research techniques
- Industry events or milestones that anyone running an AI-powered system should know
- The test: would someone in Laura's position look uninformed for NOT knowing this?
- FYI articles get NO action type, NO suggested action, NO ripple angle, NO cluster

### LOW — Background noise, archive
- General AI news without marketing application
- Enterprise-only trends ($100M+ companies)
- Consumer marketing trends
- Tool updates for platforms Pebble doesn't use
- Market data without a Pebble angle

### DISPOSE — Skip entirely
- Rehashed trend pieces with no new data
- Vendor press releases disguised as news
- Listicles / roundups without original reporting
- Anything older than 7 days with no strategic significance
- Same theme already surfaced this week (cluster, don't duplicate)

---

## Action Type Guide

For every HIGH and MEDIUM article, classify the recommended action:

| Action | When to Use | Example |
|--------|-------------|---------|
| **read** | Laura needs to absorb this to stay current | New research report with data she'll cite |
| **comment** | Article or post where Laura's perspective adds value | Blog post about AI replacing strategists — Laura's angle: "AI without strategy is noise at scale" |
| **write-about** | Signal triggers a content opportunity | Competitor launches something; Laura writes about what's missing |
| **reach-out** | Person or company Laura should connect with | Someone publishes about the exact problem Pebble solves |
| **share** | Worth amplifying without original commentary | Industry data that validates Pebble's thesis |
| **track** | Not actionable today but part of an emerging pattern | Third article this month about fCMOs adopting AI |

---

## What NOT to Surface

- Generic "AI will transform marketing" pieces with no specifics
- The same trend repackaged by different outlets (cluster it, surface once)
- Anything that's just a vendor promoting their own product
- News about AI companies with no marketing application
- Content older than 7 days unless it's a major research report
~~~

### File 2: `knowledge/dispatch_project_instructions.md`

Create this file at `knowledge/dispatch_project_instructions.md` with exactly this content:

~~~markdown
# Dispatch Intelligence — Project Instructions

> NOTE: This file is NOT used by the Dispatch pipeline. It is reference material
> for a Claude Project on claude.ai where Laura does her morning voice chats.
> She will copy-paste these as project instructions and upload ripple_context.md
> as the knowledge file.

You are Laura's daily strategic intelligence partner. You help her act on the
signals that Dispatch (her automated news pipeline) surfaces each morning.

## Your Role

You are NOT a news scanner. Dispatch already scanned the web, classified
articles, assigned them to topic clusters, and logged everything to Notion
before Laura opens this conversation. Your job is to help her decide what to
act on and how.

Specifically:
- Lead each session with 3-5 hot takes from today's Dispatch brief
- A "hot take" is something surprising, counterintuitive, directly relevant to
  client work, or likely to shift how people think about marketing
- For each signal, explain the Ripple angle — why this matters to Pebble
- When Laura asks "what should I do with this," suggest a specific action
- When she wants to act, help her draft: comment angles, LinkedIn post hooks,
  blog outlines, outreach messages
- Connect today's signals to patterns across previous days and weeks
- Be honest about signal quality

## What You Know

The knowledge file contains Pebble's three pillars, buyer profiles (Jake and
Morgan), competitive landscape, seven core narratives mapped to market language,
and relevance scoring guidelines.

## What You Can Access

- Notion MCP — Industry Intel articles database and Topic Clusters database
- Knowledge file — Pebble's positioning context (loaded automatically)

## How to Behave

- Be conversational, not formal. Morning coffee chat, not briefing deck.
- Be selective. 3-5 signals that matter > 15 that don't.
- Always list sources and links.
- DO NOT hallucinate or fabricate news, headlines, stories, or statistics.
- Respect Pebble's operating rules: AI is how we deliver not what we are,
  partner not critic tone, buyer language leads, no absolutes about competitors.
- Consider copyright. Laura doesn't take other people's work as her own.

## Session Flow

**Morning opener:** Check Notion for today's articles → lead with hot takes
**Deep dive:** Help develop Laura's angle → draft content for the action type
**Weekly synthesis (Fridays):** Cluster analysis → momentum changes → content gaps

## Key Reference IDs

- Articles database: `fe848ba99f874eefbd16d37cfb967cdc`
- Topic Clusters database: `4d7d6c1ee95a48c4ba3101ee952fc5c0`
- Articles data source: `collection://87bccaad-179e-46cb-b0a8-ca00db533612`
- Clusters data source: `collection://1f55bdd0-5ab7-473d-8cca-f7ebb1a8e618`
- Asana content ideas: `1209172840425620`
~~~
