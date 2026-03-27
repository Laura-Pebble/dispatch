"""Stage 4: Deliver the audio recap via push notification."""

import os
import requests
from datetime import datetime


def upload_file(file_path: str) -> str | None:
    """Upload MP3 to a temporary file host and return the download URL.

    Uses 0x0.st (free, no account, files last 30 days minimum).
    Falls back to None if upload fails.
    """
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                "https://0x0.st",
                files={"file": (os.path.basename(file_path), f, "audio/mpeg")},
                timeout=60,
            )
        if response.status_code == 200:
            url = response.text.strip()
            print(f"  Uploaded to: {url}")
            return url
        else:
            print(f"  Upload failed: HTTP {response.status_code}")
            return None
    except Exception as e:
        print(f"  Upload error: {e}")
        return None


def send_notification(ntfy_topic: str, audio_url: str | None = None, script_text: str = ""):
    """Send a push notification via Ntfy.sh.

    Args:
        ntfy_topic: The Ntfy topic name (e.g., "laura-morning-news").
        audio_url: URL to the uploaded MP3 (if available).
        script_text: Fallback text if no audio URL.
    """
    today = datetime.now().strftime("%A, %B %d")

    if audio_url:
        # Notification with audio link
        message = f"Your morning briefing for {today} is ready. Tap to listen."
        headers = {
            "Title": f"Morning News Recap - {today}",
            "Priority": "default",
            "Tags": "newspaper,headphones",
            "Click": audio_url,
        }
    else:
        # Text-only fallback
        message = script_text[:4000] if script_text else f"Morning briefing for {today} — audio generation failed."
        headers = {
            "Title": f"Morning News Recap - {today}",
            "Priority": "default",
            "Tags": "newspaper",
        }

    try:
        response = requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        if response.status_code == 200:
            print(f"  Notification sent to topic: {ntfy_topic}")
        else:
            print(f"  Notification failed: HTTP {response.status_code}")
    except Exception as e:
        print(f"  Notification error: {e}")


def deliver(file_path: str, ntfy_topic: str, script_text: str = ""):
    """Upload audio and send push notification.

    Args:
        file_path: Path to the MP3 file.
        ntfy_topic: Ntfy topic for push notification.
        script_text: The script text (used as fallback if audio upload fails).
    """
    audio_url = upload_file(file_path)
    send_notification(ntfy_topic, audio_url=audio_url, script_text=script_text)
