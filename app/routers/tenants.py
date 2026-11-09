from fastapi import APIRouter, Depends, status

from app.auth import generate_api_key, hash_api_key, require_admin
from app.db import SessionDep
from app.models import Tenant
from app.schemas import TenantCreate, TenantCreated

# Every route in this router requires the admin token.
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.post("/tenants", status_code=status.HTTP_201_CREATED)
async def create_tenant(body: TenantCreate, session: SessionDep) -> TenantCreated:
    api_key = generate_api_key()
    tenant = Tenant(name=body.name, api_key_hash=hash_api_key(api_key))
    session.add(tenant)
    await session.commit()
    await session.refresh(tenant)  # load created_at, which Postgres filled in

    # The raw key appears in this response and nowhere else: it is never stored or logged.
    return TenantCreated(
        id=tenant.id, name=tenant.name, api_key=api_key, created_at=tenant.created_at
    )
