"""
Feedback request and response schemas.
"""

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """User feedback on a translation."""

    translation_id: str = Field(..., min_length=1)
    vote: str = Field(..., pattern="^(like|dislike)$")
    consent: bool


class FeedbackResponse(BaseModel):
    """Feedback submission response."""

    success: bool
    error: dict[str, str] | None = None
