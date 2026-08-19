"""Phase 1 - Protected API routes (Supabase Auth)."""

import logging

from fastapi import APIRouter, Depends

from app import auth, connections

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


@router.get("/me")
def me(user: dict = Depends(auth.get_current_user)) -> dict:
    """Return the current authenticated user's basic profile."""
    auth.upsert_user(user)

    meta = user.get("user_metadata") or {}
    return {
        "id": user.get("sub"),
        "email": user.get("email"),
        "name": (
            meta.get("full_name")
            or user.get("full_name")
            or meta.get("name")
        ),
        "avatar_url": meta.get("avatar_url") or user.get("avatar_url"),
        "provider": meta.get("provider") or user.get("app_metadata", {}).get("provider"),
    }


@router.get("/connections")
def list_connections(user: dict = Depends(auth.get_current_user)) -> dict:
    """List the current user's email provider connections (no secrets)."""
    rows = connections.list_connections(user["sub"])
    return {
        "connections": [
            {
                "id": r.get("id"),
                "provider": r.get("provider"),
                "account_email": r.get("account_email"),
                "status": r.get("status"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
    }