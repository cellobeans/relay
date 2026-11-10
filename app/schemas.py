"""Shapes of request bodies and responses. FastAPI validates input against these (422 if wrong)."""

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

EventType = Annotated[str, Field(min_length=1, max_length=100)]


class TenantCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class TenantCreated(BaseModel):
    id: uuid.UUID
    name: str
    api_key: str = Field(description="Shown only once. Relay stores only its hash.")
    created_at: datetime


class EndpointCreate(BaseModel):
    url: HttpUrl  # rejects anything that isn't a valid http(s) URL
    event_types: list[EventType] = Field(min_length=1)


class EndpointOut(BaseModel):
    # Lets Pydantic read fields straight off a SQLAlchemy object (endpoint.url, endpoint.id...).
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    event_types: list[str]
    active: bool
    created_at: datetime


class EndpointCreated(EndpointOut):
    """Same as EndpointOut plus the signing secret, returned only from the create call."""

    secret: str


class EventCreate(BaseModel):
    type: EventType
    payload: dict[str, Any]


class DeliveryAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    attempt_no: int
    status: str
    response_code: int | None
    error: str | None
    latency_ms: int | None
    next_retry_at: datetime | None
    created_at: datetime


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    payload: dict[str, Any]
    idempotency_key: str
    created_at: datetime
    deliveries: list[DeliveryAttemptOut]


class ReplayResult(BaseModel):
    replayed: int = Field(description="How many dead deliveries were sent again")
