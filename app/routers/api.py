"""Phase 1 - Protected API routes (Supabase Auth)."""

import logging

from fastapi import APIRouter, Depends

from app import auth

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