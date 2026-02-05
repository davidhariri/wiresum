"""Classification of feed entries using Anthropic Claude."""

import json
import logging
import re

from anthropic import Anthropic
from firecrawl import Firecrawl

from .config import Config
from .db import Database, Entry

logger = logging.getLogger(__name__)


def fetch_content_from_url(config: Config, url: str) -> str | None:
    """Fetch article content from URL using Firecrawl.

    Returns markdown content or None if fetch fails.
    """
    if not url:
        return None

    try:
        client = Firecrawl(api_key=config.firecrawl_api_key)
        doc = client.scrape(url, formats=["markdown"])
        markdown = getattr(doc, "markdown", None)
        if markdown:
            logger.info(f"Fetched {len(markdown)} chars from {url[:50]}...")
            return markdown
    except Exception as e:
        logger.warning(f"Firecrawl failed for {url}: {e}")

    return None


def build_system_prompt(db: Database) -> str:
    """Build the system prompt with user context and interests."""
    user_context = db.get_config("user_context") or ""
    interests = db.get_interests()

    interests_text = "\n".join(
        f"- {i.key}: {i.label}" + (f" - {i.description}" if i.description else "")
        for i in interests
    )

    return f"""You are a smart assistant helping filter RSS feeds. You know your reader well:

{user_context}

Your job: Classify each article and extract key insights tailored to this reader.

## Output Format (JSON)

{{"interest": "key_or_null", "is_signal": true/false, "reasoning": "bullet points"}}

## Fields

**interest**: Match to one of these keys, or null if none fit:
{interests_text}

**is_signal**: true ONLY if genuinely valuable. Filter out:
- Marketing, PR, corporate case studies
- "How X uses Y" fluff pieces
- Podcast/video promos without substance
- News without insight or implications

**reasoning**: Key takeaways as bullet points. Write for your reader specifically.
- What's the actual insight? (not just "this article discusses X")
- Why would this matter to someone building in AI/iOS/startups?
- Any tactical takeaway or implication?

Keep each bullet punchy—one clear thought. 1-3 bullets depending on substance.

Good:
• Regulatory moat took 4 years to build—competitors effectively locked out
• Swift 6 ownership approach worth adopting for Counsel's data layer

Bad:
• This article discusses the importance of regulatory compliance (too vague)
• Interesting insights about the startup ecosystem (says nothing)"""


def classify_entry(
    config: Config,
    db: Database,
    entry: Entry,
) -> tuple[str | None, bool, str]:
    """Classify a single entry.

    Returns (interest, is_signal, reasoning).
    """
    # Get model from database config
    model = db.get_config("model") or "claude-sonnet-4-20250514"

    # Build system prompt with user context
    system_prompt = build_system_prompt(db)

    # If Firecrawl is configured, always fetch content from URL
    # Otherwise, use Feedbin content as-is
    if config.firecrawl_api_key and entry.url:
        fetched = fetch_content_from_url(config, entry.url)
        if fetched:
            # Update entry with fetched content for classification
            entry = Entry(
                id=entry.id,
                feedbin_id=entry.feedbin_id,
                feed_name=entry.feed_name,
                title=entry.title,
                url=entry.url,
                content=fetched,
                author=entry.author,
                published_at=entry.published_at,
                fetched_at=entry.fetched_at,
                processed_at=entry.processed_at,
                interest=entry.interest,
                is_signal=entry.is_signal,
                reasoning=entry.reasoning,
            )
            # Persist fetched content to DB
            db.update_entry_content(entry.id, fetched)

    # Format the entry for classification
    user_content = format_entry_for_classification(entry)

    # Call Anthropic
    client = Anthropic(api_key=config.anthropic_api_key)
    response = client.messages.create(
        model=model,
        max_tokens=500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )

    # Parse the response
    content = response.content[0].text
    return parse_classification_response(content)


def format_entry_for_classification(entry: Entry) -> str:
    """Format an entry for classification."""
    parts = []

    if entry.feed_name:
        parts.append(f"Feed: {entry.feed_name}")
    if entry.title:
        parts.append(f"Title: {entry.title}")
    if entry.url:
        parts.append(f"URL: {entry.url}")
    if entry.author:
        parts.append(f"Author: {entry.author}")
    if entry.content:
        # Truncate long content
        content = entry.content[:3000] if len(entry.content) > 3000 else entry.content
        # Strip HTML tags for cleaner classification
        content = re.sub(r"<[^>]+>", " ", content)
        content = re.sub(r"\s+", " ", content).strip()
        parts.append(f"Content: {content}")

    return "\n".join(parts)


def parse_classification_response(content: str) -> tuple[str | None, bool, str]:
    """Parse the JSON classification response.

    Returns (interest, is_signal, reasoning).
    """
    # Try to extract JSON from the response
    try:
        # Handle markdown code blocks
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
            if match:
                content = match.group(1)

        data = json.loads(content)

        # Support both "interest" and legacy "topic" keys
        interest = data.get("interest") or data.get("topic")
        if interest == "null" or interest == "":
            interest = None

        is_signal = bool(data.get("is_signal", False))
        reasoning = data.get("reasoning", "No reasoning provided")

        # Handle reasoning as list (model sometimes returns array instead of string)
        if isinstance(reasoning, list):
            reasoning = "\n".join(f"• {r}" for r in reasoning)

        # Ensure bullets have bullet points if they don't
        if reasoning and not reasoning.startswith("•") and not reasoning.startswith("-"):
            lines = reasoning.strip().split("\n")
            reasoning = "\n".join(
                line if line.startswith(("•", "-")) else f"• {line}"
                for line in lines
                if line.strip()
            )

        return (interest, is_signal, reasoning)

    except (json.JSONDecodeError, KeyError) as e:
        # If parsing fails, return as noise with error message
        return (None, False, f"Failed to parse classification: {e}")


def process_unclassified_entries(config: Config, db: Database, limit: int = 10) -> int:
    """Process unclassified entries.

    Returns the number of entries processed.
    """
    entries = db.get_unprocessed_entries(limit=limit)

    for entry in entries:
        try:
            interest, is_signal, reasoning = classify_entry(config, db, entry)
            db.update_entry_classification(entry.id, interest, is_signal, reasoning)
        except Exception as e:
            # Mark as processed with error
            db.update_entry_classification(entry.id, None, False, f"Classification error: {e}")

    return len(entries)
