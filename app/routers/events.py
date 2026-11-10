import uuid
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Response, status
from sqlalchemy import any_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentTenant
from app.db import SessionDep
from app.models import DeliveryAttempt, Endpoint, Event, Tenant
from app.schemas import DeliveryAttemptOut, EventCreate, EventOut

router = APIRouter(prefix="/events", tags=["events"])


async def _event_out(session: AsyncSession, event: Event) -> EventOut:
    attempts = await session.scalars(
        select(DeliveryAttempt)
        .where(DeliveryAttempt.event_id == event.id)
        .order_by(DeliveryAttempt.created_at, DeliveryAttempt.attempt_no)
    )
    return EventOut(
        id=event.id,
        type=event.type,
        payload=event.payload,
        idempotency_key=event.idempotency_key,
        created_at=event.created_at,
        deliveries=[DeliveryAttemptOut.model_validate(a) for a in attempts],
    )


async def _get_owned_event(session: AsyncSession, tenant: Tenant, event_id: uuid.UUID) -> Event:
    event = await session.scalar(
        select(Event).where(Event.id == event_id, Event.tenant_id == tenant.id)
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return event


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_event(
    body: EventCreate,
    tenant: CurrentTenant,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[str, Header(min_length=1, max_length=255)],
) -> EventOut:
    # INSERT ... ON CONFLICT DO NOTHING: Postgres decides atomically whether this key is new.
    # If a concurrent request with the same key is mid-insert, this one waits for it, then
    # does nothing. RETURNING gives us the new id, or nothing if the key already existed.
    new_id = await session.scalar(
        pg_insert(Event)
        .values(
            tenant_id=tenant.id,
            type=body.type,
            payload=body.payload,
            idempotency_key=idempotency_key,
        )
        .on_conflict_do_nothing(constraint="uq_events_tenant_id_idempotency_key")
        .returning(Event.id)
    )

    if new_id is None:
        # Repeat of an earlier request: return what we created the first time, change nothing.
        existing = await session.scalar(
            select(Event).where(
                Event.tenant_id == tenant.id, Event.idempotency_key == idempotency_key
            )
        )
        response.status_code = status.HTTP_200_OK
        return await _event_out(session, existing)

    # One pending delivery per active endpoint of this tenant subscribed to this event type.
    endpoints = await session.scalars(
        select(Endpoint).where(
            Endpoint.tenant_id == tenant.id,
            Endpoint.active.is_(True),
            body.type == any_(Endpoint.event_types),  # SQL: type = ANY(event_types)
        )
    )
    session.add_all(DeliveryAttempt(event_id=new_id, endpoint_id=e.id) for e in endpoints)
    # The event and its deliveries commit together: either all exist or none do.
    await session.commit()

    event = await session.get(Event, new_id)
    return await _event_out(session, event)


@router.get("/{event_id}")
async def get_event(event_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep) -> EventOut:
    return await _event_out(session, await _get_owned_event(session, tenant, event_id))
