"""Data models for Customer Data Platform (CDP) profiles and consent management."""

from sqlalchemy import text
from datetime import datetime
import uuid
from decimal import Decimal
from sqlalchemy import String, ForeignKey, UniqueConstraint, Index, Numeric, CheckConstraint
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from .base import Base, TimestampMixin


class CdpProfile(Base, TimestampMixin):
    __tablename__ = "cdp_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"),
        primary_key=True  # Part of logic, though SQL defines profile_id as PK, RLS relies on this
    )
    profile_id: Mapped[str] = mapped_column(String, primary_key=True)

    identities: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))

    # Contact Info
    primary_email: Mapped[str | None] = mapped_column(CITEXT)
    secondary_emails: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    primary_phone: Mapped[str | None] = mapped_column(String)
    secondary_phones: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))

    # Personal
    first_name: Mapped[str | None] = mapped_column(String)
    last_name: Mapped[str | None] = mapped_column(String)
    living_location: Mapped[str | None] = mapped_column(String)
    living_country: Mapped[str | None] = mapped_column(String)
    living_city: Mapped[str | None] = mapped_column(String)

    # Enrichment
    job_titles: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    data_labels: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    content_keywords: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    media_channels: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    behavioral_events_list: Mapped[list[str]] = mapped_column(
        "behavioral_events", JSONB, server_default=text("'[]'"))

    # Segmentation & Journey
    segments: Mapped[list[dict]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    journey_maps: Mapped[list[dict]] = mapped_column(
        JSONB, server_default=text("'[]'"))
    segment_snapshots: Mapped[list[dict]] = mapped_column(
        JSONB, server_default=text("'[]'"))

    # Stats
    event_statistics: Mapped[dict] = mapped_column(
        JSONB, server_default=text("'{}'"))
    top_engaged_touchpoints: Mapped[list[dict]] = mapped_column(
        JSONB, server_default=text("'[]'"))

    # Portfolio
    portfolio_snapshot: Mapped[dict | None] = mapped_column(
        JSONB, server_default=text("'{}'"))
    portfolio_risk_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    portfolio_last_evaluated_at: Mapped[datetime | None]

    # AI Memory
    interest_embedding: Mapped[Vector] = mapped_column(Vector(1536))

    ext_data: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'"))

    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id",
                         name="uq_cdp_profile_identity"),
        Index("idx_cdp_profiles_primary_email", "tenant_id", "primary_email"),
        Index("idx_cdp_profiles_identities",
              "identities", postgresql_using="gin"),
        Index("idx_cdp_profiles_segments", "segments", postgresql_using="gin",
              postgresql_ops={"segments": "jsonb_path_ops"}),
    )


class ConsentManagement(Base, TimestampMixin):
    __tablename__ = "consent_management"

    consent_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(
        "tenant.tenant_id", ondelete="CASCADE"), nullable=False)
    profile_id: Mapped[str] = mapped_column(ForeignKey(
        "cdp_profiles.profile_id", ondelete="CASCADE"), nullable=False)

    channel: Mapped[str] = mapped_column(String, nullable=False)
    is_allowed: Mapped[bool] = mapped_column(server_default=text("false"))
    source: Mapped[str | None] = mapped_column(String)
    legal_basis: Mapped[str | None] = mapped_column(String)

    __table_args__ = (
        UniqueConstraint("tenant_id", "profile_id", "channel",
                         name="uq_consent_profile_channel"),
        Index("idx_consent_tenant_profile", "tenant_id", "profile_id"),
    )
