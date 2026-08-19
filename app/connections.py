"""Database support for `email_connections` (Phase 3).

A connection row links a provider (currently only "gmail") to a user and holds
the provider credentials encrypted at rest (see app/security.py). Backend
writes use the service-role key (bypasses RLS); the RLS policies in the README
cover direct reads by the client.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.supabase_client import service_client

logger = logging.getLogger(__name__)

# Keep this in sync with the SQL in README (Phase 3).
TABLE = "email_connections"

DEV_USER_ID = "dev-user"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_user_id(user_id: Optional[str]) -> str:
    """Normalize the requesting user id; dev flows fall back to a fixed id."""
    return (user_id or DEV_USER_ID).strip()


def create_connection(
    user_id: str,
    provider: str,
    encrypted_token: str,
    account_email: Optional[str] = None,
    status: str = "active",
) -> Optional[dict]:
    """Insert (or update) the user's connection for this provider.

    A user has at most one connection per provider; reconnecting overwrites it.
    Returns the stored row, or None if the DB is unavailable.
    """
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping connection write.")
        return None

    row = {
        "user_id": user_id,
        "provider": provider,
        "account_email": account_email,
        "encrypted_token": encrypted_token,
        "status": status,
        "updated_at": now_iso(),
    }

    try:
        result = (
            client.table(TABLE)
            .upsert(row, on_conflict="user_id,provider")
            .execute()
        )
        data = (result.data or [{}])[0]
        logger.info(
            "Stored %s connection for user %s (account=%s)",
            provider,
            user_id,
            account_email or "unknown",
        )
        return data
    except Exception as exc:
        logger.warning("Connection write failed: %s", exc)
        return None


def get_connection(connection_id: str) -> Optional[dict]:
    client = service_client()
    if client is None:
        return None
    try:
        result = client.table(TABLE).select("*").eq("id", connection_id).execute()
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.warning("get_connection failed: %s", exc)
        return None


def get_connection_by_user(user_id: str, provider: str) -> Optional[dict]:
    client = service_client()
    if client is None:
        return None
    try:
        result = (
            client.table(TABLE)
            .select("*")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )
        return result.data or None
    except Exception as exc:
        logger.warning("get_connection_by_user failed: %s", exc)
        return None


def list_connections(user_id: Optional[str] = None) -> list:
    client = service_client()
    if client is None:
        return []
    try:
        query = client.table(TABLE).select("*").order("created_at", desc=True)
        if user_id:
            query = query.eq("user_id", user_id)
        result = query.execute()
        return result.data or []
    except Exception as exc:
        logger.warning("list_connections failed: %s", exc)
        return []


def update_connection(
    connection_id: str,
    *,
    encrypted_token: Optional[str] = None,
    account_email: Optional[str] = None,
    status: Optional[str] = None,
    last_validated_at: Optional[str] = None,
) -> Optional[dict]:
    client = service_client()
    if client is None:
        return None

    updates = {"updated_at": now_iso()}
    if encrypted_token is not None:
        updates["encrypted_token"] = encrypted_token
    if account_email is not None:
        updates["account_email"] = account_email
    if status is not None:
        updates["status"] = status
    if last_validated_at is not None:
        updates["last_validated_at"] = last_validated_at

    try:
        result = (
            client.table(TABLE).update(updates).eq("id", connection_id).execute()
        )
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.warning("update_connection failed: %s", exc)
        return None


def delete_connection(connection_id: str) -> bool:
    client = service_client()
    if client is None:
        return False
    try:
        client.table(TABLE).delete().eq("id", connection_id).execute()
        logger.info("Deleted connection %s", connection_id)
        return True
    except Exception as exc:
        logger.warning("delete_connection failed: %s", exc)
        return False