"""Admin subscription endpoints (protected).

The admin is identified by the `ADMIN_EMAIL` environment variable. Only an
authenticated user whose email matches ADMIN_EMAIL can create/extend/cancel
subscriptions. No payment gateway is involved - payments are collected
manually by the product owner and reconciled via invoice_number /
payment_reference.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import auth, subscriptions
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

PLANS = {"BASIC"}
STATUSES = {"TRIAL", "ACTIVE", "EXPIRED", "CANCELLED"}


class SubscriptionCreate(BaseModel):
    user_id: str = Field(..., description="UUID of the user to grant a subscription.")
    plan: str = Field("BASIC", description="Plan name, e.g. BASIC.")
    daily_email_limit: int = Field(50, ge=1, description="Emails allowed per day.")
    start_date: Optional[str] = Field(None, description="ISO date (YYYY-MM-DD). Defaults to today.")
    end_date: Optional[str] = Field(None, description="ISO date (YYYY-MM-DD).")
    invoice_number: Optional[str] = None
    payment_reference: Optional[str] = None
    notes: Optional[str] = None


class SubscriptionExtend(BaseModel):
    new_end_date: str = Field(..., description="New ISO end date (YYYY-MM-DD).")
    invoice_number: Optional[str] = None
    payment_reference: Optional[str] = None
    notes: Optional[str] = None


class SubscriptionCancel(BaseModel):
    notes: Optional[str] = Field(None, description="Optional reason for cancelling.")


def _require_admin(user: dict = Depends(auth.get_current_user)) -> dict:
    """FastAPI dependency: ensure the authenticated user is the admin."""
    user_email = (user.get("email") or "").strip().lower()
    admin_email = settings.ADMIN_EMAIL.strip().lower()
    if not admin_email:
        raise HTTPException(
            status_code=503,
            detail="Admin access is not configured. Set ADMIN_EMAIL in .env.",
        )
    if user_email != admin_email:
        raise HTTPException(
            status_code=403,
            detail="Admin access required.",
        )
    return user


def _validate_plan_and_status(plan: str, status: Optional[str]) -> None:
    if plan.upper() not in PLANS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported plan '{plan}'. Supported plans: {', '.join(sorted(PLANS))}.",
        )
    if status is not None and status.upper() not in STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported status '{status}'. Supported statuses: {', '.join(sorted(STATUSES))}.",
        )


@router.post("/subscriptions")
def create_subscription(
    payload: SubscriptionCreate,
    _admin: dict = Depends(_require_admin),
):
    """Create or activate a subscription for a user (manual payment collected)."""
    _validate_plan_and_status(payload.plan, None)

    sub = subscriptions.create_subscription(
        payload.user_id,
        plan=payload.plan,
        status="ACTIVE",
        daily_email_limit=payload.daily_email_limit,
        start_date=payload.start_date,
        end_date=payload.end_date,
        invoice_number=payload.invoice_number,
        payment_reference=payload.payment_reference,
        notes=payload.notes,
    )
    if sub is None:
        raise HTTPException(
            status_code=503,
            detail="Could not create subscription (Supabase service role not configured, or the subscriptions table is missing).",
        )
    return sub


@router.post("/subscriptions/{subscription_id}/extend")
def extend_subscription(
    subscription_id: str,
    payload: SubscriptionExtend,
    _admin: dict = Depends(_require_admin),
):
    """Extend a subscription's end date (subscription renewed)."""
    existing = subscriptions.get_subscription_by_id(subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subscription not found.")

    sub = subscriptions.extend_subscription(
        subscription_id,
        new_end_date=payload.new_end_date,
        invoice_number=payload.invoice_number,
        payment_reference=payload.payment_reference,
        notes=payload.notes,
    )
    if sub is None:
        raise HTTPException(status_code=503, detail="Could not extend subscription.")
    return sub


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(
    subscription_id: str,
    payload: SubscriptionCancel,
    _admin: dict = Depends(_require_admin),
):
    """Cancel a subscription (set status to CANCELLED)."""
    existing = subscriptions.get_subscription_by_id(subscription_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Subscription not found.")

    sub = subscriptions.cancel_subscription(
        subscription_id, notes=payload.notes
    )
    if sub is None:
        raise HTTPException(status_code=503, detail="Could not cancel subscription.")
    return sub


@router.get("/subscriptions")
def list_subscriptions(
    user_email: Optional[str] = None,
    status: Optional[str] = None,
    _admin: dict = Depends(_require_admin),
):
    """List subscriptions with basic user info, optionally filtered by email/status."""
    if status is not None and status.upper() not in STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported status '{status}'. Supported statuses: {', '.join(sorted(STATUSES))}.",
        )
    return subscriptions.list_subscriptions(
        user_email=user_email,
        status=status,
    )