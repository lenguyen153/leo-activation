"""Data models for campaign management including campaigns, marketing events, and activation experiments."""

import uuid
from datetime import datetime
from sqlalchemy import Index, String, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from sqlalchemy import text
from sqlalchemy import ForeignKeyConstraint

from .base import Base, TimestampMixin

class Campaign(Base, TimestampMixin):
    __tablename__ = "campaign"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), 
        primary_key=True
    )
    campaign_id: Mapped[str] = mapped_column(
        String, 
        primary_key=True, 
        server_default=text("gen_random_uuid()::text")
    )
    
    campaign_code: Mapped[str] = mapped_column(String, nullable=False)
    campaign_name: Mapped[str] = mapped_column(String, nullable=False)
    objective: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default=text("'active'"))
    
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_code", name="uq_campaign_code"),
    )

class MarketingEvent(Base, TimestampMixin):
    """
    Note: This is partitioned by HASH(tenant_id) in SQL.
    SQLAlchemy 2.0 supports declaring partition options, but schema creation usually 
    relies on manual DDL for partitions.
    """
    __tablename__ = "marketing_event"
    __table_args__ = (
        {"postgresql_partition_by": "HASH (tenant_id)"},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), 
        primary_key=True
    )
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    
    # We use a composite foreign key referencing campaign
    campaign_id: Mapped[str | None] = mapped_column(String)
    
    event_name: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    event_channel: Mapped[str] = mapped_column(String, nullable=False)
    
    start_at: Mapped[datetime]
    end_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(String, server_default=text("'planned'"))
    
    embedding: Mapped[Vector] = mapped_column(Vector(1536))
    embedding_status: Mapped[str] = mapped_column(String, server_default=text("'pending'"))

    # Explicit FK definition for composite key
    # Note: ForeignKeyConstraint in __table_args__ is preferred for composite keys
    # But mapped_column ForeignKey works if the target is clear. 
    # Given the SQL defines: CONSTRAINT fk_marketing_event_campaign FOREIGN KEY (tenant_id, campaign_id) ...
    # We define it in __table_args__ below to matches SQL exactly.

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaign.tenant_id", "campaign.campaign_id"],
            ondelete="SET NULL",
            name="fk_marketing_event_campaign"
        ),
        {"postgresql_partition_by": "HASH (tenant_id)"}
    )


class ActivationExperiment(Base, TimestampMixin):
    __tablename__ = "activation_experiments"

    experiment_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"))
    
    campaign_id: Mapped[str] = mapped_column(String, nullable=False)
    variant_name: Mapped[str] = mapped_column(String, nullable=False)
    
    exposure_count: Mapped[int] = mapped_column(default=0)
    conversion_count: Mapped[int] = mapped_column(default=0)
    
    metric_name: Mapped[str | None]
    started_at: Mapped[datetime | None]
    ended_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("tenant_id", "campaign_id", "variant_name", name="uq_experiment_variant"),
        Index("idx_experiments_campaign", "tenant_id", "campaign_id"),
    )