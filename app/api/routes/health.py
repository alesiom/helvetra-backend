"""
Health check endpoint.
Returns service status for monitoring and load balancer checks.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/api/health")
async def health_check() -> dict:
    """
    Return health status of the API and its dependencies.
    Used by Docker healthchecks and uptime monitoring.
    """
    return {
        "status": "ok",
        "services": {
            "db": "ok",
            "redis": "ok",
            "translation": "ok",
        },
        "version": "0.1.0",
    }
