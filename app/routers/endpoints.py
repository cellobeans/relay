import secrets
import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import CurrentTenant
from app.db import SessionDep
from app.models import Endpoint, Tenant
from app.schemas import EndpointCreate, EndpointCreated, EndpointOut

router = APIRouter(prefix="/endpoints", tags=["endpoints"])


async def _get_owned_endpoint(
    session: AsyncSession, tenant: Tenant, endpoint_id: uuid.UUID
) -> Endpoint:
    # Filtering on tenant_id as well as id is what keeps tenants apart. Another tenant's
    # endpoint gets the same 404 as one that doesn't exist, so we don't even confirm it's real.
    endpoint = await session.scalar(
        select(Endpoint).where(Endpoint.id == endpoint_id, Endpoint.tenant_id == tenant.id)
    )
    if endpoint is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Endpoint not found")
    return endpoint


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    body: EndpointCreate, tenant: CurrentTenant, session: SessionDep
) -> EndpointCreated:
    endpoint = Endpoint(
        tenant_id=tenant.id,
        url=str(body.url),
        event_types=body.event_types,
        # Shared secret used to sign deliveries (M3). The tenant's server uses it to verify us.
        secret="whsec_" + secrets.token_urlsafe(32),
    )
    session.add(endpoint)
    await session.commit()
    await session.refresh(endpoint)  # load created_at and active, which Postgres filled in
    return EndpointCreated.model_validate(endpoint)


@router.get("")
async def list_endpoints(tenant: CurrentTenant, session: SessionDep) -> list[EndpointOut]:
    result = await session.scalars(
        select(Endpoint).where(Endpoint.tenant_id == tenant.id).order_by(Endpoint.created_at)
    )
    return [EndpointOut.model_validate(e) for e in result]


@router.get("/{endpoint_id}")
async def get_endpoint(
    endpoint_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> EndpointOut:
    return EndpointOut.model_validate(await _get_owned_endpoint(session, tenant, endpoint_id))


@router.post("/{endpoint_id}/deactivate")
async def deactivate_endpoint(
    endpoint_id: uuid.UUID, tenant: CurrentTenant, session: SessionDep
) -> EndpointOut:
    # We keep the row (soft delete) so past deliveries to it stay traceable in M2+.
    endpoint = await _get_owned_endpoint(session, tenant, endpoint_id)
    endpoint.active = False
    await session.commit()
    return EndpointOut.model_validate(endpoint)
