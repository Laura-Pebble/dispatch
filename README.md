# Dispatch

A daily news briefing tool that scans RSS feeds, generates a conversational script with Google Gemini, converts it to a podcast-style MP3 with Microsoft Edge TTS, and sends you a push notification with a link to listen.

## How It Works

1. **Collect** — Pulls articles from RSS feeds across your configured topics
2. **Summarize** — Gemini writes a natural, conversational briefing script
3. **Speak** — Edge TTS converts the script to a high-quality MP3
4. **Deliver** — Uploads the audio and sends a push notification via Ntfy

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your Gemini API key

```bash
export GEMINI_API_KEY="your-key-here"
```

### 3. Install Ntfy on your phone

- [iOS App Store](https://apps.apple.com/us/app/ntfy/id1625396347)
- [Google Play](https://play.google.com/store/apps/details?id=io.heckel.ntfy)

Subscribe to your topic (default: `laura-morning-news`).

### 4. Configure topics

Edit `config.yaml` to set your news topics, recap length, and voice.

### 5. Run locally

```bash
cd src
python main.py
```

### 6. Deploy to GitHub Actions

1. Push this repo to GitHub
2. Go to Settings → Secrets → Actions
3. Add `GEMINI_API_KEY` secret
4. Optionally add `NTFY_TOPIC` to override the config default
5. The workflow runs daily at 7 AM ET (noon UTC)

You can also trigger it manually from the Actions tab.

## Configuration

Edit `config.yaml`:

| Setting | Options | Description |
|---------|---------|-------------|
| `recap_length` | `short`, `medium`, `deep` | ~2 min, ~5 min, or ~10 min briefing |
| `voice` | Any Edge TTS voice | e.g., `en-US-AriaNeural`, `en-US-GuyNeural` |
| `ntfy_topic` | Any string | Your private notification channel |
| `topics[].max_articles` | Number | Max articles per topic |
