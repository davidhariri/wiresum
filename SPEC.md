# Wiresum v2 - Specification

AI-powered feed filter. Server runs in Docker, continuously syncs Feedbin and classifies content. CLI reads and commands the server.

## Architecture

```
wiresum/
├── wiresum/
│   ├── __init__.py
│   ├── server.py        # FastAPI server (sync, process, API)
│   ├── cli.py           # Click CLI (talks to server)
│   ├── config.py        # Environment + runtime config
│   ├── db.py            # SQLite operations
│   ├── feedbin.py       # Feedbin API client
│   └── classifier.py    # Claude classification
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── SPEC.md
├── .env.example
└── README.md
```

## Server

Runs continuously in Docker:
- **Background sync**: Polls Feedbin every N minutes, stores new entries
- **Background processing**: Classifies unprocessed entries with Claude
- **API endpoints**:
  - `GET /entries` - List entries (with filters: processed, interest, etc.)
  - `GET /entries/{id}` - Get specific entry
  - `POST /entries/{id}/reprocess` - Re-run classification on specific entry
  - `POST /entries/{id}/read` - Mark entry as read
  - `GET /digest` - Entries grouped by interest
  - `GET /config` - Current prompt/model settings
  - `PUT /config` - Update prompt/model settings
  - `GET /interests` - List all interests
  - `POST /interests` - Add a new interest
  - `PUT /interests/{key}` - Update an interest
  - `DELETE /interests/{key}` - Delete an interest
  - `GET /stats` - Database statistics
  - `POST /sync` - Manually trigger Feedbin sync
  - `POST /entries/requeue` - Re-queue entries for classification
  - `GET /feed.xml` - RSS feed of signal entries (with AI insights as content)

## CLI Commands

| Command | Description |
|---------|-------------|
| `wiresum` | TUI digest view (default) |
| `wiresum -a` | Include filtered (non-signal) entries |
| `wiresum list` | Flat table view |
| `wiresum sync` | Manually trigger Feedbin sync |
| `wiresum requeue` | Re-classify recent entries |
| `wiresum stats` | Show database statistics |
| `wiresum reprocess <id>` | Re-classify specific entry |
| `wiresum interests list` | List all interests |
| `wiresum interests add <key> <label> [desc]` | Add interest |
| `wiresum interests edit <key> [--label] [--desc]` | Edit interest |
| `wiresum interests delete <key>` | Delete interest |
| `wiresum config show` | Show configuration |
| `wiresum config set <key> <value>` | Update config |

## Database Schema

```sql
CREATE TABLE entries (
    id INTEGER PRIMARY KEY,
    feedbin_id INTEGER UNIQUE NOT NULL,
    feed_name TEXT,
    title TEXT,
    url TEXT,
    content TEXT,
    author TEXT,
    published_at TEXT,
    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    interest TEXT,
    is_signal INTEGER,
    reasoning TEXT,
    read_at TEXT
);

CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Stores: classification_prompt, model, sync_interval, process_after

CREATE TABLE interests (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,      -- e.g., 'ai_llm'
    label TEXT NOT NULL,           -- e.g., 'AI/LLMs'
    description TEXT               -- e.g., 'New models, research, ideas'
);
```

## Default Interests

| Key | Label | Description |
|-----|-------|-------------|
| `ai_llm` | AI/LLMs | New models, research, ideas |
| `support_tech` | Support Tech | Customer support technology |
| `startups` | Startups | Startup ecosystem, funding, launches |
| `dev_tools` | Dev Tools | Developer tools, workflows |
| `software` | Software | New software products (macOS/iOS/web) |

## Environment Variables

```
FEEDBIN_EMAIL=...
FEEDBIN_PASSWORD=...
ANTHROPIC_API_KEY=...
FIRECRAWL_API_KEY=...          # Optional, improves content extraction
WIRESUM_DB_PATH=/data/wiresum.db
WIRESUM_SERVER_URL=http://localhost:8000
```

## Classification

Claude receives entries and classifies them:
- **interest**: Which interest this entry belongs to (or null if irrelevant)
- **is_signal**: Whether this is worth reading (1) or noise (0)
- **reasoning**: Brief explanation of the classification

The classification prompt is stored in the database and can be updated via CLI/API.
