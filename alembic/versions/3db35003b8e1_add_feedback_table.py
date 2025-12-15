"""add_feedback_table

Revision ID: 3db35003b8e1
Revises: d4b5c6e7f8a9
Create Date: 2025-12-15 14:53:48.447801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3db35003b8e1'
down_revision: Union[str, Sequence[str], None] = 'd4b5c6e7f8a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create feedback table for storing user votes on translations."""
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('vote', sa.String(10), nullable=False),
        sa.Column('source_text', sa.Text(), nullable=False),
        sa.Column('source_lang', sa.String(5), nullable=False),
        sa.Column('translated_text', sa.Text(), nullable=False),
        sa.Column('target_lang', sa.String(5), nullable=False),
        sa.Column('region', sa.String(20), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )


def downgrade() -> None:
    """Drop feedback table."""
    op.drop_table('feedback')
