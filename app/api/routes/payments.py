"""
Payment endpoints.
Handles checkout session creation for subscription purchases.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.stripe_service import create_checkout_session

router = APIRouter(prefix="/payments")


class CreateGatewayRequest(BaseModel):
    """Request to create a payment gateway."""

    billing_period: str  # "monthly" or "yearly"


class CreateGatewayResponse(BaseModel):
    """Response with gateway URL."""

    success: bool
    gateway_url: str | None = None
    error: str | None = None


@router.post("/create-gateway", response_model=CreateGatewayResponse)
async def create_payment_gateway(
    request: CreateGatewayRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreateGatewayResponse:
    """Create a Stripe Checkout Session for subscription purchase."""
    if request.billing_period not in ("monthly", "yearly"):
        raise HTTPException(
            status_code=400,
            detail="Invalid billing period. Must be 'monthly' or 'yearly'.",
        )

    result = await create_checkout_session(
        db=db,
        user=user,
        billing_period=request.billing_period,
    )

    if not result.success:
        return CreateGatewayResponse(
            success=False,
            error=result.error,
        )

    return CreateGatewayResponse(
        success=True,
        gateway_url=result.gateway_url,
    )
