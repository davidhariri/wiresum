# Wiresum - Product Specification

## Vision

AI-powered feed filter that separates signal from noise. A personal assistant that knows what you care about and surfaces only what matters.

## Positioning

**Core differentiator**: AI classification + personalized insights

| Feature | Feedbin | Readwise Reader | Matter | Wiresum |
|---------|---------|-----------------|--------|---------|
| RSS feeds | Yes | Yes | Yes | Yes |
| Newsletter ingestion | No | Yes | Yes | Yes |
| Save links | No | Yes | Yes | Yes |
| AI filtering | No | No | No | **Yes** |
| Personalized context | No | No | No | **Yes** |
| Page archiving | No | Yes | Yes | Yes |
| Semantic search | No | Partial | No | **Yes** |

Wiresum isn't another read-later app. It's a filter that sits upstream of your attention.

---

## V1 - SaaS Launch

### Features

**Content Ingestion**
- RSS feed management (add URL, OPML import, auto-discover from site)
- Browser extensions (Safari + Chrome) to save any link
- Newsletter ingestion (unique email address per user)

**AI Processing**
- Classification with personalized user context (interests, priorities)
- Signal/noise filtering with reasoning
- Page archiving via Firecrawl (full content preservation)
- Semantic search over archived content

**User Experience**
- Web app (Vite + React served by FastAPI)
- Personal RSS output feed (subscribe in any reader)
- Multi-user auth (Google OAuth + email/password)

**Billing**
- Stripe integration
- Single tier at launch

### Pricing

**$9.99/month**
- 50 articles/day (classification + archive combined)
- Unlimited feeds
- Full archive access
- Personal RSS output feed

### Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | FastAPI |
| Background Jobs | arq (Redis-backed) |
| Frontend | Vite + React |
| Database | Postgres (multi-tenant) |
| Auth | FastAPI auth library (Google OAuth + email/password) |
| Payments | Stripe |
| AI | Anthropic Claude |
| Content Extraction | Firecrawl |
| Search | pgvector (semantic) |

### Architecture

```
wiresum/
├── wiresum/
│   ├── __init__.py
│   ├── server.py        # FastAPI app, lifespan, routes
│   ├── worker.py        # arq background jobs
│   ├── auth.py          # Authentication (Google + email)
│   ├── billing.py       # Stripe integration
│   ├── config.py        # Environment + runtime config
│   ├── db.py            # Postgres operations
│   ├── feeds.py         # RSS/OPML/newsletter handling
│   ├── classifier.py    # Claude classification
│   ├── archiver.py      # Firecrawl content extraction
│   └── search.py        # Semantic search (pgvector)
├── frontend/            # Vite + React app
├── extensions/          # Browser extensions
│   ├── safari/
│   └── chrome/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

### Data Model

```sql
-- Users
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,              -- null for OAuth-only users
    google_id TEXT UNIQUE,
    newsletter_email TEXT UNIQUE,    -- unique inbound address
    created_at TIMESTAMPTZ DEFAULT NOW(),
    stripe_customer_id TEXT,
    subscription_status TEXT         -- 'active', 'past_due', 'canceled'
);

-- User interests/context
CREATE TABLE user_interests (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT,
    UNIQUE(user_id, key)
);

-- User configuration
CREATE TABLE user_config (
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value TEXT,
    PRIMARY KEY(user_id, key)
);

-- Feed subscriptions
CREATE TABLE feeds (
    id SERIAL PRIMARY KEY,
    url TEXT UNIQUE NOT NULL,
    title TEXT,
    site_url TEXT,
    last_fetched_at TIMESTAMPTZ
);

CREATE TABLE subscriptions (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    feed_id INTEGER REFERENCES feeds(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, feed_id)
);

-- Entries (shared across users, per-user classification)
CREATE TABLE entries (
    id SERIAL PRIMARY KEY,
    feed_id INTEGER REFERENCES feeds(id),
    external_id TEXT,                -- original feed entry ID
    title TEXT,
    url TEXT,
    content TEXT,                    -- original content
    author TEXT,
    published_at TIMESTAMPTZ,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(feed_id, external_id)
);

-- User-specific entry state
CREATE TABLE user_entries (
    id SERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
    source TEXT NOT NULL,            -- 'feed', 'extension', 'newsletter'
    processed_at TIMESTAMPTZ,
    interest TEXT,
    is_signal BOOLEAN,
    reasoning TEXT,
    read_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ,
    UNIQUE(user_id, entry_id)
);

-- Archived content (Firecrawl extraction)
CREATE TABLE archives (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER REFERENCES entries(id) ON DELETE CASCADE,
    markdown TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    embedding VECTOR(1536)           -- for semantic search
);
```

### API Endpoints

**Authentication**
- `POST /auth/register` - Email/password registration
- `POST /auth/login` - Email/password login
- `GET /auth/google` - Google OAuth redirect
- `GET /auth/google/callback` - Google OAuth callback
- `POST /auth/logout` - Logout
- `GET /auth/me` - Current user info

**Feeds**
- `GET /feeds` - List user's subscribed feeds
- `POST /feeds` - Add feed by URL (auto-discovers feed URL)
- `POST /feeds/opml` - Import OPML file
- `DELETE /feeds/{id}` - Unsubscribe from feed

**Entries**
- `GET /entries` - List entries (filters: processed, interest, is_signal, source)
- `GET /entries/{id}` - Get specific entry with archive
- `POST /entries/{id}/read` - Mark as read
- `POST /entries/{id}/archive` - Archive entry content
- `POST /entries/{id}/reprocess` - Re-run classification
- `GET /digest` - Entries grouped by interest
- `POST /save` - Save URL (from extension)

**Newsletter**
- `POST /newsletter/inbound` - Webhook for inbound emails

**Interests**
- `GET /interests` - List user's interests
- `POST /interests` - Add interest
- `PUT /interests/{key}` - Update interest
- `DELETE /interests/{key}` - Delete interest

**Config**
- `GET /config` - Get user config
- `PUT /config` - Update user config

**Search**
- `GET /search` - Semantic search over archives

**Output Feed**
- `GET /feed/{user_token}.xml` - Personal RSS feed of signal entries

**Billing**
- `GET /billing/portal` - Stripe customer portal redirect
- `POST /billing/webhook` - Stripe webhook

**Admin**
- `GET /stats` - User statistics
- `POST /sync` - Manually trigger feed sync

---

## V2 - Growth

### Features

**Acquisition**
- Free trial (14 days, credit card required)
- Multiple pricing tiers (varying storage/article limits)

**Integrations**
- X/Twitter bookmarks sync
- Pocket import

**Engagement**
- Reading analytics (articles read, time saved, topics over time)
- Highlights & annotations
- Weekly email digest of top signal

---

## V3 - Mobile

### Features

**iOS App (Swift)**
- Native reading experience
- Share extension for saving links
- Offline reading (downloaded archives)
- Push notifications for high-signal articles

---

## Future Ideas (Unprioritized)

- Native Android app
- Team/workspace features (shared feeds, collaborative filtering)
- Public sharing of curated feeds
- API for third-party integrations
- Podcast transcript ingestion
- YouTube video transcript ingestion
- Custom classification prompts per interest
- "Teach" button to correct misclassifications
- Email forwarding (forward newsletters from existing address)
- Kindle integration (send to Kindle)
