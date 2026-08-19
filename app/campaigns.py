"""Database support for `campaigns` and `campaign_contacts` (Phase 4).

Follows the same pattern as app/connections.py: backend writes via the
service-role key (bypasses RLS); RLS policies are documented in the README.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from app.connections import now_iso
from app.supabase_client import service_client

logger = logging.getLogger(__name__)

CAMPAIGNS_TABLE = "campaigns"
CONTACTS_TABLE = "campaign_contacts"


# --------------------------------------------------------------------------- #
# Campaigns
# --------------------------------------------------------------------------- #


def create_campaign(
    user_id: str,
    *,
    name: str,
    subject_template: str,
    body_template: str,
    email_connection_id: Optional[str] = None,
    attachments: Optional[list] = None,
) -> Optional[dict]:
    """Insert a campaign row. Returns the stored row, or None on DB failure."""
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping campaign write.")
        return None

    row = {
        "user_id": user_id,
        "name": name,
        "subject_template": subject_template,
        "body_template": body_template,
        "email_connection_id": email_connection_id,
        "attachments": attachments or [],
        "status": "draft",
    }
    try:
        result = client.table(CAMPAIGNS_TABLE).insert(row).execute()
        data = (result.data or [{}])[0]
        logger.info("Created campaign %s for user %s", data.get("id"), user_id)
        return data
    except Exception as exc:
        logger.warning("Campaign create failed: %s", exc)
        return None


def get_campaign(campaign_id: str) -> Optional[dict]:
    client = service_client()
    if client is None:
        return None
    try:
        result = client.table(CAMPAIGNS_TABLE).select("*").eq("id", campaign_id).maybe_single().execute()
        return result.data or None
    except Exception as exc:
        logger.warning("get_campaign failed: %s", exc)
        return None


def list_campaigns(user_id: str) -> list:
    client = service_client()
    if client is None:
        return []
    try:
        result = (
            client.table(CAMPAIGNS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("list_campaigns failed: %s", exc)
        return []


def list_all_campaigns(status: Optional[str] = None) -> list:
    """All campaigns, optionally filtered by status (used by the worker's
    crash-recovery scan)."""
    client = service_client()
    if client is None:
        return []
    try:
        query = client.table(CAMPAIGNS_TABLE).select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return result.data or []
    except Exception as exc:
        logger.warning("list_all_campaigns failed: %s", exc)
        return []


def update_campaign(campaign_id: str, **updates) -> Optional[dict]:
    client = service_client()
    if client is None:
        return None
    try:
        updates["updated_at"] = now_iso()
        result = client.table(CAMPAIGNS_TABLE).update(updates).eq("id", campaign_id).execute()
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.warning("update_campaign failed: %s", exc)
        return None


def delete_campaign(campaign_id: str) -> bool:
    client = service_client()
    if client is None:
        return False
    try:
        client.table(CAMPAIGNS_TABLE).delete().eq("id", campaign_id).execute()
        logger.info("Deleted campaign %s", campaign_id)
        return True
    except Exception as exc:
        logger.warning("delete_campaign failed: %s", exc)
        return False


# --------------------------------------------------------------------------- #
# Campaign contacts
# --------------------------------------------------------------------------- #


def replace_contacts(campaign_id: str, rows: list) -> Optional[dict]:
    """Replace all contacts of a campaign. Returns the row count, or None."""
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping contacts write.")
        return None

    try:
        client.table(CONTACTS_TABLE).delete().eq("campaign_id", campaign_id).execute()
        if rows:
            records = [
                {
                    "campaign_id": campaign_id,
                    "email": row.get("email", ""),
                    "data": row.get("data", {}),
                    "status": row.get("status", "pending"),
                    "reason": row.get("reason"),
                }
                for row in rows
            ]
            client.table(CONTACTS_TABLE).insert(records).execute()
        logger.info("Replaced contacts for campaign %s (%d rows)", campaign_id, len(rows))
        return {"count": len(rows)}
    except Exception as exc:
        logger.warning("replace_contacts failed: %s", exc)
        return None


def get_contacts(campaign_id: str) -> list:
    client = service_client()
    if client is None:
        return []
    try:
        result = (
            client.table(CONTACTS_TABLE)
            .select("*")
            .eq("campaign_id", campaign_id)
            .order("created_at", desc=False)
            .execute()
        )
        return result.data or []
    except Exception as exc:
        logger.warning("get_contacts failed: %s", exc)
        return []


def get_contacts_by_status(campaign_id: str, status: str) -> list:
    """Contacts in a given status, oldest first (the worker's send queue)."""
    return [c for c in get_contacts(campaign_id) if c.get("status") == status]


def update_contact_status(
    contact_id: str,
    *,
    status: str,
    reason: Optional[str] = None,
    sent_at: Optional[str] = None,
    attempts: Optional[int] = None,
) -> Optional[dict]:
    """Record a per-contact send result. Used by the worker (Phase 5)."""
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping contact update.")
        return None

    updates = {"status": status, "reason": reason}
    if sent_at is not None:
        updates["sent_at"] = sent_at
    if attempts is not None:
        updates["attempts"] = attempts
    try:
        result = client.table(CONTACTS_TABLE).update(updates).eq("id", contact_id).execute()
        return result.data[0] if result.data else None
    except Exception as exc:
        logger.warning("update_contact_status failed: %s", exc)
        return None


def count_sent_today(user_id: str) -> int:
    """Emails this user sent today (UTC), across all campaigns.

    This is the server-side daily-quota counter (Phase 5). Default cap is
    DAILY_EMAIL_QUOTA (50). The campaign_contacts.sent_at timestamps are
    compared against the start of today in UTC.
    """
    client = service_client()
    if client is None:
        return 0

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        result = (
            client.table(CONTACTS_TABLE)
            .select("id", count="exact")
            .eq("status", "sent")
            .gte("sent_at", today.isoformat())
            .eq("campaigns.user_id", user_id)
            .execute()
        )
        return _extract_count(result)
    except Exception as exc:
        # PostgREST embedded-filter might not be supported by older PostgREST;
        # fall back to counting per campaign.
        logger.warning("count_sent_today (joined) failed, falling back per-campaign: %s", exc)

    total = 0
    for campaign in list_campaigns(user_id):
        try:
            result = (
                client.table(CONTACTS_TABLE)
                .select("id", count="exact")
                .eq("campaign_id", campaign.get("id"))
                .eq("status", "sent")
                .gte("sent_at", today.isoformat())
                .execute()
            )
            total += _extract_count(result)
        except Exception as exc:
            logger.warning("count_sent_today per-campaign failed: %s", exc)
    return total


def _extract_count(result) -> int:
    """supabase-py returns the count on the response object when count="exact"."""
    count = getattr(result, "count", None)
    if count is None:
        return len(result.data or [])
    try:
        return int(count)
    except (TypeError, ValueError):
        return len(result.data or [])


def get_contacts_summary(campaign_id: str) -> dict:
    """Pending/invalid/duplicate counts for the report and campaign fields."""
    contacts = get_contacts(campaign_id)
    total = len(contacts)
    return {
        "total_contacts": total,
        "valid_contacts": sum(1 for c in contacts if c.get("status") == "pending"),
        "invalid": sum(1 for c in contacts if c.get("status") == "invalid"),
        "duplicates": sum(1 for c in contacts if c.get("status") == "duplicate"),
    }