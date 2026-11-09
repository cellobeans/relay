import hashlib
import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select

from app.config import settings
from app.db import SessionDep
from app.models import Tenant


def generate_api_key() -> str:
    # 32 random bytes = 256 bits: impossible to guess. The "rly_" prefix makes a leaked key
    # easy to recognise in logs or code (GitHub's secret scanning works the same way).
    return "rly_" + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    # Plain SHA-256 is enough here (unlike passwords, which need slow hashes like bcrypt):
    # our keys are long random strings, so there's no list of likely guesses to try.
    return hashlib.sha256(api_key.encode()).hexdigest()


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},  # tells the client which auth scheme we expect
    )


def _bearer_token(authorization: str | None) -> str:
    """Pull the token out of an `Authorization: Bearer <token>` header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized("Missing or malformed Authorization header, expected 'Bearer <token>'")
    return authorization.removeprefix("Bearer ").strip()


async def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    """Dependency for admin-only routes: the token must equal the ADMIN_TOKEN env var."""
    token = _bearer_token(authorization)
    # compare_digest takes the same time no matter where the strings differ, so an attacker
    # can't work out the token character by character by timing our responses.
    if not secrets.compare_digest(token.encode(), settings.admin_token.encode()):
        raise _unauthorized("Invalid admin token")


async def get_current_tenant(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> Tenant:
    """Dependency for tenant routes: find the tenant whose stored hash matches the key's hash."""
    api_key = _bearer_token(authorization)
    tenant = await session.scalar(
        select(Tenant).where(Tenant.api_key_hash == hash_api_key(api_key))
    )
    if tenant is None:
        raise _unauthorized("Invalid API key")
    return tenant


# Shorthand used in route signatures: `tenant: CurrentTenant`.
CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
