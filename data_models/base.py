import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import MetaData, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry

# Define naming convention for constraints to ensure migration consistency
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=convention)
    
    # Enable type annotation map for common postgres types across all models
    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[dict[str, Any]]: JSONB,
        list[str]: JSONB,
        uuid.UUID: UUID(as_uuid=True),
    }

class TimestampMixin:
    """Mixin to add created_at and updated_at columns."""
    
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), 
        server_default=func.now(), 
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), 
        server_default=func.now(), 
        onupdate=func.now(),
        nullable=False
    )

class TenantMixin:
    """Mixin to add tenant_id to tables."""
    
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        # Note: Foreign key is usually defined explicitly in the model 
        # to allow custom ondelete rules, but this serves as the type definition.
    )