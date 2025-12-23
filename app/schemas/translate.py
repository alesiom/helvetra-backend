"""
Translation request and response schemas.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

# Supported language codes for translation
SUPPORTED_LANGUAGE_CODES = {"de", "gsw", "fr", "it", "en", "rm"}

# Supported Swiss German dialects
SwissDialect = Literal["bern", "zurich", "basel", "stgallen", "wallis", "luzern"]


class TranslateRequest(BaseModel):
    """Incoming translation request."""

    text: str = Field(..., min_length=1, max_length=1000)
    source_lang: str = Field(..., min_length=2, max_length=4)
    target_lang: str = Field(..., min_length=2, max_length=3)
    formality: Literal["informal", "formal", "auto"] = Field(
        default="auto", description="Formality level for German translations (du/Sie)"
    )
    dialect: SwissDialect | None = Field(
        default=None, description="Swiss German dialect (only used when target_lang is gsw)"
    )


class TranslateResponse(BaseModel):
    """Translation response with result or error."""

    success: bool
    data: dict[str, Any] | None = None
    meta: dict[str, Any] | None = None
    error: dict[str, str] | None = None
