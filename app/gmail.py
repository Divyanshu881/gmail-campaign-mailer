"""Google OAuth + Gmail API sending logic.

Owns the OAuth client config/flow building and the Gmail API send call.
Provider-specific on purpose - app/providers/gmail.py wraps this behind the
EmailProvider interface so campaign/worker code never depends on Gmail
directly.
"""

import base64
import json
import logging
from email.encoders import encode_base64
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from mimetypes import guess_type
from pathlib import Path
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


def credentials_to_json(creds: Credentials) -> str:
    """Serialize credentials (without the id_token) for encrypted storage."""
    return creds.to_json()


def credentials_from_json(json_str: str) -> Optional[Credentials]:
    """Restore credentials from credentials_to_json(), refreshing if expired.

    Returns None if the token is unusable (corrupted, expired with no refresh
    token, or rejected by Google).
    """
    try:
        creds = Credentials.from_authorized_user_info(json.loads(json_str), SCOPES)
    except Exception as exc:
        logger.error("Could not parse stored credentials: %s", exc)
        return None

    if creds.valid:
        return creds

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            return creds
        except Exception as exc:
            logger.error("Could not refresh access token: %s", exc)
            return None

    logger.warning("Stored credentials are no longer usable; re-authentication required.")
    return None


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


def _build_message(
    to: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
    attachments: Optional[list] = None,
) -> bytes:
    """Build an RFC-2822 message with To/Subject, optional HTML and attachments.

    The Gmail API requires the recipient address in the raw message headers
    ("To"); it does not read it from the payload.
    """
    if not html and not attachments:
        message = MIMEText(body, "plain", "utf-8")
        message["To"] = to
        message["Subject"] = subject
        return message.as_bytes()

    body_part = MIMEText(body, "plain", "utf-8")
    if html:
        msg = MIMEMultipart("alternative")
        msg.attach(body_part)
        msg.attach(MIMEText(html, "html", "utf-8"))
    else:
        msg = body_part

    if not attachments:
        msg["To"] = to
        msg["Subject"] = subject
        return msg.as_bytes()

    outer = MIMEMultipart("mixed")
    outer["To"] = to
    outer["Subject"] = subject
    outer.attach(msg)
    for path in attachments:
        p = Path(path)
        if not p.is_file():
            raise HTTPException(status_code=422, detail=f"Attachment not found: {path}")
        part = MIMEBase("application", "octet-stream")
        part.set_payload(p.read_bytes())
        encode_base64(part)
        ctype, _ = guess_type(p.name)
        if ctype:
            main, sub = ctype.split("/", 1)
            part.set_type(f"{main}/{sub}")
        part.add_header(
            "Content-Disposition",
            "attachment",
            filename=p.name,
        )
        outer.attach(part)
    return outer.as_bytes()


def send_message(
    creds: Credentials,
    to: str,
    subject: str,
    body: str,
    html: Optional[str] = None,
    attachments: Optional[list] = None,
) -> dict:
    """Send an email via the Gmail API from the authenticated user.

    'From' is set by Gmail to the authenticated user's address automatically.
    """
    raw_message = _build_message(to, subject, body, html, attachments)
    raw = base64.urlsafe_b64encode(raw_message).decode("ascii")

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


def send_test_email(creds: Credentials, to: str, subject: str, body: str) -> dict:
    """Send a plain-text email via the Gmail API from the authenticated user."""
    return send_message(creds, to, subject, body, html=None, attachments=None)