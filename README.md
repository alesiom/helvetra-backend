# Helvetra Backend

Translation API for Helvetra.

## Requirements

- Python 3.11+
- Docker & Docker Compose

## Local Development

```bash
# Start all services
docker-compose up

# API available at http://localhost:8000
# Docs available at http://localhost:8000/docs (debug mode only)
```

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

## Environment Variables

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/v1/languages` | List supported languages |
| POST | `/api/v1/translate` | Translate text |
| POST | `/api/v1/feedback` | Submit feedback |
