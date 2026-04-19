"""
API key management endpoints.
Allows B2B customers to generate, list, revoke, and rotate API keys.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.api_key import (
    create_api_key,
    has_active_b2b_subscription,
    list_api_keys,
    revoke_api_key,
    rotate_api_key,
)

router = APIRouter(prefix="/api-keys")


# --- Schemas ---


class CreateKeyRequest(BaseModel):
    """Request to generate a new API key."""

    name: str = Field(..., min_length=1, max_length=100)


class ApiKeyResponse(BaseModel):
    """API key metadata (never includes the full key)."""

    id: UUID
    name: str
    key_prefix: str
    rate_limit: int
    last_used_at: str | None
    created_at: str

    model_config = {"from_attributes": True}


class ApiKeyCreatedResponse(ApiKeyResponse):
    """Response after key creation, includes the full key (shown once)."""

    key: str


# --- Helpers ---


async def _require_b2b(user: User, db: AsyncSession) -> None:
    """Raise 403 if user lacks an active B2B subscription."""
    if not await has_active_b2b_subscription(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active B2B subscription required to manage API keys",
        )


def _key_to_response(api_key) -> ApiKeyResponse:
    """Convert an ApiKey model to its response schema."""
    return ApiKeyResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        rate_limit=api_key.rate_limit,
        last_used_at=api_key.last_used_at.isoformat() if api_key.last_used_at else None,
        created_at=api_key.created_at.isoformat(),
    )


# --- Routes ---


@router.post("", response_model=ApiKeyCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_key(
    request: CreateKeyRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreatedResponse:
    """Generate a new API key. The full key is only shown once in this response."""
    await _require_b2b(user, db)

    try:
        api_key, raw_key = await create_api_key(db, user.id, request.name)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.commit()

    return ApiKeyCreatedResponse(
        id=api_key.id,
        name=api_key.name,
        key_prefix=api_key.key_prefix,
        rate_limit=api_key.rate_limit,
        last_used_at=None,
        created_at=api_key.created_at.isoformat(),
        key=raw_key,
    )


@router.get("", response_model=list[ApiKeyResponse])
async def list_keys(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ApiKeyResponse]:
    """List all active API keys for the authenticated user."""
    await _require_b2b(user, db)
    keys = await list_api_keys(db, user.id)
    return [_key_to_response(k) for k in keys]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Revoke an API key."""
    await _require_b2b(user, db)
    result = await revoke_api_key(db, user.id, key_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )
    await db.commit()


@router.post("/{key_id}/rotate", response_model=ApiKeyCreatedResponse)
async def rotate_key(
    key_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ApiKeyCreatedResponse:
    """Revoke an existing key and generate a new one with the same name."""
    await _require_b2b(user, db)

    result = await rotate_api_key(db, user.id, key_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API key not found or already revoked",
        )

    new_key, raw_key = result
    await db.commit()

    return ApiKeyCreatedResponse(
        id=new_key.id,
        name=new_key.name,
        key_prefix=new_key.key_prefix,
        rate_limit=new_key.rate_limit,
        last_used_at=None,
        created_at=new_key.created_at.isoformat(),
        key=raw_key,
    )
