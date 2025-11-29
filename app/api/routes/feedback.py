"""
Feedback endpoint.
Handles user feedback (like/dislike) on translations.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.feedback import Feedback
from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
) -> FeedbackResponse:
    """
    Store user feedback on a translation.
    Only stores data if user has given consent.
    """
    if not request.consent:
        return FeedbackResponse(
            success=False,
            error={"code": "CONSENT_REQUIRED", "message": "User consent is required"},
        )

    feedback = Feedback(
        translation_id=request.translation_id,
        vote=request.vote,
    )
    db.add(feedback)

    return FeedbackResponse(success=True)
