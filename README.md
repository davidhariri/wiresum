# Wiresum

AI-powered feed filter. Syncs your Feedbin feeds, classifies entries by interest, and separates signal from noise.

## How It Works

1. **Sync** - Background job pulls new entries from Feedbin every 15 minutes
2. **Fetch** - Firecrawl extracts clean article content (optional, falls back to basic HTML)
3. **Classify** - Claude assigns each entry to an interest and decides signal vs noise
4. **Browse** - TUI shows today's signal grouped by interest, with key takeaways

## Requirements

- Python 3.11+
- [Anthropic API key](https://console.anthropic.com)
- [Feedbin account](https://feedbin.com)
- [Firecrawl API key](https://firecrawl.dev) (optional, improves content extraction)

## Quick Start

### Run Locally

```bash
# Clone and install
git clone https://github.com/davidhariri/wiresum.git
cd wiresum
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your credentials

# Start the server
uvicorn wiresum.server:app --reload

# In another terminal, open the TUI
wiresum
```

### Run with Docker

```bash
# Clone the repo
git clone https://github.com/davidhariri/wiresum.git
cd wiresum

# Configure
cp .env.example .env
# Edit .env with your credentials

# Run
docker-compose up --build
```

The server syncs Feedbin entries and classifies them in the background. Use the CLI to browse.

## TUI Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `↑` / `k` | Move up |
| `↓` / `j` | Move down |
| `←` / `h` | Previous day |
| `→` / `l` | Next day |
| `Enter` | Open in browser |
| `c` | Copy URL to clipboard |
| `q` | Quit |

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

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key for Claude |
| `FEEDBIN_EMAIL` | Yes | Feedbin email |
| `FEEDBIN_PASSWORD` | Yes | Feedbin password |
| `FIRECRAWL_API_KEY` | No | Firecrawl API key (improves content extraction) |
| `WIRESUM_DB_PATH` | No | SQLite path (default: `/data/wiresum.db`) |
| `WIRESUM_SERVER_URL` | No | Server URL for CLI (default: `http://localhost:8000`) |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/entries` | List entries (with filters) |
| `GET` | `/entries/{id}` | Get specific entry |
| `POST` | `/entries/{id}/reprocess` | Re-classify entry |
| `POST` | `/entries/{id}/read` | Mark entry as read |
| `GET` | `/digest` | Entries grouped by interest |
| `GET` | `/config` | Get configuration |
| `PUT` | `/config` | Update configuration |
| `GET` | `/interests` | List interests |
| `POST` | `/interests` | Create interest |
| `PUT` | `/interests/{key}` | Update interest |
| `DELETE` | `/interests/{key}` | Delete interest |
| `GET` | `/stats` | Database statistics |
| `POST` | `/sync` | Trigger Feedbin sync |
| `POST` | `/entries/requeue` | Re-queue entries for classification |
| `GET` | `/feed.xml` | RSS feed of signal entries |

## Architecture

```
wiresum/
├── wiresum/
│   ├── server.py        # FastAPI server (sync, classify, API)
│   ├── cli.py           # Click CLI + Rich TUI
│   ├── config.py        # Environment config
│   ├── db.py            # SQLite operations
│   ├── feedbin.py       # Feedbin API client
│   └── classifier.py    # Claude classification
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## License

MIT
