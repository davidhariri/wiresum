"""FastAPI server with background sync and classification tasks."""

import logging
import os
import sys
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .classifier import classify_entry, process_unclassified_entries
from .config import load_config
from .db import Database
from .feedbin import sync_feedbin


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def validate_environment():
    """Validate required environment variables on startup."""
    required = {
        "GROQ_API_KEY": "Groq API key for classification (https://console.groq.com)",
        "FEEDBIN_EMAIL": "Feedbin account email",
        "FEEDBIN_PASSWORD": "Feedbin account password",
    }

    missing = []
    for var, description in required.items():
        if not os.environ.get(var):
            missing.append(f"  {var}: {description}")

    if missing:
        logger.error("Missing required environment variables:")
        for m in missing:
            logger.error(m)
        logger.error("\nCopy .env.example to .env and fill in your credentials.")
        sys.exit(1)

    # Warn about optional but recommended variables
    if not os.environ.get("FIRECRAWL_API_KEY"):
        logger.warning(
            "FIRECRAWL_API_KEY not set. Article content extraction will be limited "
            "to basic HTML parsing. For better results, get a key at https://firecrawl.dev"
        )

# Global state
config = None
db = None
scheduler = None


def sync_job():
    """Background job to sync Feedbin entries."""
    try:
        count = sync_feedbin(config, db)
        if count > 0:
            logger.info(f"Synced {count} new entries from Feedbin")
    except Exception as e:
        logger.error(f"Feedbin sync error: {e}")


def classify_job():
    """Background job to classify unprocessed entries."""
    try:
        count = process_unclassified_entries(config, db, limit=10)
        if count > 0:
            logger.info(f"Classified {count} entries")
    except Exception as e:
        logger.error(f"Classification error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    global config, db, scheduler

    # Validate environment before starting
    validate_environment()

    # Initialize
    config = load_config()
    db = Database(config.db_path)
    scheduler = BackgroundScheduler()

    # Get sync interval from config
    sync_interval = int(db.get_config("sync_interval") or 15)

    # Schedule background jobs
    scheduler.add_job(sync_job, "interval", minutes=sync_interval, id="sync")
    scheduler.add_job(classify_job, "interval", minutes=1, id="classify")
    scheduler.start()

    logger.info(f"Server started. Sync interval: {sync_interval} minutes")

    # Run initial sync
    sync_job()

    yield

    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="Wiresum", version="2.0.0", lifespan=lifespan)


# --- Pydantic models ---


class EntryResponse(BaseModel):
    id: int
    feedbin_id: int
    feed_name: str | None
    title: str | None
    url: str | None
    content: str | None
    author: str | None
    published_at: str | None
    processed_at: str | None
    interest: str | None
    is_signal: bool | None
    reasoning: str | None
    read_at: str | None


class ConfigResponse(BaseModel):
    classification_prompt: str
    model: str
    sync_interval: int
    process_after: str | None


class ConfigUpdate(BaseModel):
    key: str
    value: str


class InterestResponse(BaseModel):
    id: int
    key: str
    label: str
    description: str | None


class InterestCreate(BaseModel):
    key: str
    label: str
    description: str | None = None


class InterestUpdate(BaseModel):
    label: str | None = None
    description: str | None = None


class DigestInterestSummary(BaseModel):
    interest_key: str | None
    interest_label: str | None
    count: int
    entries: list[EntryResponse]


class StatsResponse(BaseModel):
    total_entries: int
    unprocessed: int
    signal: int


# --- API routes ---


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "version": "2.0.0"}


@app.get("/entries", response_model=list[EntryResponse])
def list_entries(
    processed: bool | None = None,
    interest: str | None = None,
    is_signal: bool | None = None,
    limit: int = 100,
    offset: int = 0,
    since_hours: int | None = None,
):
    """List entries with optional filters."""
    entries = db.get_entries(
        processed=processed,
        interest=interest,
        is_signal=is_signal,
        limit=limit,
        offset=offset,
        since_hours=since_hours,
    )
    return [_entry_to_response(e) for e in entries]


@app.get("/entries/{entry_id}", response_model=EntryResponse)
def get_entry(entry_id: int):
    """Get a specific entry."""
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return _entry_to_response(entry)


@app.post("/entries/{entry_id}/reprocess", response_model=EntryResponse)
def reprocess_entry(entry_id: int):
    """Re-classify a specific entry."""
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Clear existing classification
    db.clear_entry_classification(entry_id)

    # Re-classify
    interest, is_signal, reasoning = classify_entry(config, db, entry)
    db.update_entry_classification(entry_id, interest, is_signal, reasoning)

    # Return updated entry
    return _entry_to_response(db.get_entry(entry_id))


@app.post("/entries/{entry_id}/read")
def mark_entry_read(entry_id: int):
    """Mark an entry as read."""
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    db.mark_entry_read(entry_id)
    return {"status": "ok"}


@app.get("/digest", response_model=list[DigestInterestSummary])
def get_digest(
    limit_per_interest: int = 10,
    since_hours: int = 48,
    date: str | None = None,
    include_all: bool = False,
):
    """Get entries grouped by interest.

    Args:
        date: Filter to a specific date (YYYY-MM-DD format). If provided, since_hours is ignored.
        include_all: If True, include filtered (non-signal) entries too.
    """
    interests = db.get_interests()

    result = []

    # Get entries for each interest
    for interest in interests:
        entries = db.get_entries(
            processed=True,
            interest=interest.key,
            is_signal=None if include_all else True,
            limit=limit_per_interest,
            since_hours=since_hours if date is None else None,
            date=date,
        )
        if entries:
            result.append(
                DigestInterestSummary(
                    interest_key=interest.key,
                    interest_label=interest.label,
                    count=len(entries),
                    entries=[_entry_to_response(e) for e in entries],
                )
            )

    # Get entries with no interest
    no_interest_entries = db.get_entries(
        processed=True,
        is_signal=None if include_all else True,
        limit=limit_per_interest,
        since_hours=since_hours if date is None else None,
        date=date,
    )
    # Filter to only include entries where interest is actually None
    no_interest_entries = [e for e in no_interest_entries if e.interest is None]
    if no_interest_entries:
        result.append(
            DigestInterestSummary(
                interest_key=None,
                interest_label="Other",
                count=len(no_interest_entries),
                entries=[_entry_to_response(e) for e in no_interest_entries],
            )
        )

    return result


@app.get("/config")
def get_config():
    """Get current configuration."""
    return {
        "classification_prompt": db.get_config("classification_prompt") or "",
        "model": db.get_config("model") or "",
        "sync_interval": int(db.get_config("sync_interval") or 15),
        "process_after": db.get_config("process_after") or "",
    }


@app.put("/config")
def update_config(update: ConfigUpdate):
    """Update a configuration value."""
    valid_keys = {"classification_prompt", "model", "sync_interval", "process_after"}
    if update.key not in valid_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid config key. Valid keys: {valid_keys}",
        )

    db.set_config(update.key, update.value)

    # If sync interval changed, update scheduler
    if update.key == "sync_interval" and scheduler:
        scheduler.reschedule_job("sync", trigger="interval", minutes=int(update.value))
        logger.info(f"Updated sync interval to {update.value} minutes")

    return {"status": "ok", "key": update.key, "value": update.value}


@app.get("/interests", response_model=list[InterestResponse])
def list_interests():
    """List all interests."""
    interests = db.get_interests()
    return [
        InterestResponse(
            id=i.id,
            key=i.key,
            label=i.label,
            description=i.description,
        )
        for i in interests
    ]


@app.post("/interests", response_model=InterestResponse)
def create_interest(interest: InterestCreate):
    """Create a new interest."""
    existing = db.get_interest(interest.key)
    if existing:
        raise HTTPException(status_code=400, detail="Interest with this key already exists")

    interest_id = db.create_interest(interest.key, interest.label, interest.description)
    return InterestResponse(
        id=interest_id,
        key=interest.key,
        label=interest.label,
        description=interest.description,
    )


@app.put("/interests/{key}", response_model=InterestResponse)
def update_interest(key: str, update: InterestUpdate):
    """Update an interest."""
    existing = db.get_interest(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Interest not found")

    db.update_interest(key, update.label, update.description)
    updated = db.get_interest(key)
    return InterestResponse(
        id=updated.id,
        key=updated.key,
        label=updated.label,
        description=updated.description,
    )


@app.delete("/interests/{key}")
def delete_interest(key: str):
    """Delete an interest."""
    existing = db.get_interest(key)
    if not existing:
        raise HTTPException(status_code=404, detail="Interest not found")

    db.delete_interest(key)
    return {"status": "ok", "deleted": key}


@app.get("/stats", response_model=StatsResponse)
def get_stats(since_hours: int | None = None):
    """Get database statistics."""
    stats = db.get_stats(since_hours=since_hours)
    return StatsResponse(**stats)


@app.post("/sync")
def trigger_sync():
    """Manually trigger a Feedbin sync."""
    count = sync_feedbin(config, db)
    return {"status": "ok", "synced": count}


@app.post("/entries/requeue")
def requeue_entries(since_hours: int = 24):
    """Mark entries for reprocessing by clearing their processed status."""
    count = db.requeue_entries(since_hours=since_hours)
    return {"status": "ok", "requeued": count}


# --- Helpers ---


def _entry_to_response(entry) -> EntryResponse:
    """Convert Entry to EntryResponse."""
    return EntryResponse(
        id=entry.id,
        feedbin_id=entry.feedbin_id,
        feed_name=entry.feed_name,
        title=entry.title,
        url=entry.url,
        content=entry.content,
        author=entry.author,
        published_at=entry.published_at,
        processed_at=entry.processed_at,
        interest=entry.interest,
        is_signal=entry.is_signal,
        reasoning=entry.reasoning,
        read_at=entry.read_at,
    )
