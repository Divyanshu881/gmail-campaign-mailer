"""Phase 0 - Google OAuth + Gmail API sending logic.

This module owns the Gmail OAuth flow (PKCE, CSRF state, local token storage)
and the Gmail API send call. It is provider-specific on purpose; later phases
introduce an EmailProvider abstraction, but per the design doc we do NOT build
that until Phase 3.
"""

import base64
import json
import logging
import secrets
from email.mime.text import MIMEText
from typing import Optional

from fastapi import HTTPException
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import settings

logger = logging.getLogger(__name__)

# Only the Gmail permission required for sending email.
# openid/email are used to identify the authenticated user.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "openid",
    "email",
]

# In-memory store of pending OAuth flows keyed by state, for CSRF protection
# and to preserve the PKCE code_verifier between the two OAuth steps.
# Fine for this single-process dev PoC; replaced by real session storage later.
_pending_flows: dict[str, Flow] = {}


def client_config() -> dict:
    """Build the Google OAuth client config from settings."""
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.OAUTH_REDIRECT_URI],
        }
    }


def build_flow() -> Flow:
    flow = Flow.from_client_config(client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.OAUTH_REDIRECT_URI
    return flow


def credentials_configured() -> bool:
    return settings.gmail_configured()


def load_credentials() -> Optional[Credentials]:
    """Load the stored token, refreshing it if expired. Returns None if unusable."""
    if not settings.TOKEN_FILE.exists():
        logger.info("No token file found at %s", settings.TOKEN_FILE)
        return None

    try:
        creds = Credentials.from_authorized_user_file(str(settings.TOKEN_FILE), SCOPES)
    except Exception as exc:  # corrupted token file
        logger.error("Could not read token file %s: %s", settings.TOKEN_FILE, exc)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            settings.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
            logger.info("Refreshed access token and saved to %s", settings.TOKEN_FILE)
            return creds
        except Exception as exc:
            logger.error("Could not refresh access token: %s", exc)
            return None

    logger.warning("Token exists but is no longer usable; re-authentication required.")
    return None


def save_token(creds: Credentials) -> None:
    settings.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    logger.info("OAuth token saved to %s", settings.TOKEN_FILE)


def gmail_service(creds: Credentials):
    return build("gmail", "v1", credentials=creds)


def id_token_email(creds: Credentials) -> Optional[str]:
    """Extract the user's email from the OpenID Connect id_token.

    The id_token is only available on freshly-obtained credentials (it is not
    persisted by Credentials.to_json()). The token came from Google over TLS,
    so this decode is only for display purposes, not a security boundary.
    """
    id_token = getattr(creds, "id_token", None)
    if not id_token:
        return None
    try:
        payload_segment = id_token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
        return claims.get("email")
    except Exception as exc:
        logger.warning("Could not decode id_token email: %s", exc)
        return None


def send_test_email(creds: Credentials, to: str, subject: str, body: str) -> dict:
    """Send a plain-text email via the Gmail API from the authenticated user.

    'From' is set by Gmail to the authenticated user's address automatically.
    """
    message = MIMEText(body, "plain", "utf-8")
    message["To"] = to
    message["Subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

    try:
        service = gmail_service(creds)
        sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    except HttpError as exc:
        logger.error("Gmail send failed: %s", exc)
        raise HTTPException(
            status_code=400,
            detail=f"Gmail send failed ({exc.resp.status}): {exc.reason}",
        )
    except Exception as exc:
        logger.error("Unexpected error while sending: %s", exc)
        raise HTTPException(status_code=500, detail=f"Unexpected send error: {exc}")

    logger.info("Email sent via Gmail API: id=%s to=%s", sent.get("id"), to)
    return {"status": "sent", "message_id": sent.get("id"), "to": to}