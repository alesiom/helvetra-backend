"""
Payment endpoints.
Handles payment gateway creation for subscription purchases.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.dependencies import get_current_user
from app.models.user import User
from app.services.payrexx import create_gateway

router = APIRouter(prefix="/payments")

# Subscription pricing in cents
PRICES = {
    "monthly": 799,   # CHF 7.99
    "yearly": 5988,   # CHF 59.88 (CHF 4.99/month)
}

# Redirect URLs
BASE_URL = "https://helvetra.ch"
SUCCESS_URL = f"{BASE_URL}/pricing/success"
FAILED_URL = f"{BASE_URL}/pricing/cancel"
CANCEL_URL = f"{BASE_URL}/pricing/cancel"


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
) -> CreateGatewayResponse:
    """
    Create a Payrexx payment gateway for subscription purchase.

    Requires authentication. Returns a gateway URL for the user to complete payment.
    """
    if request.billing_period not in PRICES:
        raise HTTPException(
            status_code=400,
            detail="Invalid billing period. Must be 'monthly' or 'yearly'.",
        )

    amount = PRICES[request.billing_period]

    result = await create_gateway(
        amount=amount,
        currency="CHF",
        billing_period=request.billing_period,
        user_email=user.email,
        success_url=SUCCESS_URL,
        failed_url=FAILED_URL,
        cancel_url=CANCEL_URL,
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
