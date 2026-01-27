"""Data models for alerting system including instruments, market snapshots, alert rules, and news feeds."""

import uuid
import enum
from decimal import Decimal
from datetime import datetime

from sqlalchemy import String, ForeignKey, Numeric, BigInteger, Enum, ARRAY, Index, UniqueConstraint, text, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .base import Base, TimestampMixin

class AlertSourceEnum(enum.Enum):
    USER_MANUAL = "USER_MANUAL"
    AI_AGENT = "AI_AGENT"

class AlertStatusEnum(enum.Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TRIGGERED = "TRIGGERED"

class Instrument(Base, TimestampMixin):
    __tablename__ = "instruments"

    instrument_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"))
    
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    # FIX: Use Text type, not text("TEXT")
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type_: Mapped[str] = mapped_column("type", String(50), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    meta_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    __table_args__ = (
        UniqueConstraint("tenant_id", "symbol", name="uq_instrument_symbol"),
    )

class MarketSnapshot(Base):
    __tablename__ = "market_snapshot"

    symbol: Mapped[str] = mapped_column(String(20), primary_key=True)
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 5))
    change_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    last_updated: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rules"

    rule_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), primary_key=True)
    
    profile_id: Mapped[str] = mapped_column(ForeignKey("cdp_profiles.profile_id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    
    alert_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[AlertSourceEnum] = mapped_column(Enum(AlertSourceEnum), default=AlertSourceEnum.USER_MANUAL)
    
    condition_logic: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[AlertStatusEnum] = mapped_column(Enum(AlertStatusEnum), default=AlertStatusEnum.ACTIVE)
    frequency: Mapped[str | None] = mapped_column(String(50), default="ONCE")

    __table_args__ = (
        Index("idx_alert_rules_worker", "symbol", "status", postgresql_where=text("status = 'ACTIVE'")),
    )

class NewsFeed(Base):
    __tablename__ = "news_feed"

    news_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"))
    
    # FIX: Use Text type
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    
    related_symbols: Mapped[list[str] | None] = mapped_column(ARRAY(String))
    sentiment_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    
    content_embedding: Mapped[Vector] = mapped_column(Vector(1536))
    published_at: Mapped[datetime | None] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index(
            "idx_news_embedding",
            "content_embedding",
            postgresql_using="hnsw",
            postgresql_ops={"content_embedding": "vector_cosine_ops"}
        ),
    )