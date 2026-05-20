"""Pebble Teacher — AI marketing curriculum podcast.

Runs Mon / Wed / Fri at 7 AM ET. Sibling to Dispatch; deeper, curriculum-driven,
20-30 minutes per episode. See config_teacher.yaml for sources and word budgets.

Pipeline stages (see src/teacher/main.py):
  1. discover_web   — RSS scrape + full-text extract from curated expert blogs
  2. discover_x     — Gemini grounding search for X handles
  3. discover_inbox — read manual Slack/clipboard items from Teacher Inbox Notion DB
  4. curriculum     — load this episode's planned lesson from Teacher Curriculum DB
  5. curate         — rank discovered items against the lesson topic
  6. extract        — write per-source pages to Teacher Sources DB
  7. lesson_script  — generate the 20-30 min teaching script (Gemini)
  8. publish        — TTS, podcast feed, Notion episode write, Ntfy notification

The Claude Project "Pebble Teacher" reads the Sources + Episodes DBs via the
Notion connector — no manual file uploads.
"""
