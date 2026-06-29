from datetime import datetime
from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    rss_url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    site_url: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(10), default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    poll_interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_poll_status: Mapped[str | None] = mapped_column(String(20))
    last_poll_new_items: Mapped[int | None] = mapped_column(Integer)
    last_poll_message: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
