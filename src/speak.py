"""Stage 3: Convert script text to spoken MP3 using Microsoft Edge TTS."""

import asyncio
import edge_tts


async def _generate_audio(text: str, voice: str, output_path: str):
    """Async helper for edge-tts generation."""
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def text_to_speech(script: str, voice: str = "en-US-AriaNeural", output_path: str = "output/recap.mp3") -> str:
    """Convert a text script to an MP3 audio file.

    Args:
        script: The spoken script text.
        voice: Edge TTS voice name (e.g., en-US-AriaNeural, en-US-GuyNeural).
        output_path: Where to save the MP3.

    Returns:
        Path to the generated MP3 file.
    """
    if not script.strip():
        raise ValueError("Empty script — nothing to convert to speech")

    # Fallback voices if primary fails
    voices_to_try = [voice]
    fallbacks = ["en-US-GuyNeural", "en-US-AriaNeural", "en-US-JennyNeural"]
    for fb in fallbacks:
        if fb != voice:
            voices_to_try.append(fb)

    import os
    for v in voices_to_try:
        try:
            print(f"  Generating audio with voice: {v}")
            asyncio.run(_generate_audio(script, v, output_path))
            size = os.path.getsize(output_path)
            if size < 1000:
                raise ValueError("Audio file too small — likely empty")
            size_mb = size / (1024 * 1024)
            print(f"  Audio saved: {output_path} ({size_mb:.1f} MB)")
            return output_path
        except Exception as e:
            print(f"  Voice {v} failed: {e}")

    raise RuntimeError(f"All TTS voices failed: {voices_to_try}")
