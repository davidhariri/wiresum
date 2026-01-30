"""Classification of feed entries using Groq (Llama)."""

import json
import logging
import re
from pathlib import Path

from firecrawl import Firecrawl
from groq import Groq
from jinja2 import Environment, FileSystemLoader

from .config import Config
from .db import Database, Entry

logger = logging.getLogger(__name__)


PROMPT_DIR = Path(__file__).parent / "prompts"
PROMPT_FILE = "classification.j2"


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


def load_prompt_template():
    """Load the Jinja2 prompt template."""
    env = Environment(loader=FileSystemLoader(PROMPT_DIR))
    return env.get_template(PROMPT_FILE)


def classify_entry(
    config: Config,
    db: Database,
    entry: Entry,
) -> tuple[str | None, bool, str]:
    """Classify a single entry.

    Returns (interest, is_signal, reasoning).
    """
    # Get model from database config
    model = db.get_config("model")

    # Load Jinja template and get interests
    template = load_prompt_template()
    interests = db.get_interests()

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

    # Render the prompt with interests
    system_prompt = template.render(interests=interests)
    user_content = format_entry_for_classification(entry)

    # Call Groq
    client = Groq(api_key=config.groq_api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
        max_tokens=500,
    )

    # Parse the response
    content = response.choices[0].message.content
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
            reasoning = "\n".join(reasoning)

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
