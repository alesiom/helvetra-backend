"""add_b2b_subscription_product

Revision ID: e5f6a7b8c9d0
Revises: a1b2c3d4e5f6
Create Date: 2026-04-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create subscriptionproduct enum type (uppercase to match SQLAlchemy convention)
    op.execute("CREATE TYPE subscriptionproduct AS ENUM ('CONSUMER', 'B2B')")

    # Add 'STARTER' value to subscriptiontier enum
    op.execute("ALTER TYPE subscriptiontier ADD VALUE IF NOT EXISTS 'STARTER'")

    # Add product column with default 'CONSUMER'
    op.add_column(
        'subscriptions',
        sa.Column(
            'product',
            sa.Enum('CONSUMER', 'B2B', name='subscriptionproduct'),
            nullable=False,
            server_default='CONSUMER',
        ),
    )

    # Backfill all existing subscriptions as CONSUMER
    op.execute("UPDATE subscriptions SET product = 'CONSUMER' WHERE product IS NULL")

    # Add unique index on (user_id, product) to enforce one subscription per product per user
    op.create_index(
        'ix_subscriptions_user_product',
        'subscriptions',
        ['user_id', 'product'],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_subscriptions_user_product', table_name='subscriptions')
    op.drop_column('subscriptions', 'product')
    op.execute("DROP TYPE subscriptionproduct")
    # Note: PostgreSQL does not support removing enum values (starter)
