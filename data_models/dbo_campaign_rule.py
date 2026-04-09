"""Data models for the Rule-Based Notification Campaign Engine."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class CampaignRule(Base, TimestampMixin):
    """
    A declarative campaign rule evaluated by the campaign engine.
    Conditions are stored as a composable JSONB tree (AND/OR/NOT + leaf predicates).
    """

    __tablename__ = "campaign_rules"

    rule_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[str | None] = mapped_column(String)

    rule_name: Mapped[str] = mapped_column(String, nullable=False)
    rule_description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'paused'")
    )
    priority: Mapped[int] = mapped_column(Integer, server_default=text("100"))

    # Rule definition
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message_templates.template_id", ondelete="SET NULL")
    )
    message_config: Mapped[dict | None] = mapped_column(JSONB)

    # Scheduling & frequency
    frequency_cap: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{\"cooldown_days\": 7, \"max_per_day\": 1}'")
    )
    schedule_cron: Mapped[str] = mapped_column(
        String, server_default=text("'0 * * * *'")
    )
    audience_filter: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("idx_campaign_rules_tenant_status", "tenant_id", "status"),
        Index("idx_campaign_rules_priority", "tenant_id", "priority"),
    )


class CampaignEngineRun(Base):
    """Audit record for each hourly engine execution."""

    __tablename__ = "campaign_engine_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    finished_at: Mapped[datetime | None]

    rules_evaluated: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    profiles_matched: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    sent: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    skipped: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    errored: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    run_metadata: Mapped[dict | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("idx_engine_runs_tenant_time", "tenant_id", "started_at"),
    )
