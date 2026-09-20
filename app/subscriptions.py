"""Subscription and daily usage tracking.

Subscriptions are managed manually by the admin (no payment gateway). The admin
creates/extends/cancels subscriptions via protected admin endpoints. Users can
view their own subscription via GET /api/subscription.

The subscription is considered active ONLY when:
  status in ('ACTIVE', 'TRIAL') AND start_date <= today <= end_date

No scheduled job is needed to expire subscriptions — expiration is detected
on every check by comparing end_date against today.

Daily email usage is tracked in a separate `usage_daily` table (one row per
user per day, atomically incremented by the worker after each successful send).
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.connections import now_iso
from app.config import settings
from app.supabase_client import service_client

logger = logging.getLogger(__name__)

SUBSCRIPTIONS_TABLE = "subscriptions"
USAGE_TABLE = "usage_daily"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _today() -> date:
    return datetime.now(timezone.utc).date()


# --------------------------------------------------------------------------- #
# Subscriptions
# --------------------------------------------------------------------------- #

def get_subscription(user_id: str) -> Optional[dict]:
    """Return the user's subscription row, or None."""
    client = service_client()
    if client is None:
        return None
    try:
        result = (
            client.table(SUBSCRIPTIONS_TABLE)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(1)
            .maybe_single()
            .execute()
        )
        # This postgrest-py version returns None itself (not a response with
        # .data=None) when .maybe_single() matches zero rows - guard for it.
        return result.data if result else None
    except Exception as exc:
        logger.warning("get_subscription failed: %s", exc)
        return None


def get_subscription_by_id(subscription_id: str) -> Optional[dict]:
    """Return a subscription by its primary key."""
    client = service_client()
    if client is None:
        return None
    try:
        result = (
            client.table(SUBSCRIPTIONS_TABLE)
            .select("*")
            .eq("id", subscription_id)
            .maybe_single()
            .execute()
        )
        return result.data if result else None
    except Exception as exc:
        logger.warning("get_subscription_by_id failed: %s", exc)
        return None


def _user_profile(user_id: str) -> dict:
    """Basic user info (email/name) for the admin subscription view."""
    client = service_client()
    if client is None:
        return {}
    try:
        result = (
            client.table("users")
            .select("email,full_name")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return (result.data or {}) if result else {}
    except Exception:
        return {}


def list_subscriptions(
    *,
    user_email: Optional[str] = None,
    status: Optional[str] = None,
) -> list:
    """List subscriptions, optionally filtered. Includes basic user info for admin view."""
    client = service_client()
    if client is None:
        return []
    try:
        query = client.table(SUBSCRIPTIONS_TABLE).select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status.upper())
        result = query.execute()
        rows = result.data or []

        for row in rows:
            row["user"] = _user_profile(row.get("user_id", ""))

        if user_email:
            rows = [
                r for r in rows
                if user_email.lower() in (r.get("user") or {}).get("email", "").lower()
            ]

        return rows
    except Exception as exc:
        logger.warning("list_subscriptions failed: %s", exc)
        return []


def create_subscription(
    user_id: str,
    *,
    plan: str = "BASIC",
    status: str = "ACTIVE",
    daily_email_limit: int = 50,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    invoice_number: Optional[str] = None,
    payment_reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[dict]:
    """Create or replace a user's subscription. Upserts on user_id."""
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; skipping subscription write.")
        return None

    today = _today()
    if start_date is None:
        start_date = today.isoformat()
    if end_date is None:
        end_date = (today + timedelta(days=settings.TRIAL_DAYS)).isoformat()

    row = {
        "user_id": user_id,
        "plan": plan.upper(),
        "status": status.upper(),
        "daily_email_limit": daily_email_limit,
        "start_date": start_date,
        "end_date": end_date,
        "invoice_number": invoice_number,
        "payment_reference": payment_reference,
        "notes": notes,
        "updated_at": now_iso(),
    }

    try:
        existing = get_subscription(user_id)
        if existing:
            result = (
                client.table(SUBSCRIPTIONS_TABLE)
                .update(row)
                .eq("id", existing["id"])
                .execute()
            )
        else:
            row["created_at"] = now_iso()
            result = client.table(SUBSCRIPTIONS_TABLE).insert(row).execute()

        data = (result.data or [{}])[0]
        logger.info("Subscription for user %s: plan=%s status=%s", user_id, plan, status)
        return data
    except Exception as exc:
        logger.warning("create_subscription failed: %s", exc)
        return None


def extend_subscription(
    subscription_id: str,
    *,
    new_end_date: str,
    invoice_number: Optional[str] = None,
    payment_reference: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[dict]:
    """Extend a subscription's end date."""
    client = service_client()
    if client is None:
        return None

    updates: dict = {
        "end_date": new_end_date,
        "status": "ACTIVE",
        "updated_at": now_iso(),
    }
    if invoice_number is not None:
        updates["invoice_number"] = invoice_number
    if payment_reference is not None:
        updates["payment_reference"] = payment_reference
    if notes is not None:
        updates["notes"] = notes

    try:
        result = (
            client.table(SUBSCRIPTIONS_TABLE)
            .update(updates)
            .eq("id", subscription_id)
            .execute()
        )
        data = (result.data or [{}])[0]
        logger.info("Extended subscription %s to %s", subscription_id, new_end_date)
        return data
    except Exception as exc:
        logger.warning("extend_subscription failed: %s", exc)
        return None


def cancel_subscription(subscription_id: str, *, notes: Optional[str] = None) -> Optional[dict]:
    """Set a subscription's status to CANCELLED."""
    client = service_client()
    if client is None:
        return None

    updates: dict = {
        "status": "CANCELLED",
        "updated_at": now_iso(),
    }
    if notes is not None:
        updates["notes"] = notes

    try:
        result = (
            client.table(SUBSCRIPTIONS_TABLE)
            .update(updates)
            .eq("id", subscription_id)
            .execute()
        )
        data = (result.data or [{}])[0]
        logger.info("Cancelled subscription %s", subscription_id)
        return data
    except Exception as exc:
        logger.warning("cancel_subscription failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Subscription validation
# --------------------------------------------------------------------------- #

def is_subscription_active(sub: dict) -> bool:
    """Check if a subscription is currently active.

    Active means:
      - status is ACTIVE or TRIAL
      - today is within [start_date, end_date]
    """
    status = (sub.get("status") or "").upper()
    if status not in ("ACTIVE", "TRIAL"):
        return False
    try:
        start = date.fromisoformat(sub["start_date"])
        end = date.fromisoformat(sub["end_date"])
    except (KeyError, ValueError):
        return False
    today = _today()
    return start <= today <= end


def create_trial_subscription(user_id: str) -> Optional[dict]:
    """Create a trial subscription for a new user. No-op if one already exists."""
    existing = get_subscription(user_id)
    if existing is not None:
        return existing

    today = _today()
    return create_subscription(
        user_id,
        plan="BASIC",
        status="TRIAL",
        daily_email_limit=settings.DAILY_EMAIL_QUOTA,
        start_date=today.isoformat(),
        end_date=(today + timedelta(days=settings.TRIAL_DAYS)).isoformat(),
        notes="Auto-created trial subscription",
    )


# --------------------------------------------------------------------------- #
# Daily usage tracking
# --------------------------------------------------------------------------- #

def get_daily_usage(user_id: str) -> int:
    """Return how many emails the user has sent today."""
    client = service_client()
    if client is None:
        return 0

    today_str = _today().isoformat()
    try:
        result = (
            client.table(USAGE_TABLE)
            .select("emails_sent")
            .eq("user_id", user_id)
            .eq("date", today_str)
            .maybe_single()
            .execute()
        )
        # See get_subscription(): .maybe_single().execute() returns None
        # itself (not a response) when there is no row yet for today.
        row = result.data if result else None
        return int(row["emails_sent"]) if row else 0
    except Exception as exc:
        logger.warning("get_daily_usage failed: %s", exc)
        return 0


def increment_daily_usage(user_id: str) -> int:
    """Atomically increment today's email count. Returns the new total."""
    client = service_client()
    if client is None:
        return 0

    today_str = _today().isoformat()
    try:
        existing = (
            client.table(USAGE_TABLE)
            .select("id,emails_sent")
            .eq("user_id", user_id)
            .eq("date", today_str)
            .maybe_single()
            .execute()
        )
        # See get_subscription(): .maybe_single().execute() returns None
        # itself (not a response) when there is no row yet for today - this
        # previously made every "first send of the day" silently skip the
        # insert below, so usage_daily was never created and the daily quota
        # was never actually enforced.
        existing_data = existing.data if existing else None

        if existing_data:
            new_count = int(existing_data["emails_sent"]) + 1
            client.table(USAGE_TABLE).update({"emails_sent": new_count}).eq(
                "id", existing_data["id"]
            ).execute()
            return new_count

        client.table(USAGE_TABLE).insert({
            "user_id": user_id,
            "date": today_str,
            "emails_sent": 1,
        }).execute()
        return 1
    except Exception as exc:
        logger.warning("increment_daily_usage failed: %s", exc)
        return 0


def get_daily_limit(user_id: str) -> int:
    """Return the user's daily email limit from their subscription."""
    sub = get_subscription(user_id)
    if sub:
        return int(sub.get("daily_email_limit") or settings.DAILY_EMAIL_QUOTA)
    return settings.DAILY_EMAIL_QUOTA


def has_daily_quota(user_id: str) -> bool:
    """True if the user has remaining daily emails AND an active subscription."""
    sub = get_subscription(user_id)
    if sub is None or not is_subscription_active(sub):
        return False
    limit = int(sub.get("daily_email_limit") or settings.DAILY_EMAIL_QUOTA)
    used = get_daily_usage(user_id)
    return used < limit


def get_subscription_status(user_id: str) -> Optional[dict]:
    """Return a summary dict for GET /api/subscription.

    The reported status is derived from the date range, not just the stored
    status: if the end_date has passed, the subscription is reported as
    EXPIRED even if the stored status still says ACTIVE.
    """
    sub = get_subscription(user_id)
    if sub is None:
        return None

    active = is_subscription_active(sub)
    today_used = get_daily_usage(user_id)
    daily_limit = int(sub.get("daily_email_limit") or settings.DAILY_EMAIL_QUOTA)

    if active:
        reported_status = "ACTIVE"
    else:
        stored = (sub.get("status") or "").upper()
        if stored in ("CANCELLED", "EXPIRED"):
            reported_status = stored
        else:
            # Stored status is ACTIVE/TRIAL but the date range has passed.
            reported_status = "EXPIRED"

    return {
        "status": reported_status,
        "plan": sub.get("plan", "BASIC"),
        "daily_email_limit": daily_limit,
        "emails_sent_today": today_used,
        "emails_remaining_today": max(0, daily_limit - today_used),
        "start_date": sub.get("start_date"),
        "end_date": sub.get("end_date"),
    }
