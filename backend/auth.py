"""Supabase JWT verification for FastAPI using ES256 (ECC P-256) with JWKS."""

from __future__ import annotations

import os
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

# Supabase JWKS endpoint
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
JWKS_URL = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json" if SUPABASE_URL else None

# Legacy JWT secret (for backwards compatibility with old HS256 tokens)
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET") or os.environ.get("JWT_SECRET")

security = HTTPBearer(auto_error=False)

# Cache for JWKS
_jwks_cache = None


def _load_jwks() -> dict:
    """Load JWKS from Supabase."""
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache

    if not JWKS_URL:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth not configured (missing SUPABASE_URL)",
        )

    import requests
    try:
        resp = requests.get(JWKS_URL, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to load JWKS: {e}",
        )


def _get_signing_key(kid: str) -> dict:
    """Get signing key from JWKS by kid."""
    jwks = _load_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=f"Unknown key ID: {kid}",
    )


def _jwk_to_pem(jwk: dict) -> str:
    """Convert JWK (EC P-256) to PEM format."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.backends import default_backend
    import base64

    # Extract x and y coordinates
    x = base64.urlsafe_b64decode(jwk["x"] + "=")  # Add padding
    y = base64.urlsafe_b64decode(jwk["y"] + "=")

    # Create public numbers
    public_numbers = ec.EllipticCurvePublicNumbers(
        int.from_bytes(x, "big"),
        int.from_bytes(y, "big"),
        ec.SECP256R1(),
    )
    public_key = public_numbers.public_key(default_backend())

    # Export as PEM
    pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return pem.decode("utf-8")


def verify_supabase_jwt(token: str) -> str:
    """Verify Supabase access token and return user_id (sub). Raises on invalid token.

    Supports ES256 (ECC P-256) via JWKS and legacy HS256 via JWT_SECRET.
    """
    try:
        # Decode without verification to get the header
        unverified = jwt.decode(token, options={"verify_signature": False})
        headers = jwt.get_unverified_header(token)
        alg = headers.get("alg", "HS256")
        kid = headers.get("kid")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token format: {e}",
        )

    # Try ES256 with JWKS
    if alg == "ES256" and kid:
        try:
            jwk = _get_signing_key(kid)
            pem = _jwk_to_pem(jwk)
            payload = jwt.decode(
                token,
                pem,
                algorithms=["ES256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {e}",
            )
    # Fallback to legacy HS256
    elif alg == "HS256" and JWT_SECRET:
        try:
            payload = jwt.decode(
                token,
                JWT_SECRET,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expired",
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Unsupported algorithm: {alg}",
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
