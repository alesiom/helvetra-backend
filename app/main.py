"""
API entry point.
Initializes the app with middleware and routes.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    api_keys,
    auth,
    feedback,
    health,
    languages,
    payments,
    public,
    subscription,
    translate,
    webhooks,
)
from app.config import get_settings
from app.core.middleware import RateLimitMiddleware

settings = get_settings()

app = FastAPI(
    title="Helvetra API",
    description="Swiss translation API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Middleware is processed in reverse order (last added = first executed)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(health.router, tags=["Health"])
app.include_router(auth.router, prefix="/api/v1", tags=["Auth"])
app.include_router(languages.router, prefix="/api/v1", tags=["Languages"])
app.include_router(translate.router, prefix="/api/v1", tags=["Translation"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
app.include_router(subscription.router, prefix="/api/v1", tags=["Subscription"])
app.include_router(payments.router, prefix="/api/v1", tags=["Payments"])
app.include_router(api_keys.router, prefix="/api/v1", tags=["API Keys"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["Webhooks"])

# B2B Public API — separate prefix, API key auth
app.include_router(public.router, prefix="/api/public/v1", tags=["Public API"])
