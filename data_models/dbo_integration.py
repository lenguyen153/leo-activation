"""Data models for data source integration and synchronization settings."""

import uuid
from datetime import datetime, timedelta
from sqlalchemy import String, ForeignKey, Boolean, Interval, UniqueConstraint, Index, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

class DataSource(Base, TimestampMixin):
    __tablename__ = "data_sources"

    source_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    
    source_name: Mapped[str] = mapped_column(String, nullable=False)
    source_type: Mapped[str] = mapped_column(String, nullable=False)
    
    connection_ref: Mapped[str | None] = mapped_column(String)
    sync_frequency: Mapped[timedelta | None] = mapped_column(Interval)
    last_synced_at: Mapped[datetime | None]
    
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    __table_args__ = (
        UniqueConstraint("tenant_id", "source_name", name="uq_tenant_source_name"),
        Index("idx_data_sources_active", "is_active"),
    )