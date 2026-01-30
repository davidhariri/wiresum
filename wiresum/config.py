"""Configuration management via environment variables and database."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass
class Config:
    """Application configuration loaded from environment."""

    # API Keys
    groq_api_key: str
    feedbin_email: str
    feedbin_password: str
    firecrawl_api_key: str

    # Paths
    db_path: Path

    # Server
    server_url: str


def load_config() -> Config:
    """Load configuration from environment variables."""
    load_dotenv()

    # Default to ~/.wiresum/wiresum.db for local, /data/wiresum.db for Docker
    default_db_path = Path.home() / ".wiresum" / "wiresum.db"
    db_path_env = os.getenv("WIRESUM_DB_PATH")
    db_path = Path(db_path_env) if db_path_env else default_db_path

    return Config(
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        feedbin_email=os.getenv("FEEDBIN_EMAIL", ""),
        feedbin_password=os.getenv("FEEDBIN_PASSWORD", ""),
        firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
        db_path=db_path,
        server_url=os.getenv("WIRESUM_SERVER_URL", "http://localhost:8000"),
    )


# Default classification prompt - generates analytical insights
DEFAULT_CLASSIFICATION_PROMPT = """Classify RSS entries. Return JSON.

interest: match to key or null
is_signal: true if worth reading
reasoning: MAX 15 WORDS. No articles (a/an/the). No verbs like "shows/demonstrates/highlights". Fragment style.

COPY THIS STYLE EXACTLY:
- "iCloud sync approach worth copying—closes gap vs Reeder"
- "10x volume post-election = prediction markets mainstream"
- "memory trick applicable to Swift codebase"
- "EU policy push—new partnership opportunities"
- "€500K grant for AI youth safety research"

WRONG (too long, too formal):
- "This demonstrates how AI is transforming the design workflow"
- "The article shows that prediction markets are gaining traction"

Interests:
{interests}

{{{{"interest": "key_or_null", "is_signal": bool, "reasoning": "15 words max fragment"}}}}"""

DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_SYNC_INTERVAL = 15  # minutes

# Default interests (key, label, description for AI context)
DEFAULT_INTERESTS = [
    (
        "ai",
        "AI",
        "New AI models, research, techniques, and tools. How companies are applying AI. LLM developments.",
    ),
    (
        "dev",
        "Dev",
        "Developer tools, programming languages, workflows, and engineering practices.",
    ),
    (
        "startups",
        "Startups",
        "Startup funding, launches, founder stories, and market dynamics.",
    ),
    (
        "cx",
        "CX Tech",
        "Customer support and experience technology. Relevant to Ada's domain.",
    ),
    (
        "apple",
        "Apple",
        "Apple product rumors and announcements. The indie developer ecosystem around iOS/macOS. Updates to Apple's first-party apps and their new features. Not general Apple commentary or stock news.",
    ),
    (
        "apps",
        "Apps",
        "Productivity apps and tools that improve workflows. Not OS-level, not dev tools.",
    ),
]


def get_default_process_after() -> str:
    """Return ISO datetime for 24 hours ago (default cutoff for new installs)."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
