"""Supabase JWT verification for FastAPI."""

from __future__ import annotations

import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET")
if not JWT_SECRET:
    JWT_SECRET = os.environ.get("JWT_SECRET")

security = HTTPBearer(auto_error=False)


def verify_supabase_jwt(token: str) -> str:
    """Verify Supabase access token and return user_id (sub). Raises on invalid token."""
    if not JWT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured (missing SUPABASE_JWT_SECRET)",
        )
    try:
        payload = jwt.decode(
            token,
            JWT_SECRET,
            audience="authenticated",
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing sub",
        )
    return str(user_id)


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> str:
    """FastAPI dependency: require Bearer token and return user_id."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return verify_supabase_jwt(credentials.credentials)


def get_user_id_from_token(token: str | None) -> str | None:
    """Verify token (e.g. from query param for SSE) and return user_id, or None if invalid/missing."""
    if not token:
        return None
    try:
        return verify_supabase_jwt(token)
    except HTTPException:
        return None
