# Wiresum - Claude Code Context

## Project Overview

Wiresum is an AI-powered feed filter. It syncs entries from Feedbin, classifies them by interest using Groq/Llama, and separates signal from noise. The server runs headless with background jobs; the CLI provides a TUI for browsing.

## Architecture

```
wiresum/
├── wiresum/
│   ├── server.py        # FastAPI server + background scheduler
│   ├── cli.py           # Click CLI + Rich TUI
│   ├── config.py        # Environment config + defaults
│   ├── db.py            # SQLite operations
│   ├── feedbin.py       # Feedbin API client + Firecrawl extraction
│   └── classifier.py    # Groq/Llama classification
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

## Tech Stack

- **Framework**: FastAPI
- **Database**: SQLite
- **AI**: Groq API (Llama models)
- **Content extraction**: Firecrawl (optional, falls back to basic HTML)
- **CLI**: Click + Rich (TUI with keyboard navigation)
- **Scheduler**: APScheduler (background sync/classify jobs)
- **Linter**: Ruff

## Code Conventions

- Python 3.11+
- Line length: 100 chars (ruff)
- Use type hints for function signatures
- Docstrings for public functions
- Import order: stdlib, third-party, local (ruff I)
- Prefer simple, readable code over clever abstractions

## Testing

Currently no test suite. When adding tests:
- Use pytest
- Place tests in `tests/` directory
- Name files `test_*.py`
- Run with: `pytest tests/`

## Branch Naming

- Claude-created branches: `claude/issue-{number}-{short-description}`
- Example: `claude/issue-42-add-dark-mode`

## Review Checklist

For PRs to be approved, ensure:
- [ ] Code follows existing patterns in the codebase
- [ ] No obvious security issues (especially API key handling)
- [ ] Changes are documented if they affect user-facing behavior
- [ ] Tests included for new functionality (when test suite exists)
- [ ] Ruff linting passes: `ruff check wiresum/`

## Environment

- Local dev: `pip install -e .`
- Run server: `uvicorn wiresum.server:app --reload`
- Run CLI: `wiresum` (requires server running)
- Docker: `docker-compose up --build`

## Key Files

- `wiresum/server.py` - FastAPI app, lifespan, background jobs, all API routes
- `wiresum/cli.py` - TUI digest view, list view, all CLI commands
- `wiresum/classifier.py` - Groq API calls, prompt construction
- `wiresum/feedbin.py` - Feedbin sync, optional Firecrawl content extraction
- `wiresum/db.py` - SQLite schema, Entry/Interest models, all DB operations
- `wiresum/config.py` - Environment variables, default interests/prompts

## Gotchas

- Server and CLI are separate: CLI talks to server via HTTP
- No auth on API (designed for local/private use)
- Database path configurable via `WIRESUM_DB_PATH` env var
- `FIRECRAWL_API_KEY` is optional; without it, uses basic HTML extraction
- Background jobs: sync runs every N minutes, classify runs every minute
- Schema uses "interest" (not "topic") and "label" (not "name")
