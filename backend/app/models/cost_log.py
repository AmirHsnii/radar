from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CostLog(Base):
    __tablename__ = "cost_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    news_id: Mapped[int | None] = mapped_column(ForeignKey("news_items.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(200))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    task_name: Mapped[str] = mapped_column(String(100), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
