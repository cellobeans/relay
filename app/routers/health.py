from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session

router = APIRouter()


@router.get("/healthz")
async def healthz(
    request: Request,
    response: Response,
    # FastAPI calls get_session() per request and passes the session in.
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    checks = {"database": "ok", "redis": "ok"}

    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:  # any failure means "not healthy"; report it instead of crashing
        checks["database"] = f"error: {exc.__class__.__name__}"

    try:
        await request.app.state.redis.ping()
    except Exception as exc:
        checks["redis"] = f"error: {exc.__class__.__name__}"

    healthy = all(v == "ok" for v in checks.values())
    # 503 tells load balancers / Docker "don't send traffic here right now".
    response.status_code = status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if healthy else "degraded", **checks}
