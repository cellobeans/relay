import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Parent class for all tables. Alembic reads Base.metadata to autogenerate migrations."""


class Tenant(Base):
    """A customer company using Relay. Authenticates with an API key."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # SHA-256 hex digest of the API key (64 chars). unique=True also creates the index we
    # search on every authenticated request, so the lookup stays fast with many tenants.
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Endpoint(Base):
    """A URL a tenant wants events delivered to, plus which event types it subscribes to."""

    __tablename__ = "endpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # ondelete=CASCADE: deleting a tenant deletes its endpoints. index=True: every query
    # filters by tenant_id (that's how tenants are kept apart), so it needs an index.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    url: Mapped[str] = mapped_column(Text)
    # Stored as-is, not hashed: in M3 the worker needs the real value to sign each delivery.
    secret: Mapped[str] = mapped_column(String(100))
    event_types: Mapped[list[str]] = mapped_column(ARRAY(Text))
    active: Mapped[bool] = mapped_column(default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
