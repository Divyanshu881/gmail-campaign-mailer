"""Phase 3 - Test-send route, routed through EmailProvider."""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import connections
from app.providers import get_provider
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

router = APIRouter()

PROVIDER = "gmail"
_provider = get_provider(PROVIDER)


class SendRequest(BaseModel):
    to: str = Field(..., description="Recipient email address")
    subject: str = Field(..., min_length=1, description="Email subject")
    body: str = Field(..., min_length=1, description="Email body")


@router.post("/email/send")
def send_email(
    payload: SendRequest,
    user_id: Optional[str] = Query(default=None),
) -> dict:
    """Send a plain-text test email through the user's Gmail connection."""
    uid = connections.resolve_user_id(user_id)
    connection = connections.get_connection_by_user(uid, PROVIDER)
    if connection is None:
        raise HTTPException(
            status_code=401,
            detail="No Gmail connection found. Visit /auth/login first.",
        )

    # Basic validation before hitting the API.
    if "@" not in payload.to or "." not in payload.to.split("@")[-1]:
        raise HTTPException(status_code=422, detail=f"Invalid recipient email: {payload.to}")

    try:
        return _provider.send_test_email(
            connection, to=payload.to, subject=payload.subject, body=payload.body
        )
    except ProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc))