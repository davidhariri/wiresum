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
│   └── classifier.py    # Groq/Llama classification
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
- **Background processing**: Classifies unprocessed entries with Groq (Llama)
- **API endpoints**:
  - `GET /entries` - List entries (with filters: processed, topic, etc.)
  - `GET /digest` - Per-topic summaries
  - `GET /config` - Current prompt/model settings
  - `PUT /config` - Update prompt/model settings
  - `POST /entries/{id}/reprocess` - Re-run classification on specific entry
  - `GET /topics` - List all topics
  - `POST /topics` - Add a new topic
  - `PUT /topics/{key}` - Update a topic
  - `DELETE /topics/{key}` - Delete a topic

## CLI Commands

| Command | Description |
|---------|-------------|
| `wiresum` | Default view: queue + recent classifications |
| `wiresum digest` | Per-topic summaries |
| `wiresum config` | Show current prompt/model config |
| `wiresum config set <key> <value>` | Update config |
| `wiresum reprocess <id>` | Re-classify specific entry |
| `wiresum topics` | List all topics |
| `wiresum topics add <key> <name> [desc]` | Add a new topic |
| `wiresum topics edit <key> [--name] [--desc]` | Edit a topic |
| `wiresum topics delete <key>` | Delete a topic |

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
    topic TEXT,           -- NULL if irrelevant
    is_signal INTEGER,    -- 1 = worth reading, 0 = noise
    reasoning TEXT
);

CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Stores: classification_prompt, model, sync_interval

CREATE TABLE topics (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,      -- e.g., 'ai_llm'
    name TEXT NOT NULL,            -- e.g., 'AI/LLMs'
    description TEXT               -- e.g., 'New models, research, ideas'
);
```

## Default Topics

| Key | Name | Description |
|-----|------|-------------|
| `ai_llm` | AI/LLMs | New models, research, ideas |
| `support_tech` | Support Tech | Customer support technology |
| `startups` | Startups | Startup ecosystem, funding, launches |
| `dev_tools` | Dev Tools | Developer tools, workflows |
| `software` | Software | New software products (macOS/iOS/web) |

## Environment Variables

```
FEEDBIN_EMAIL=...
FEEDBIN_PASSWORD=...
GROQ_API_KEY=...
WIRESUM_DB_PATH=/data/wiresum.db
WIRESUM_SERVER_URL=http://localhost:8000
```

## Classification

Groq (Llama) receives entries and classifies them:
- **topic**: Which topic this entry belongs to (or null if irrelevant)
- **is_signal**: Whether this is worth reading (1) or noise (0)
- **reasoning**: Brief explanation of the classification

The classification prompt is stored in the database and can be updated via CLI/API.
