"""Phase 0 - Gmail API test-send route."""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import gmail

logger = logging.getLogger(__name__)

router = APIRouter()


class SendRequest(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject")
    body: str = Field(..., min_length=1, description="Email body")


@router.post("/email/send")
def send_email(payload: SendRequest) -> dict:
    """Send a plain-text test email via the Gmail API from the authenticated user."""
    creds = gmail.load_credentials()
    if creds is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Visit /auth/login first.",
        )

    # Basic validation before hitting the API.
    if "@" not in payload.to or "." not in payload.to.split("@")[-1]:
        raise HTTPException(status_code=422, detail=f"Invalid recipient email: {payload.to}")

    return gmail.send_test_email(creds, payload.to, payload.subject, payload.body)