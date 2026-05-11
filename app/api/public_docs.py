"""
Filtered OpenAPI schema and hosted documentation pages for the public
B2B API.

The main FastAPI app exposes both the consumer endpoints (JWT auth)
and the public B2B endpoints (API key auth). For B2B customers we
want documentation that shows only the public surface and only the
auth scheme that applies to them. This module attaches a separate
OpenAPI generator and Swagger UI / ReDoc pages under
`/api/public/v1/*`.
"""

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse

PUBLIC_API_PREFIX = "/api/public/v1"
PUBLIC_API_TAG = "Public API"

PUBLIC_OPENAPI_PATH = f"{PUBLIC_API_PREFIX}/openapi.json"
PUBLIC_SWAGGER_PATH = f"{PUBLIC_API_PREFIX}/docs"
PUBLIC_REDOC_PATH = f"{PUBLIC_API_PREFIX}/redoc"


def _build_public_openapi_schema(app: FastAPI) -> dict[str, Any]:
    """
    Generate an OpenAPI schema containing only public B2B routes, with
    the X-API-Key security scheme attached as the default auth method.
    """
    full = get_openapi(
        title="Helvetra Public API",
        version=app.version,
        description=(
            "Swiss translation API. Authenticate with the `X-API-Key` "
            "header — generate keys from your account page once you have "
            "an active B2B subscription. See <https://helvetra.ch/developers> "
            "for pricing and an interactive quickstart."
        ),
        routes=app.routes,
    )

    # Keep only paths under the public prefix.
    full["paths"] = {
        path: ops
        for path, ops in full.get("paths", {}).items()
        if path.startswith(PUBLIC_API_PREFIX)
    }

    # Replace any inherited security schemes with X-API-Key only.
    components = full.setdefault("components", {})
    components["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": (
                "Pass your Helvetra API key in the X-API-Key header. Keys "
                "begin with `hv_live_` and are tied to an account with an "
                "active B2B subscription."
            ),
        }
    }
    full["security"] = [{"ApiKeyAuth": []}]

    # Surface the production base URL for "Try it out" in Swagger UI.
    full["servers"] = [{"url": "https://helvetra.ch", "description": "Production"}]

    # Drop tags that don't appear in the filtered paths to keep the sidebar tidy.
    used_tags = set()
    for ops in full["paths"].values():
        for op in ops.values():
            for tag in op.get("tags", []) or []:
                used_tags.add(tag)
    full["tags"] = [t for t in full.get("tags", []) if t["name"] in used_tags]

    return full


def install_public_docs(app: FastAPI) -> None:
    """
    Attach the public OpenAPI JSON endpoint plus Swagger UI and ReDoc
    pages to the given FastAPI app. Call once at app startup.

    The endpoints are mounted on a dedicated router so they show up
    under the same `/api/public/v1` prefix as the API itself, which
    means nginx already proxies them correctly.
    """
    router = APIRouter(prefix=PUBLIC_API_PREFIX, include_in_schema=False)

    @router.get("/openapi.json")
    async def public_openapi() -> JSONResponse:
        """Return the filtered public OpenAPI schema."""
        return JSONResponse(_build_public_openapi_schema(app))

    @router.get("/docs", response_class=HTMLResponse)
    async def public_swagger() -> HTMLResponse:
        """Serve Swagger UI for the public API."""
        return get_swagger_ui_html(
            openapi_url=PUBLIC_OPENAPI_PATH,
            title="Helvetra Public API — Reference",
        )

    @router.get("/redoc", response_class=HTMLResponse)
    async def public_redoc() -> HTMLResponse:
        """Serve ReDoc for the public API."""
        return get_redoc_html(
            openapi_url=PUBLIC_OPENAPI_PATH,
            title="Helvetra Public API — Reference",
        )

    app.include_router(router)
