"""Add webhook_events table for idempotency and audit.

Revision ID: d4b5c6e7f8a9
Revises: c3a8f2e91d7a
Create Date: 2025-12-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4b5c6e7f8a9"
down_revision: str | None = "c3a8f2e91d7a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("event_id", sa.String(255), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("processed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_events_source_event_id",
        "webhook_events",
        ["source", "event_id"],
        unique=True,
    )
    op.create_index(
        "ix_webhook_events_created_at",
        "webhook_events",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_created_at", table_name="webhook_events")
    op.drop_index("ix_webhook_events_source_event_id", table_name="webhook_events")
    op.drop_table("webhook_events")
