import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class Event(Base):
    """Something that happened in a tenant's system (e.g. "order.created") to deliver."""

    __tablename__ = "events"
    __table_args__ = (
        # The idempotency guarantee: Postgres itself refuses a second event with the same key for
        # the same tenant, even if two requests arrive at the same instant. Its index (tenant_id
        # first) also serves "find this tenant's events" lookups, so no separate index is needed.
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_events_tenant_id_idempotency_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(Text)
    # JSONB stores the JSON in a parsed binary form Postgres can query and index.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeliveryStatus(enum.StrEnum):
    pending = "pending"  # waiting to be sent (or for its scheduled retry time)
    succeeded = "succeeded"  # the endpoint answered 2xx
    failed = "failed"  # this attempt failed and a later attempt was scheduled
    dead = "dead"  # this attempt failed and Relay gave up; only a manual replay sends it again


class DeliveryAttempt(Base):
    """One try at delivering one event to one endpoint. Retries add new rows, keeping history."""

    __tablename__ = "delivery_attempts"
    __table_args__ = (
        # Stops the same attempt being created twice (e.g. a job that runs twice, or two
        # concurrent replays). Its index (event_id first) also serves "deliveries for this event".
        UniqueConstraint(
            "event_id", "endpoint_id", "attempt_no", name="uq_delivery_attempts_event_endpoint_no"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("endpoints.id", ondelete="CASCADE"), index=True
    )
    attempt_no: Mapped[int] = mapped_column(default=1)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status"), default=DeliveryStatus.pending
    )
    response_code: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None]
    # For a pending retry: the earliest time it may run. Empty for a first attempt (run now).
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
