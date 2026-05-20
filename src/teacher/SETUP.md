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

## 7. (Optional) Add a Teacher cover image

Drop `static/teacher-cover.png` (1400×1400 to 3000×3000, square PNG). The
workflow falls back to the Dispatch cover if there isn't one.

## Manual workflow: Slack & ad-hoc sources

The Teacher pipeline does NOT crawl Slack workspaces in CI (community Slacks
generally don't allow bots, and the MCP-based Slack tools available to Claude
are not callable from a Python script). Instead:

- When you see a notable Slack thread, link, or idea during the week, add a row
  to the **Teacher Inbox** DB with the URL and a one-line `Note`.
- On the next run, the pipeline reads "New" inbox rows, treats them as sources
  alongside the automated discovery, and marks them "Used" when an episode
  ships.
- Items that don't get picked (Inbox stays "New" but lesson doesn't need them)
  carry to the next run.
