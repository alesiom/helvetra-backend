"""
Translation request and response schemas.
"""

from typing import Any
from pydantic import BaseModel, Field


class TranslateRequest(BaseModel):
    """Incoming translation request."""

    text: str = Field(..., min_length=1, max_length=5000)
    source_lang: str = Field(..., min_length=2, max_length=3)
    target_lang: str = Field(..., min_length=2, max_length=3)


class TranslateResponse(BaseModel):
    """Translation response with result or error."""

    success: bool
    data: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    error: dict[str, str] | None = None
