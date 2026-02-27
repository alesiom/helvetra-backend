# Helvetra Backend

Translation API powering [Helvetra](https://helvetra.ch), a privacy-first Swiss translation app.

## Features

- Translation API powered by Swiss AI (Apertus-70B)
- Swiss German dialect support (Zurich, Bern, Basel, Luzern, St. Gallen, Wallis)
- Auto-detect source language
- Formality toggle (du/Sie, tu/vous, tu/Lei)
- Prompt injection protection
- Rate limiting and tiered usage tracking
- Sign in with Apple authentication
- StoreKit 2 subscription verification
- Email verification with multilingual templates

## Tech Stack

- **Framework:** Python 3.11+ / FastAPI
- **Database:** PostgreSQL 15 + SQLAlchemy + Alembic
- **Cache:** Redis
- **AI:** Apertus-70B via Infomaniak AI API
- **Auth:** JWT + Sign in with Apple
- **Payments:** Payrexx (web) + Apple StoreKit 2 (iOS)

## Setup

```bash
# Clone and configure
cp .env.example .env
# Edit .env with your values

# Start with Docker
docker-compose up

# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/translate` | Translate text |
| GET | `/api/v1/languages` | List supported languages |
| POST | `/api/v1/feedback` | Submit translation feedback |
| GET | `/api/v1/subscription` | Get subscription status |
| GET | `/api/v1/subscription/limits` | Get tier limits |
| GET | `/api/health` | Health check |

## Supported Languages

| Code | Language |
|------|----------|
| de | German |
| gsw | Swiss German (with regional dialects) |
| fr | French |
| it | Italian |
| en | English |
| rm | Romansh |

## Project Structure

```
app/
├── main.py          # Application entry point
├── config.py        # Environment configuration
├── api/routes/      # API endpoints
├── schemas/         # Request/response models
├── services/        # Business logic
├── models/          # Database models
└── core/            # Utilities and middleware
```

## License

MIT
