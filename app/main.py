"""
API entry point.
Initializes the app with middleware and routes.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api.routes import health, languages, translate, feedback

settings = get_settings()

app = FastAPI(
    title="Helvetra API",
    description="Swiss translation API",
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(languages.router, prefix="/api/v1", tags=["Languages"])
app.include_router(translate.router, prefix="/api/v1", tags=["Translation"])
app.include_router(feedback.router, prefix="/api/v1", tags=["Feedback"])
