"""
Feedback database model.
Stores user votes on translations with consent tracking.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Feedback(Base):
    """User feedback on a translation."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    vote: Mapped[str] = mapped_column(String(10))  # "like" or "dislike"
    source_text: Mapped[str] = mapped_column(Text)
    source_lang: Mapped[str] = mapped_column(String(5))
    translated_text: Mapped[str] = mapped_column(Text)
    target_lang: Mapped[str] = mapped_column(String(5))
    region: Mapped[str | None] = mapped_column(String(20), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
