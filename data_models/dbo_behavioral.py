"""Data model for storing behavioral events associated with user profiles."""

import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, BigInteger, text, Integer, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class BehavioralEvent(Base):
    __tablename__ = "behavioral_events"
    __table_args__ = (
        Index("idx_behavioral_profile_time", "profile_id", text("created_at DESC")),
        Index("idx_behavioral_entity", "entity_type", "entity_id"),
        {"postgresql_partition_by": "RANGE (created_at)"}
    )

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey("cdp_profiles.profile_id", ondelete="CASCADE"), nullable=False)
    
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    
    entity_type: Mapped[str | None] = mapped_column(String)
    entity_id: Mapped[str | None] = mapped_column(String)
    
    sentiment_val: Mapped[int | None] = mapped_column(Integer, default=0)
    meta_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))
    
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False, primary_key=True)