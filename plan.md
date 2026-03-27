# Plan: Add Notion Logging to Pipeline

## Goal
After the pipeline collects articles, log each one to the Notion "Industry Intel — Saved Articles" database so claude.ai has data to discuss each morning.

## What exists
- `collect.py` already gathers articles (title, source, description, link)
- Notion database exists with fields: Title, Category, Relevance, Status, Tags, Source, URL, Date Found, Notes, Why It Matters, Scraped
- Gemini is working for summarization

## Steps

### 1. Set up Notion API access
- Laura creates a Notion internal integration at https://www.notion.so/my-integrations
- She shares the Industry Intel database with the integration
- Integration token goes in env var `NOTION_TOKEN`

### 2. Add `notion-client` to requirements.txt

### 3. Create `src/log_notion.py`
New script that:
- Takes collected articles from `collect.py`
- Checks each article URL against existing entries (skip duplicates)
- Uses Gemini to classify each article: Category, Relevance, Tags, Why It Matters
- Logs to Notion with:
  - Title = article headline
  - Source = publication name
  - URL = article link
  - Date Found = today
  - Status = "To Review"
  - Category, Relevance, Tags, Why It Matters = from Gemini classification
  - Scraped = unchecked

### 4. Update `src/main.py`
Add Notion logging as a new step between Collect and Summarize:
```
Collect → Log to Notion → Summarize → Speak → Deliver
```

### 5. Update GitHub Actions workflow
Add `NOTION_TOKEN` secret to the env vars

### 6. Test the full pipeline locally
