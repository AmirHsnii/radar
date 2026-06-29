from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

GENERATION_MODE_FULL = "full"
GENERATION_MODE_SUMMARY_ONLY = "summary_only"


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    title_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    content: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(10))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"))
    status: Mapped[str] = mapped_column(
        String(50), default="pending", index=True
    )
    # pending → fetched → translated → summarized → classified → published | failed
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # AI outputs
    title_fa: Mapped[str | None] = mapped_column(String(500))
    summary_fa: Mapped[str | None] = mapped_column(Text)
    sentiment: Mapped[str | None] = mapped_column(String(20))
    # JSON arrays: ["BTC","ETH"] / ["DeFi","بازار"]
    coins_json: Mapped[str | None] = mapped_column(Text)
    categories_json: Mapped[str | None] = mapped_column(Text)
    wp_post_id: Mapped[int | None] = mapped_column(Integer)
    processing_cost_usd: Mapped[float | None] = mapped_column()
    pipeline_stages_json: Mapped[str | None] = mapped_column(Text)
    # full = extracted from article page; summary_only = fetch failed, LLM used title/RSS excerpt
    generation_mode: Mapped[str | None] = mapped_column(String(20))
