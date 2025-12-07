"""
Health check endpoint.
Returns service status for monitoring and load balancer checks.
"""

import httpx
import redis.asyncio as redis
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.core.database import async_session_maker

router = APIRouter()
settings = get_settings()


async def check_database() -> str:
    """Check database connectivity by running a simple query."""
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"


async def check_redis() -> str:
    """Check Redis connectivity by pinging the server."""
    try:
        client = redis.from_url(settings.redis_url)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception:
        return "error"


async def check_translation_api() -> str:
    """Check translation API availability with a lightweight request."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.apertus_api_base}/models",
                headers={"Authorization": f"Bearer {settings.apertus_api_key}"},
                timeout=5.0,
            )
            return "ok" if response.status_code == 200 else "degraded"
    except Exception:
        return "error"


@router.get("/api/health")
async def health_check() -> dict:
    """
    Return health status of the API and its dependencies.
    Used by Docker healthchecks and uptime monitoring.
    """
    db_status = await check_database()
    redis_status = await check_redis()
    translation_status = await check_translation_api()

    # Overall status is "ok" only if all services are healthy
    services_ok = all(status == "ok" for status in [db_status, redis_status, translation_status])

    return {
        "status": "ok" if services_ok else "degraded",
        "services": {
            "db": db_status,
            "redis": redis_status,
            "translation": translation_status,
        },
        "version": "0.1.0",
    }
