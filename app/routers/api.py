"""Protected API routes (Supabase Auth)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app import auth, connections, subscriptions

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


@router.get("/quota")
def daily_quota(user: dict = Depends(auth.get_current_user)) -> dict:
    """Daily sending quota for the current user (server-side enforced).

    Mirrors the same source of truth used to enforce the limit (the
    subscription's daily_email_limit + usage_daily), not the global default,
    so this never disagrees with what /start and the worker actually enforce.
    """
    used = subscriptions.get_daily_usage(user["sub"])
    limit = subscriptions.get_daily_limit(user["sub"])
    return {
        "used": used,
        "quota": limit,
        "remaining": max(0, limit - used),
    }


@router.get("/subscription")
def my_subscription(user: dict = Depends(auth.get_current_user)) -> dict:
    """Return the current user's subscription status and daily usage."""
    sub = subscriptions.get_subscription_status(user["sub"])
    if sub is None:
        raise HTTPException(
            status_code=404,
            detail="No subscription found for this user.",
        )
    return sub


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
