"""
Audit logging for security-relevant events.
Logs authentication events without exposing sensitive data.
"""

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# Configure audit logger
audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)

# Create handler if not already configured
if not audit_logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - AUDIT - %(levelname)s - %(message)s"))
    audit_logger.addHandler(handler)


class AuthEvent(str, Enum):
    """Authentication event types."""

    REGISTER_SUCCESS = "register_success"
    REGISTER_FAILED = "register_failed"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    TOKEN_REFRESH = "token_refresh"
    ACCOUNT_LOCKED = "account_locked"
    ACCOUNT_DELETED = "account_deleted"
    RATE_LIMITED = "rate_limited"


def log_auth_event(
    event: AuthEvent,
    ip_address: str,
    email: str | None = None,
    user_agent: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Log an authentication event.
    Never logs passwords or tokens.
    """
    # Mask email for privacy (show first 2 chars and domain)
    masked_email = None
    if email:
        parts = email.split("@")
        if len(parts) == 2:
            masked_email = f"{parts[0][:2]}***@{parts[1]}"

    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event.value,
        "ip": ip_address,
        "email": masked_email,
        "user_agent": user_agent[:100] if user_agent else None,  # Truncate long UAs
    }

    if details:
        # Filter out any sensitive fields that might accidentally be passed
        safe_details = {
            k: v
            for k, v in details.items()
            if k not in ("password", "token", "refresh_token", "access_token")
        }
        log_data["details"] = safe_details

    audit_logger.info(str(log_data))
