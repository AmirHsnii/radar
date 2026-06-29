from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeadLetterQueue(Base):
    __tablename__ = "dead_letter_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int | None] = mapped_column(ForeignKey("news_items.id", ondelete="SET NULL"))
    stage: Mapped[str] = mapped_column(String(100))
    error_message: Mapped[str] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(50), default="pending", index=True)
    # pending | retrying | resolved | exhausted
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
