"""add_usage_alert_flags

Adds alert_80_sent and alert_100_sent boolean flags to usage_periods so
the B2B usage-alert email service knows which thresholds have already
fired in the current billing period. New periods get fresh FALSEs.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-05-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'usage_periods',
        sa.Column(
            'alert_80_sent',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        'usage_periods',
        sa.Column(
            'alert_100_sent',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column('usage_periods', 'alert_100_sent')
    op.drop_column('usage_periods', 'alert_80_sent')
