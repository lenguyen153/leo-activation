"""
Data model and tenant context utilities.

This module defines:
- Tenant ORM model
- Session-level tenant resolver for PostgreSQL RLS
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Final

import psycopg
from sqlalchemy import String, UniqueConstraint, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from data_utils.settings import DatabaseSettings


from .base import Base, TimestampMixin

# ---------------------------------------------------------------------
# Logging & Constants
# ---------------------------------------------------------------------

logger = logging.getLogger(__name__)

DEFAULT_TENANT_NAME: Final[str] = "master"
TENANT_STATUS_ACTIVE: Final[str] = "active"

# ---------------------------------------------------------------------
# ORM Model
# ---------------------------------------------------------------------

class Tenant(Base, TimestampMixin):
    """
    Tenant represents an isolated logical customer boundary.
    Used in combination with PostgreSQL RLS via `app.current_tenant_id`.
    """

    __tablename__ = "tenant"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    tenant_name: Mapped[str] = mapped_column(
        String,
        nullable=False,
        index=True,
        server_default=text(f"'{DEFAULT_TENANT_NAME}'"),
    )

    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        server_default=text(f"'{TENANT_STATUS_ACTIVE}'"),
    )

    # --------------------------------------------------
    # Keycloak integration
    # --------------------------------------------------

    keycloak_realm: Mapped[str] = mapped_column(String, nullable=False)
    keycloak_client_id: Mapped[str] = mapped_column(String, nullable=False)
    keycloak_org_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # --------------------------------------------------
    # Extensible metadata
    # --------------------------------------------------

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )

    __table_args__ = (
        UniqueConstraint(
            "keycloak_realm",
            "tenant_name",
            name="uq_tenant_keycloak_realm",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Tenant(id={self.tenant_id}, name='{self.tenant_name}', status='{self.status}')>"
        )


# ---------------------------------------------------------------------
# Tenant Context Resolver (PostgreSQL RLS)
# ---------------------------------------------------------------------

def get_default_tenant_id(pg_connection: psycopg.Connection = None) -> uuid.UUID:
    """
    Utility to get the default tenant ID from the database.
    """
    if pg_connection is None:
        # Lazy init connection if not provided
        pg_connection = DatabaseSettings().get_pg_connection()
    
    with pg_connection.cursor() as cursor:
        cursor.execute(
            "SELECT tenant_id FROM tenant WHERE tenant_name = %s",
            (DEFAULT_TENANT_NAME,),
        )
        result = cursor.fetchone()
        if not result:
            raise RuntimeError(f"Default tenant '{DEFAULT_TENANT_NAME}' not found in database.")
        
        return result[0]

def resolve_tenant_id(session: Session, tenant_name: str = DEFAULT_TENANT_NAME) -> uuid.UUID:
    """
    Look up a tenant_id by name within an existing SQL session.
    """
    stmt = select(Tenant.tenant_id).where(Tenant.tenant_name == tenant_name)
    tenant_id = session.scalar(stmt)

    if not tenant_id:
        raise RuntimeError(f"Tenant '{tenant_name}' not found in database.")
    
    return tenant_id


def set_tenant_context(session: Session, tenant_id: uuid.UUID) -> None:
    """
    Binds the tenant_id to the current PostgreSQL transaction.
    
    The 'true' parameter in set_config makes the setting local to the 
    current transaction, preventing leaks in connection pools.
    """
    session.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    logger.debug("RLS context set for tenant_id: %s", tenant_id)


def prepare_tenant_session(session: Session, tenant_name: str = DEFAULT_TENANT_NAME) -> uuid.UUID:
    """
    High-level utility to resolve a tenant and bind the session in one go.
    
    Usage:
        with get_db_context(settings) as session:
            prepare_tenant_session(session, "my_customer")
            # All subsequent queries in this session follow RLS rules
            data = session.execute(...) 
    """
    tenant_id = resolve_tenant_id(session, tenant_name)
    set_tenant_context(session, tenant_id)
    
    logger.info("Session bound to tenant '%s' (%s)", tenant_name, tenant_id)
    return tenant_id