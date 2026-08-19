"""Phase 1 - Supabase Auth.

Google login is handled by Supabase Auth (hosted OAuth); our backend never
handles passwords. The backend's job is to:
  1. Verify Supabase-issued access tokens (JWT, HS256) presented as Bearer tokens.
  2. Identify the current user from the token claims.
  3. Persist a lightweight profile row in the `users` table.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import jwt
from fastapi import Header, HTTPException
from jwt import InvalidTokenError, PyJWKClient

from app.config import settings
from app.supabase_client import service_client

logger = logging.getLogger(__name__)

# Supabase user access tokens carry aud="authenticated".
AUDIENCE = "authenticated"

# Cached client for the project's JWKS (used for RS256/ES256 tokens).
_jwks_client: Optional[PyJWKClient] = None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        if not settings.SUPABASE_URL:
            raise HTTPException(
                status_code=503,
                detail="Supabase is not configured. Set SUPABASE_URL in .env (see .env.example).",
            )
        _jwks_client = PyJWKClient(f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json")
    return _jwks_client


def verify_supabase_token(token: str) -> dict:
    """Verify a Supabase access token and return its claims.

    Older Supabase projects sign access tokens with HS256 using the project's
    JWT secret; newer projects use asymmetric keys (RS256/ES256) published at
    the project's JWKS endpoint. We support both by inspecting the token's
    `alg` header and verifying accordingly.
    """
    try:
        alg = jwt.get_unverified_header(token).get("alg")
    except InvalidTokenError as exc:
        logger.warning("Malformed token header: %s", exc)
        raise HTTPException(status_code=401, detail=f"Malformed token: {exc}")

    if alg == "HS256":
        if not settings.SUPABASE_JWT_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Supabase is not configured. Set SUPABASE_JWT_SECRET in .env (see .env.example).",
            )
        try:
            return jwt.decode(
                token,
                settings.SUPABASE_JWT_SECRET,
                algorithms=["HS256"],
                audience=AUDIENCE,
                options={"require": ["exp", "sub"]},
            )
        except InvalidTokenError as exc:
            logger.warning("Supabase token rejected: %s", exc)
            raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")

    if alg in ("RS256", "ES256"):
        try:
            jwks = _get_jwks_client()
            key = jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                key,
                algorithms=[alg],
                audience=AUDIENCE,
                options={"require": ["exp", "sub"]},
            )
        except HTTPException:
            raise
        except InvalidTokenError as exc:
            logger.warning("Supabase token rejected: %s", exc)
            raise HTTPException(status_code=401, detail=f"Invalid or expired token: {exc}")
        except Exception as exc:
            logger.error("Could not verify token via JWKS: %s", exc)
            raise HTTPException(status_code=500, detail=f"Could not verify token: {exc}")

    raise HTTPException(status_code=401, detail=f"Unsupported token algorithm: {alg}")


def get_current_user(authorization: Optional[str] = Header(default=None)) -> dict:
    """FastAPI dependency: extract and verify the Bearer token, return its claims."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header. Expected 'Bearer <token>'.",
        )

    return verify_supabase_token(token.strip())


def upsert_user(claims: dict) -> None:
    """Upsert the authenticated user's profile row. Non-fatal on DB errors.

    Uses the service role key server-side so RLS does not block the write.
    """
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping user upsert.")
        return

    meta = claims.get("user_metadata") or {}
    row = {
        "id": claims.get("sub"),
        "email": claims.get("email"),
        "full_name": meta.get("full_name") or claims.get("full_name"),
        "avatar_url": meta.get("avatar_url") or claims.get("avatar_url"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        client.table("users").upsert(row, on_conflict="id").execute()
        logger.info("Upserted user profile for %s", row["email"])
    except Exception as exc:
        logger.warning("User upsert failed (continuing with JWT identity): %s", exc)