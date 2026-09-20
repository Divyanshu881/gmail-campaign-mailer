"""Campaign API routes (protected).

Campaigns, contact upload (CSV/Excel), attachments, validation, and reports.
Sending is handled by the background worker: POST /{id}/start validates,
checks the daily quota, and enqueues the campaign on Redis. No HTTP request
ever stays open while emails are being sent.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app import auth, campaign_validation, campaigns, connections, contacts, queue, storage, subscriptions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/campaigns")


class CampaignCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    subject_template: str = Field(..., min_length=1)
    body_template: str = Field(..., min_length=1)
    email_connection_id: str = Field(..., description="Email connection used as the sending provider")


class CampaignOut(BaseModel):
    id: str
    user_id: str
    name: str
    subject_template: str
    body_template: str
    email_connection_id: Optional[str] = None
    status: str
    total_contacts: int = 0
    valid_contacts: int = 0
    sent_count: int = 0
    failed_count: int = 0
    attachments: list = []
    created_at: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    subject_template: Optional[str] = Field(None, min_length=1)
    body_template: Optional[str] = Field(None, min_length=1)
    email_connection_id: Optional[str] = None


def _get_owned_campaign(campaign_id: str, user_id: str) -> dict:
    campaign = campaigns.get_campaign(campaign_id)
    if campaign is None or campaign.get("user_id") != user_id:
        raise HTTPException(status_code=404, detail="Campaign not found.")
    return campaign


def _check_connection(user_id: str, email_connection_id: str) -> None:
    connection = connections.get_connection(email_connection_id)
    if connection is None or connection.get("user_id") != user_id:
        raise HTTPException(
            status_code=422,
            detail="Email connection not found or does not belong to this user.",
        )


@router.post("", response_model=CampaignOut)
def create_campaign(payload: CampaignCreate, user: dict = Depends(auth.get_current_user)):
    """Create a new campaign draft."""
    user_id = user["sub"]
    _check_connection(user_id, payload.email_connection_id)

    campaign = campaigns.create_campaign(
        user_id=user_id,
        name=payload.name,
        subject_template=payload.subject_template,
        body_template=payload.body_template,
        email_connection_id=payload.email_connection_id,
    )
    if campaign is None:
        raise HTTPException(
            status_code=503,
            detail="Could not save campaign (Supabase service role not configured, or the campaigns table is missing).",
        )
    return campaign


@router.get("")
def list_campaigns(user: dict = Depends(auth.get_current_user)):
    """List the current user's campaigns (newest first)."""
    return campaigns.list_campaigns(user["sub"])


@router.patch("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: str,
    payload: CampaignUpdate,
    user: dict = Depends(auth.get_current_user),
):
    """Update a draft campaign's name/templates/connection."""
    _get_owned_campaign(campaign_id, user["sub"])

    updates: dict = {}
    if payload.name is not None:
        updates["name"] = payload.name
    if payload.subject_template is not None:
        updates["subject_template"] = payload.subject_template
    if payload.body_template is not None:
        updates["body_template"] = payload.body_template
    if payload.email_connection_id is not None:
        _check_connection(user["sub"], payload.email_connection_id)
        updates["email_connection_id"] = payload.email_connection_id

    if not updates:
        return campaigns.get_campaign(campaign_id)

    if campaigns.update_campaign(campaign_id, **updates) is None:
        raise HTTPException(
            status_code=503,
            detail="Could not update campaign (Supabase service role not configured, or the campaigns table is missing).",
        )
    return campaigns.get_campaign(campaign_id)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, user: dict = Depends(auth.get_current_user)):
    """Get a single campaign with current contact counts."""
    campaign = _get_owned_campaign(campaign_id, user["sub"])
    summary = campaigns.get_contacts_summary(campaign_id)
    return {**campaign, **summary}


@router.post("/{campaign_id}/contacts")
def upload_contacts(
    campaign_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(auth.get_current_user),
):
    """Parse and store a CSV/Excel contacts file for the campaign."""
    _get_owned_campaign(campaign_id, user["sub"])

    data = file.file.read()
    try:
        parsed = contacts.parse_contacts_file(file.filename or "contacts.csv", data)
    except contacts.ContactFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    stored = campaigns.replace_contacts(campaign_id, parsed["rows"])
    if stored is None:
        raise HTTPException(
            status_code=503,
            detail="Could not store contacts (Supabase service role not configured, or the campaign_contacts table is missing).",
        )

    campaigns.update_campaign(
        campaign_id,
        total_contacts=parsed["summary"]["total"],
        valid_contacts=parsed["summary"]["valid"],
    )

    return {
        "campaign_id": campaign_id,
        "filename": parsed["filename"],
        "columns": parsed["columns"],
        "summary": parsed["summary"],
        "errors": [
            {"email": r.get("email"), "reason": r.get("reason")}
            for r in parsed["rows"]
            if r["status"] != "pending"
        ],
    }


@router.post("/{campaign_id}/attachments")
def upload_attachments(
    campaign_id: str,
    files: list[UploadFile] = File(...),
    user: dict = Depends(auth.get_current_user),
):
    """Attach one or more files to the campaign (added to every outgoing email).

    Stored in Supabase Storage (not local disk) so the worker - a separate
    process/service - can read them regardless of which backend instance
    handled this upload.
    """
    campaign = _get_owned_campaign(campaign_id, user["sub"])

    stored = []
    for file in files:
        filename = Path(file.filename or "").name or "attachment"
        storage_path = f"{campaign_id}/{filename}"
        if not storage.upload_attachment(storage_path, file.file.read()):
            raise HTTPException(
                status_code=503,
                detail=f"Could not store attachment '{filename}' (storage unavailable).",
            )
        stored.append({"filename": filename, "path": storage_path})
        logger.info("Saved attachment %s for campaign %s", filename, campaign_id)

    existing = campaign.get("attachments") or []
    campaigns.update_campaign(campaign_id, attachments=existing + stored)

    return {"campaign_id": campaign_id, "attachments": existing + stored}


@router.post("/{campaign_id}/validate")
def validate_campaign(campaign_id: str, user: dict = Depends(auth.get_current_user)):
    """Run all pre-send validation checks and return the result."""
    campaign = _get_owned_campaign(campaign_id, user["sub"])
    contact_rows = campaigns.get_contacts(campaign_id)
    result = campaign_validation.validate_campaign(user["sub"], campaign, contact_rows)
    return {"campaign_id": campaign_id, **result}


@router.get("/{campaign_id}/report")
def campaign_report(campaign_id: str, user: dict = Depends(auth.get_current_user)):
    """Per-contact report: email, status, reason, timestamp, attempts."""
    _get_owned_campaign(campaign_id, user["sub"])
    rows = campaigns.get_contacts(campaign_id)
    summary = campaigns.get_contacts_summary(campaign_id)
    result = {
        "campaign_id": campaign_id,
        "summary": summary,
        "contacts": [
            {
                "email": r.get("email"),
                "status": r.get("status"),
                "reason": r.get("reason"),
                "attempts": r.get("attempts") or 0,
                "sent_at": r.get("sent_at"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }
    if summary["total_contacts"] == 0:
        result["message"] = "No contacts uploaded yet. Upload a CSV/Excel file first."
    return result


@router.post("/{campaign_id}/start")
def start_campaign(campaign_id: str, user: dict = Depends(auth.get_current_user)):
    """Validate subscription + quota, and enqueue a campaign for the worker.

    Checks before queueing:
      1. User is authenticated (dependency).
      2. User owns the campaign (ownership check below).
      3. Subscription is active (status + date range).
      4. Daily email quota is available (subscription-based limit).
      5. Gmail provider is connected (campaign_validation below).

    This returns immediately (HTTP 200) once the campaign is queued. Sending
    happens asynchronously in the background worker, which enforces the daily
    quota again per email - this check is just a fast fail for the user.
    """
    user_id = user["sub"]
    campaign = _get_owned_campaign(campaign_id, user_id)

    if campaign.get("status") not in ("draft", "paused"):
        raise HTTPException(
            status_code=409,
            detail=f"Campaign cannot be started from status '{campaign.get('status')}'. "
            "Expected 'draft' or 'paused'.",
        )

    # Subscription must be active and within its date range.
    sub = subscriptions.get_subscription(user_id)
    if sub is None or not subscriptions.is_subscription_active(sub):
        raise HTTPException(
            status_code=403,
            detail="Active subscription required.",
        )

    contact_rows = campaigns.get_contacts(campaign_id)
    result = campaign_validation.validate_campaign(user_id, campaign, contact_rows)
    if not result["valid"]:
        raise HTTPException(
            status_code=422,
            detail={"message": "Campaign is not ready to send.", **result},
        )

    # Daily quota comes from the subscription's daily_email_limit.
    daily_limit = subscriptions.get_daily_limit(user_id)
    used_today = subscriptions.get_daily_usage(user_id)
    remaining = daily_limit - used_today
    if remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail=f"Daily email quota reached ({used_today}/{daily_limit}). "
            "Try again tomorrow.",
        )

    if campaigns.update_campaign(campaign_id, status="queued") is None:
        raise HTTPException(
            status_code=503,
            detail="Could not mark the campaign as queued (Supabase service role not configured?).",
        )

    if not queue.enqueue_campaign(campaign_id, user_id):
        campaigns.update_campaign(campaign_id, status="draft")
        raise HTTPException(
            status_code=503,
            detail="Could not enqueue the campaign (Redis is not configured or reachable). "
            "Set REDIS_URL and run the worker (venv/bin/python -m app.worker).",
        )

    logger.info("Campaign %s queued for user %s (remaining daily quota: %d)", campaign_id, user_id, remaining)
    return {
        "campaign_id": campaign_id,
        "status": "queued",
        "message": "Campaign queued. Sending runs in the background worker.",
        "remaining_daily_quota": remaining,
    }


@router.delete("/{campaign_id}")
def delete_campaign(campaign_id: str, user: dict = Depends(auth.get_current_user)):
    """Delete a campaign and its contacts."""
    _get_owned_campaign(campaign_id, user["sub"])
    if not campaigns.delete_campaign(campaign_id):
        raise HTTPException(status_code=503, detail="Could not delete campaign.")
    return {"deleted": True, "campaign_id": campaign_id}