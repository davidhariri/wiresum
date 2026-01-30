# Wiresum - Claude Code Context

## Project Overview

Wiresum is a minimal, AI-powered read-later app. Users save links via a bookmarklet, and Claude generates summaries with key takeaways. Built with FastAPI and SQLite.

## Architecture

```
wiresum/
├── api/              # FastAPI web app
│   ├── main.py       # App entry point, middleware
│   ├── routes/       # API endpoints
│   └── templates/    # Jinja2 HTML templates
├── ai/               # Claude integration
│   └── summarizer.py # Article summarization
├── extraction/       # Content extraction
│   └── content.py    # trafilatura wrapper
├── storage/          # Data layer
│   └── database.py   # SQLite operations
└── cli.py            # CLI commands
```

## Tech Stack

- **Framework**: FastAPI
- **Database**: SQLite
- **AI**: Anthropic Claude API
- **Content extraction**: trafilatura
- **Templates**: Jinja2
- **CLI**: Click
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
- [ ] No obvious security issues (especially auth/API key handling)
- [ ] Changes are documented if they affect user-facing behavior
- [ ] Tests included for new functionality (when test suite exists)
- [ ] Ruff linting passes: `ruff check wiresum/`

## Environment

- Local dev: `pip install -e .`
- Run: `uvicorn wiresum.api.main:app --reload`
- Docker: `docker-compose up --build`
- Deploy: Railway (auto-deploys from main)

## Key Files

- `wiresum/api/main.py` - FastAPI app setup and middleware
- `wiresum/api/routes/articles.py` - CRUD for saved articles
- `wiresum/ai/summarizer.py` - Claude summarization logic
- `wiresum/storage/database.py` - SQLite database operations

## Gotchas

- API key auth uses `Authorization: Bearer {key}` header
- Session auth uses `itsdangerous` signed cookies
- Database path is configurable via `WIRESUM_DB_PATH` env var
- Content extraction can fail on paywalled/JS-heavy sites
