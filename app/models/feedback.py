"""
Feedback database model.
Stores user votes on translations with consent tracking.
"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Feedback(Base):
    """User feedback on a translation."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    translation_id: Mapped[str] = mapped_column(String(100), index=True)
    vote: Mapped[str] = mapped_column(String(10))  # "like" or "dislike"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
