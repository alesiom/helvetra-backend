"""
CSRF protection for cookie-authenticated state-changing endpoints.

Pattern: double-submit cookie. A non-HttpOnly csrf_token cookie is set
alongside the HttpOnly refresh_token cookie. State-changing requests must
echo the cookie value back in an X-CSRF-Token header — a cross-origin
attacker cannot read the cookie (Same-Origin Policy) and therefore cannot
fake the header. See helvetra/backend#110.

Only enforced when the request actually carries a refresh_token cookie.
Bearer-token-only requests (mobile clients, API key callers) are unaffected
because the browser does not auto-send those credentials.
"""

import hmac
import secrets

from fastapi import HTTPException, Request, Response, status

from app.config import get_settings

settings = get_settings()

CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_COOKIE_PATH = "/api/v1/auth"


def issue_csrf_token() -> str:
    """Return a fresh CSRF token value."""
    return secrets.token_urlsafe(32)


def set_csrf_cookie(response: Response, token: str, max_age_seconds: int) -> None:
    """Attach the csrf_token cookie to a response (must be JS-readable)."""
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,  # JS must be able to read it to echo into the header
        secure=not settings.debug,
        samesite="strict",
        max_age=max_age_seconds,
        path=CSRF_COOKIE_PATH,
    )


def clear_csrf_cookie(response: Response) -> None:
    """Remove the csrf_token cookie (e.g. on logout)."""
    response.delete_cookie(key=CSRF_COOKIE_NAME, path=CSRF_COOKIE_PATH)


def require_csrf(request: Request) -> None:
    """
    FastAPI dependency. Enforce double-submit CSRF on cookie-authenticated
    requests. No-op when the request has no refresh_token cookie — Bearer-
    auth flows are not exposed to CSRF.
    """
    if "refresh_token" not in request.cookies:
        return  # not a cookie-authenticated request

    cookie_value = request.cookies.get(CSRF_COOKIE_NAME, "")
    header_value = request.headers.get(CSRF_HEADER_NAME, "")

    if not cookie_value or not header_value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing CSRF token",
        )

    if not hmac.compare_digest(cookie_value, header_value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )
