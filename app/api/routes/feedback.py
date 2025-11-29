"""
Feedback endpoint.
Handles user feedback (like/dislike) on translations.
"""

from fastapi import APIRouter

from app.schemas.feedback import FeedbackRequest, FeedbackResponse

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """
    Store user feedback on a translation.
    Only stores data if user has given consent.
    """
    if not request.consent:
        return FeedbackResponse(
            success=False,
            error={"code": "CONSENT_REQUIRED", "message": "User consent is required"},
        )

    # TODO: Store feedback in database (Issue #3)
    return FeedbackResponse(success=True)
