"""add_email_verification_tokens_table

Revision ID: c3a8f2e91d7a
Revises: b9c9f076fcbe
Create Date: 2025-12-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3a8f2e91d7a'
down_revision: Union[str, Sequence[str], None] = 'b9c9f076fcbe'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create email_verification_tokens table."""
    op.create_table('email_verification_tokens',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('token_hash', sa.String(length=255), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('used', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_email_verification_tokens_token_hash', 'email_verification_tokens', ['token_hash'], unique=False)
    op.create_index('ix_email_verification_tokens_user_id', 'email_verification_tokens', ['user_id'], unique=False)


def downgrade() -> None:
    """Drop email_verification_tokens table."""
    op.drop_index('ix_email_verification_tokens_user_id', table_name='email_verification_tokens')
    op.drop_index('ix_email_verification_tokens_token_hash', table_name='email_verification_tokens')
    op.drop_table('email_verification_tokens')
