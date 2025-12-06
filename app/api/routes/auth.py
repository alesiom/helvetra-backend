"""
Authentication endpoints.
Handles user registration, login, token refresh, and logout.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user
from app.config import get_settings
from app.core.database import get_db
from app.models.user import RefreshToken, User
from app.schemas.auth import (
    AuthResponse,
    LoginRequest,
    MessageResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    get_refresh_token_expiry,
    hash_password,
    hash_refresh_token,
    verify_password,
)

settings = get_settings()
router = APIRouter(prefix="/auth")


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Register a new user with email and password."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == request.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Create user
    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
    )
    db.add(user)
    await db.flush()

    # Create tokens
    access_token = create_access_token(user.id)
    raw_refresh, hashed_refresh = create_refresh_token()

    refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=get_refresh_token_expiry(),
    )
    db.add(refresh_token)

    return AuthResponse(
        success=True,
        data={
            "user": UserResponse(
                id=user.id,
                email=user.email,
                email_verified=user.email_verified,
            ).model_dump(),
            "tokens": TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
                expires_in=settings.access_token_expire_minutes * 60,
            ).model_dump(),
        },
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Authenticate user with email and password."""
    result = await db.execute(select(User).where(User.email == request.email))
    user = result.scalar_one_or_none()

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Create tokens
    access_token = create_access_token(user.id)
    raw_refresh, hashed_refresh = create_refresh_token()

    refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=get_refresh_token_expiry(),
    )
    db.add(refresh_token)

    return AuthResponse(
        success=True,
        data={
            "user": UserResponse(
                id=user.id,
                email=user.email,
                email_verified=user.email_verified,
            ).model_dump(),
            "tokens": TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
                expires_in=settings.access_token_expire_minutes * 60,
            ).model_dump(),
        },
    )


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> AuthResponse:
    """Exchange a refresh token for new access and refresh tokens."""
    token_hash = hash_refresh_token(request.refresh_token)

    result = await db.execute(
        select(RefreshToken)
        .where(RefreshToken.token_hash == token_hash)
        .where(RefreshToken.revoked == False)  # noqa: E712
    )
    stored_token = result.scalar_one_or_none()

    if not stored_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Check expiry
    from datetime import datetime, timezone

    if stored_token.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token expired",
        )

    # Revoke old token (rotation)
    stored_token.revoked = True

    # Get user
    user_result = await db.execute(select(User).where(User.id == stored_token.user_id))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    # Create new tokens
    access_token = create_access_token(user.id)
    raw_refresh, hashed_refresh = create_refresh_token()

    new_refresh_token = RefreshToken(
        user_id=user.id,
        token_hash=hashed_refresh,
        expires_at=get_refresh_token_expiry(),
    )
    db.add(new_refresh_token)

    return AuthResponse(
        success=True,
        data={
            "tokens": TokenResponse(
                access_token=access_token,
                refresh_token=raw_refresh,
                expires_in=settings.access_token_expire_minutes * 60,
            ).model_dump(),
        },
    )


@router.post("/logout", response_model=MessageResponse)
async def logout(
    request: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> MessageResponse:
    """Revoke a refresh token to log out."""
    token_hash = hash_refresh_token(request.refresh_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    stored_token = result.scalar_one_or_none()

    if stored_token:
        stored_token.revoked = True

    return MessageResponse(success=True, message="Logged out successfully")


@router.get("/me", response_model=AuthResponse)
async def me(
    current_user: User = Depends(get_current_user),
) -> AuthResponse:
    """Get current authenticated user profile."""
    return AuthResponse(
        success=True,
        data={
            "user": UserResponse(
                id=current_user.id,
                email=current_user.email,
                email_verified=current_user.email_verified,
            ).model_dump(),
        },
    )
