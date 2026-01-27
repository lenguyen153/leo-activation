"""Data models for segment snapshots and their members."""

import uuid
from datetime import datetime
from sqlalchemy import String, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

class SegmentSnapshot(Base):
    __tablename__ = "segment_snapshot"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"), 
        primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String, 
        primary_key=True, 
        server_default=text("gen_random_uuid()::text")
    )
    
    segment_name: Mapped[str] = mapped_column(String, nullable=False)
    segment_version: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))

class SegmentSnapshotMember(Base):
    __tablename__ = "segment_snapshot_member"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenant.tenant_id", ondelete="CASCADE"),
        primary_key=True
    )
    snapshot_id: Mapped[str] = mapped_column(
        String, primary_key=True
    )
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("cdp_profiles.profile_id", ondelete="CASCADE"),
        primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    
    # Composite FK for snapshot
    from sqlalchemy import ForeignKeyConstraint
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "snapshot_id"],
            ["segment_snapshot.tenant_id", "segment_snapshot.snapshot_id"],
            ondelete="CASCADE",
            name="fk_snapshot_member_snapshot"
        ),
    )