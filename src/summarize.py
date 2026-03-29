"""Stage 2: Generate a spoken script from collected news using Google Gemini."""

import os
from google import genai


# Prompt templates by recap length
PROMPTS = {
    "short": """You are a friendly, professional news briefing host called Dispatch.
Write a spoken script (~2 minutes when read aloud) summarizing the following news articles.

Rules:
- Start by jumping right into the news — do NOT say "good morning" or reference a time of day
- Group stories by topic
- For each story: one headline sentence + one sentence of context
- Use natural, conversational language — this will be read aloud
- End with a brief sign-off
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Do NOT say "Article 1" or number the stories

Articles by topic:
{articles}""",

    "medium": """You are a friendly, professional news briefing host called Dispatch.
Write a spoken script (~5 minutes when read aloud) summarizing the following news articles.

Rules:
- Start by jumping right into the news — do NOT say "good morning" or reference a time of day
- Group stories by topic with smooth transitions between topics
- For each story: headline + a short paragraph of context explaining why it matters
- Draw connections between related stories when relevant
- Use natural, conversational language — this will be read aloud
- End with a brief sign-off
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Do NOT say "Article 1" or number the stories

Articles by topic:
{articles}""",

    "deep": """You are a friendly, professional news briefing host called Dispatch.
Write a spoken script (~10 minutes when read aloud) providing an in-depth briefing on the following news articles.

Rules:
- Start with a quick overview of today's top themes — do NOT say "good morning" or reference a time of day
- Group stories by topic with smooth transitions
- For each story: headline + detailed summary + analysis of implications
- Draw connections between stories across topics
- Include brief context about why each story matters for someone in AI, marketing, and B2B tech
- Use natural, conversational language — this will be read aloud
- End with key takeaways and a sign-off
- Do NOT use markdown, bullet points, or formatting — plain spoken text only
- Do NOT say "Article 1" or number the stories

Articles by topic:
{articles}""",
}


def generate_script(news_data: list, recap_length: str = "medium") -> str:
    """Generate a spoken briefing script from collected news articles.

    Args:
        news_data: Output from collect.collect_news()
        recap_length: "short", "medium", or "deep"

    Returns:
        Plain text script ready for TTS.
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("  Warning: GEMINI_API_KEY not set, falling back to headline list")
        return _fallback_script(news_data)

    client = genai.Client(api_key=api_key)

    # Format articles for the prompt
    articles_text = _format_articles(news_data)

    if not articles_text.strip():
        return "Good morning! I checked your news feeds today but didn't find any new stories. Check back tomorrow!"

    prompt_template = PROMPTS.get(recap_length, PROMPTS["medium"])
    prompt = prompt_template.format(articles=articles_text)

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        script = response.text.strip()
        print(f"  Generated {recap_length} script ({len(script)} chars)")
        return script
    except Exception as e:
        print(f"  Error calling Gemini: {e}")
        print("  Falling back to headline list")
        return _fallback_script(news_data)


def _format_articles(news_data: list) -> str:
    """Format news data into a readable text block for the LLM prompt."""
    sections = []
    for topic_data in news_data:
        topic = topic_data["topic"]
        articles = topic_data["articles"]
        if not articles:
            continue

        section = f"\n--- {topic} ---\n"
        for art in articles:
            section += f"\nHeadline: {art['title']}\n"
            section += f"Source: {art['source']}\n"
            if art["description"]:
                section += f"Summary: {art['description']}\n"
        sections.append(section)

    return "\n".join(sections)


def _fallback_script(news_data: list) -> str:
    """Simple headline list when Gemini is unavailable."""
    lines = ["Good morning! Here are today's headlines.\n"]
    for topic_data in news_data:
        topic = topic_data["topic"]
        articles = topic_data["articles"]
        if not articles:
            continue
        lines.append(f"In {topic}:")
        for art in articles:
            lines.append(f"  {art['title']}, from {art['source']}.")
        lines.append("")
    lines.append("That's your briefing for today. Have a great day!")
    return "\n".join(lines)
