"""Feedbin API client for syncing feed entries."""

import httpx

from .config import Config
from .db import Database, Entry


FEEDBIN_API = "https://api.feedbin.com/v2"


class FeedbinClient:
    """Client for the Feedbin API."""

    def __init__(self, config: Config):
        self.email = config.feedbin_email
        self.password = config.feedbin_password

    def _auth(self) -> tuple[str, str]:
        """Return basic auth tuple."""
        return (self.email, self.password)

    def verify_credentials(self) -> bool:
        """Verify that credentials are valid."""
        response = httpx.get(
            f"{FEEDBIN_API}/authentication.json",
            auth=self._auth(),
        )
        return response.status_code == 200

    def get_subscriptions(self) -> dict[int, str]:
        """Get a mapping of feed_id -> feed_name."""
        response = httpx.get(
            f"{FEEDBIN_API}/subscriptions.json",
            auth=self._auth(),
        )
        response.raise_for_status()

        return {sub["feed_id"]: sub["title"] for sub in response.json()}

    def get_entries(self, since: str | None = None, per_page: int = 100) -> list[dict]:
        """Fetch entries from Feedbin.

        Args:
            since: ISO 8601 timestamp to fetch entries after (e.g. process_after date)
        """
        all_entries = []
        page = 1

        while True:
            params = {"per_page": per_page, "page": page}
            if since:
                params["since"] = since

            response = httpx.get(
                f"{FEEDBIN_API}/entries.json",
                auth=self._auth(),
                params=params,
                timeout=30.0,
            )

            # Feedbin returns 404 on empty pages when using since
            if response.status_code == 404:
                break

            response.raise_for_status()

            entries = response.json()
            if not entries:
                break

            all_entries.extend(entries)
            page += 1

        return all_entries


def sync_feedbin(config: Config, db: Database) -> int:
    """Sync entries from Feedbin to the database.

    Fetches entries since process_after date. Database upsert handles deduplication.

    Returns the number of entries synced.
    """
    client = FeedbinClient(config)

    # Get feed names for labeling
    subscriptions = client.get_subscriptions()

    # Get process_after date to limit how far back we fetch
    process_after = db.get_config("process_after")

    # Fetch entries since process_after (or all if not set)
    entries = client.get_entries(since=process_after)

    # Store each entry
    count = 0
    for raw in entries:
        feed_name = subscriptions.get(raw.get("feed_id"), "Unknown Feed")

        entry = Entry(
            id=None,
            feedbin_id=raw["id"],
            feed_name=feed_name,
            title=raw.get("title"),
            url=raw.get("url"),
            content=raw.get("content"),
            author=raw.get("author"),
            published_at=raw.get("published"),
            fetched_at=None,
            processed_at=None,
            interest=None,
            is_signal=None,
            reasoning=None,
        )
        db.upsert_entry(entry)
        count += 1

    return count
