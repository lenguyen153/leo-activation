"""Data models for execution tracking including agent tasks, delivery logs, activation outcomes, message templates, and embedding jobs."""

import uuid
from decimal import Decimal
from datetime import datetime

# Make sure Text is imported
from sqlalchemy import String, ForeignKey, BigInteger, Text, text, Integer, Index, ForeignKeyConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin

class AgentTask(Base):
    """ Represents a task assigned to an AI agent within the system.
    Args:
        Base (_type_): _base class_
    """
    __tablename__ = "agent_task"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    task_id: Mapped[str] = mapped_column(String, primary_key=True, server_default=text("gen_random_uuid()::text"))

    agent_name: Mapped[str] = mapped_column(String, nullable=False)
    task_type: Mapped[str] = mapped_column(String, nullable=False)
    task_goal: Mapped[str | None] = mapped_column(String)

    campaign_id: Mapped[str | None] = mapped_column(String)
    event_id: Mapped[str | None] = mapped_column(String)
    snapshot_id: Mapped[str | None] = mapped_column(String)
    
    related_news_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("news_feed.news_id"))

    # Fixed: Use Text type. Removed nullable=False to match "str | None" type hint and SQL default
    reasoning_summary: Mapped[str | None] = mapped_column(Text)
    reasoning_trace: Mapped[dict | None] = mapped_column(JSONB)

    status: Mapped[str] = mapped_column(String, server_default=text("'pending'"))
    # Fixed: Use Text type. Removed nullable=False to match "str | None" type hint
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    completed_at: Mapped[datetime | None]

    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["campaign.tenant_id", "campaign.campaign_id"],
            ondelete="SET NULL",
            name="fk_agent_task_campaign"
        ),
    )

class DeliveryLog(Base):
    """ Log of message deliveries for campaigns and events. """
    __tablename__ = "delivery_log"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    delivery_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    
    campaign_id: Mapped[str | None] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    
    profile_id: Mapped[str] = mapped_column(String, nullable=False)
    
    channel: Mapped[str] = mapped_column(String, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String, nullable=False)
    provider_response: Mapped[dict | None] = mapped_column(JSONB)
    
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

class ActivationOutcome(Base):
    """ 
        Links a specific delivery to a concrete user outcome.
        This table is append-only and represents attribution truth.
        e.g: This activation of delivery (email / push / message) is credited with this outcome.
    Args:
        Base (_type_): _base class_
    """
    __tablename__ = "activation_outcomes"

    outcome_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    
    delivery_id: Mapped[int] = mapped_column(ForeignKey("delivery_log.delivery_id", ondelete="CASCADE"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey("cdp_profiles.profile_id", ondelete="CASCADE"), nullable=False)
    
    outcome_type: Mapped[str] = mapped_column(String, nullable=False)
    outcome_value: Mapped[Decimal | None]
    
    occurred_at: Mapped[datetime] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

    __table_args__ = (
        Index("idx_outcomes_tenant_delivery", "tenant_id", "delivery_id"),
        Index("idx_outcomes_profile_time", "profile_id", "occurred_at"),
    )

class MessageTemplate(Base, TimestampMixin):
    """ template to send messages

    Args:
        Base (_type_): _description_
        TimestampMixin (_type_): _description_
    """
    
    __tablename__ = "message_templates"

    template_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    
    channel: Mapped[str] = mapped_column(String, nullable=False)
    template_name: Mapped[str] = mapped_column(String, nullable=False)
    
    # FIX: Changed mapped_column(text("TEXT")) to mapped_column(Text)
    subject_template: Mapped[str | None] = mapped_column(Text)
    # FIX: Changed mapped_column(text("TEXT"), ...) to mapped_column(Text, ...)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    
    template_engine: Mapped[str] = mapped_column(String, server_default=text("'jinja2'"))
    language_code: Mapped[str | None] = mapped_column(String, default="vi")
    
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'"))
    status: Mapped[str] = mapped_column(String, default="draft")
    version: Mapped[int] = mapped_column(Integer, default=1)

    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "template_name", "version", name="uq_template_name_version"),
        Index("idx_message_templates_channel", "channel"),
    )

class EmbeddingJob(Base):
    """ Create a table to track embedding jobs for events.

    Args:
        Base (_type_): _description_
    """
    __tablename__ = "embedding_job"

    job_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    event_id: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, server_default=text("'pending'"))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))