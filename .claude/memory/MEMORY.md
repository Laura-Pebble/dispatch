# Morning News Voice Recap — Project Memory

## Owner
- Laura McAliley (laura@pebble-marketing.com)

## Project Overview
Daily news briefing tool: scans RSS feeds → Gemini AI script → Edge TTS audio → push notification

## Architecture
- **Pipeline**: collect.py → summarize.py → speak.py → deliver.py (orchestrated by main.py)
- **AI**: Google Gemini API (Laura has paid account)
- **TTS**: Microsoft Edge TTS (free, neural voice: en-US-AriaNeural)
- **Delivery**: Ntfy.sh push notifications (topic: laura-morning-news)
- **Scheduling**: GitHub Actions (daily 7 AM ET / noon UTC)
- **Config**: config.yaml controls topics, feeds, length, voice, notification

## News Topics
1. AI and Marketing — MarTech, Marketing AI Institute, Content Marketing Institute
2. General News — BBC, NYT
3. AI for Business — Ars Technica, VentureBeat
4. B2B Tech and Startups — TechCrunch, SaaStr

## Status
- All source files written (main.py, collect.py, summarize.py, speak.py, deliver.py)
- Config and GitHub Actions workflow created
- NOT YET: dependencies installed, local test run, pushed to GitHub, Ntfy app installed
- Laura may change the approach — this is still exploratory

## Key Decisions
- Free tools prioritized (Edge TTS, Ntfy.sh, GitHub Actions free tier)
- Graceful fallbacks at every stage (feed fail → skip, Gemini fail → headline list, TTS fail → text-only)
- Three recap lengths: short (~2 min), medium (~5 min), deep (~10 min)

## Location
- Pebble Google Drive: `GoogleDrive-laura@pebble-marketing.com/My Drive/Morning News Recap/`
