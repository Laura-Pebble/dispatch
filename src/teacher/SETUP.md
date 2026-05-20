# Pebble Teacher — One-time Setup

Run through this once. Takes about 20 minutes.

## 1. Create four Notion databases

Create these as **regular databases** (not inline) in any page Laura's integration
has access to. Don't worry about field types — `notion_dbs.py` adds any missing
fields on the first run.

| DB | Title-field name |
|---|---|
| Teacher Curriculum | `Topic` |
| Teacher Sources | `Title` |
| Teacher Episodes | `Title` |
| Teacher Inbox | `Note` |

Share each one with the existing Notion integration (the same one Dispatch uses —
`NOTION_TOKEN` secret).

## 2. Copy the DB IDs into `config_teacher.yaml`

For each DB, open it in the browser, copy the 32-char ID from the URL (between
`/` and `?v=`), and paste under `notion:` in `config_teacher.yaml`:

```yaml
notion:
  curriculum_db_id: "abc123..."
  sources_db_id:    "def456..."
  episodes_db_id:   "ghi789..."
  inbox_db_id:      "jkl012..."
```

## 3. Seed the curriculum

```bash
NOTION_TOKEN=secret_... python src/teacher/seed_curriculum.py
```

This loads the 12 foundational lessons with planned dates starting next Monday.

## 4. Smoke test

```bash
NOTION_TOKEN=secret_... GEMINI_API_KEY=AIza... python src/teacher/smoke_test.py all
```

Should print `✓` on every stage.

## 5. Set up the Pebble Teacher Claude Project

In claude.ai:
1. New Project → "Pebble Teacher"
2. Add the Notion connector → grant it access to Laura's workspace (or just the
   Teacher Sources + Episodes + Curriculum DBs)
3. Set Project instructions: "Pebble Teacher episodes and sources live in the
   Teacher Sources, Teacher Episodes, and Teacher Curriculum Notion databases.
   When I ask about a topic we covered, search those databases and pull the
   relevant sources. Cite by author and episode number when you do."

Done. The Project will pick up new episodes automatically every Mon/Wed/Fri.

## 6. Add the workflow secrets

In the GitHub repo settings → Secrets → Actions, the Teacher workflow expects:

- `GEMINI_API_KEY` (already exists for Dispatch)
- `NOTION_TOKEN` (already exists for Dispatch)
- `PODCAST_BASE_URL` (already exists for Dispatch)
- `TEACHER_NTFY_TOPIC` (NEW — e.g. `laura-teacher`, separate from the Dispatch topic so notifications are distinguishable)

## 7. Set up the Slack inbox collector (scheduled Claude session)

The CI pipeline can't call the Slack MCP (it's a Claude tool, not a Python
library), so Slack content arrives via a **scheduled Claude Code on the Web
session** that runs unattended and writes Slack finds into the Teacher Inbox
Notion DB. The pipeline then reads from that DB during the Mon/Wed/Fri runs.

**No manual drops are required after this is set up.**

1. In claude.ai → Settings → Connectors, authorize the **Slack** connector
   against each of the 4 community workspaces Laura belongs to (Pavilion,
   RevGenius / Marketing AI Institute, AI GTM Support Group, Cybersecurity
   Marketing Society). Communities whose admins block third-party app installs
   will silently drop out — the session logs which ones.
2. In Claude Code on the Web → Recurring sessions → **New**:
   - Repository: `Laura-Pebble/dispatch`
   - Branch: `main`
   - Schedule: `Sun, Tue, Thu at 20:00 America/New_York` (so each pipeline
     run has fresh inbox content)
   - Prompt: paste the **Run Prompt** section from
     `src/teacher/inbox_collector_prompt.md` verbatim
3. Save. The session runs unattended. Each run prints a one-line summary
   like `Inbox collector: wrote 7 rows from Pavilion, AI GTM. Skipped: RevGenius (not authorized)`.

If a community Slack is permanently un-authorizable, the only loss is that
community's content stream — the pipeline still ships episodes from the
remaining sources.

## 8. (Optional) Add a Teacher cover image

If you have a square PNG cover (1400×1400 to 3000×3000) you want to use
instead of the Dispatch cover, save it as `static/teacher-cover.png`. If you
skip this step, the workflow automatically falls back to the Dispatch cover —
no action required.
