"""
Subscription database models.
Tracks user subscriptions, usage, and credits across payment providers.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, String, false, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SubscriptionProduct(str, enum.Enum):
    """Product line for the subscription."""

    CONSUMER = "consumer"
    B2B = "b2b"


class SubscriptionTier(str, enum.Enum):
    """Available subscription tiers."""

    FREE = "free"
    PRO = "pro"
    STARTER = "starter"
    BUSINESS = "business"


class SubscriptionStatus(str, enum.Enum):
    """Subscription lifecycle states."""

    ACTIVE = "active"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAST_DUE = "past_due"


class SubscriptionSource(str, enum.Enum):
    """Payment provider for the subscription."""

    PAYREXX = "payrexx"
    APPLE = "apple"
    STRIPE = "stripe"


class Subscription(Base):
    """User subscription for paid features."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    product: Mapped[SubscriptionProduct] = mapped_column(
        Enum(SubscriptionProduct), default=SubscriptionProduct.CONSUMER
    )
    tier: Mapped[SubscriptionTier] = mapped_column(
        Enum(SubscriptionTier), default=SubscriptionTier.FREE
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.ACTIVE
    )
    source: Mapped[SubscriptionSource | None] = mapped_column(
        Enum(SubscriptionSource), nullable=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="subscriptions")

    __table_args__ = (
        Index("ix_subscriptions_user_id", "user_id"),
        Index("ix_subscriptions_user_product", "user_id", "product", unique=True),
        Index("ix_subscriptions_external_id", "external_id"),
    )


class UsagePeriod(Base):
    """Track character usage per billing period."""

    __tablename__ = "usage_periods"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    characters_used: Mapped[int] = mapped_column(BigInteger, default=0)
    characters_limit: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Per-period flags marking which B2B usage-alert emails have already
    # been sent. New periods auto-reset to FALSE so customers get a fresh
    # set of alerts every month.
    alert_80_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    alert_100_sent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false(), default=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_usage_periods_user_id", "user_id"),
        Index("ix_usage_periods_period", "user_id", "period_start", "period_end"),
    )


class CreditBalance(Base):
    """Track top-up credits purchased by users."""

    __tablename__ = "credit_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    balance: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_credit_balances_user_id", "user_id"),)


class CreditTransaction(Base):
    """Log of credit purchases and usage."""

    __tablename__ = "credit_transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(50), nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_credit_transactions_user_id", "user_id"),)


# Import to resolve forward reference
from app.models.user import User  # noqa: E402, F401
