"""webhook_events.payload to JSONB

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-05-19
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Existing rows are valid JSON strings, so the USING cast just parses them."""
    op.alter_column(
        "webhook_events",
        "payload",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        postgresql_using="payload::jsonb",
    )


def downgrade() -> None:
    op.alter_column(
        "webhook_events",
        "payload",
        existing_type=postgresql.JSONB(),
        type_=sa.Text(),
        existing_nullable=False,
        postgresql_using="payload::text",
    )
