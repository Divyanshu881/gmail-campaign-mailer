"""Phase 0 - Gmail OAuth flow routes."""

import json
import logging
import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app import gmail
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/auth/login")
def auth_login() -> RedirectResponse:
    """Start the Google OAuth flow. Redirects the user to Google's consent screen."""
    if not gmail.credentials_configured():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials are not configured. "
                   "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env (see .env.example).",
        )

    flow = gmail.build_flow()
    state = secrets.token_urlsafe(32)
    gmail._pending_flows[state] = flow

    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    logger.info("Starting Google OAuth flow (state=%s)", state)
    return RedirectResponse(authorization_url)


@router.get("/auth/callback")
def auth_callback(
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> HTMLResponse:
    """Handle Google's redirect after the user approves/denies consent."""
    if error:
        logger.error("Google returned an OAuth error: %s", error)
        return HTMLResponse(
            f"<h1>Authorization failed</h1><p>Google returned: {error}</p>"
            "<p><a href='/'>Back to home</a></p>",
            status_code=400,
        )

    if not code:
        logger.error("OAuth callback received no authorization code.")
        return HTMLResponse(
            "<h1>Authorization failed</h1><p>No authorization code was returned.</p>"
            "<p><a href='/'>Back to home</a></p>",
            status_code=400,
        )

    if not state or state not in gmail._pending_flows:
        logger.warning("OAuth state mismatch or missing state (possible CSRF).")
        return HTMLResponse(
            "<h1>Authorization failed</h1><p>Invalid or missing OAuth state.</p>"
            "<p><a href='/'>Back to home</a></p>",
            status_code=400,
        )
    flow = gmail._pending_flows.pop(state)

    if not gmail.credentials_configured():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth credentials are not configured. "
                   "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env (see .env.example).",
        )

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        logger.exception("Failed to exchange authorization code")
        return HTMLResponse(
            f"<h1>Authorization failed</h1><p>Could not exchange the code for a token: {exc}</p>"
            "<p><a href='/'>Back to home</a></p>",
            status_code=400,
        )

    gmail.save_token(flow.credentials)
    email = gmail.id_token_email(flow.credentials)
    if email:
        settings.AUTH_EMAIL_FILE.write_text(json.dumps({"email": email}), encoding="utf-8")
        logger.info("Authenticated Gmail account: %s", email)
    else:
        logger.warning("Could not determine the authenticated Gmail email from the id_token.")
    logger.info("OAuth flow completed successfully.")
    return RedirectResponse(url="/?auth=success")


@router.get("/auth/logout")
def auth_logout() -> RedirectResponse:
    """Delete the locally stored token (dev convenience)."""
    if settings.TOKEN_FILE.exists():
        settings.TOKEN_FILE.unlink()
        logger.info("Deleted local token file %s", settings.TOKEN_FILE)
    if settings.AUTH_EMAIL_FILE.exists():
        settings.AUTH_EMAIL_FILE.unlink()
        logger.info("Deleted local auth-email file %s", settings.AUTH_EMAIL_FILE)
    return RedirectResponse(url="/")


@router.get("/auth/status")
def auth_status() -> dict:
    """Report whether the app holds a usable Gmail token.

    Identity is read from the locally stored id_token email. The token is
    verified by gmail.load_credentials(), which refreshes it when expired.
    """
    creds = gmail.load_credentials()
    if creds is None:
        return {"authenticated": False, "detail": "Not authenticated. Visit /auth/login."}

    email = None
    if settings.AUTH_EMAIL_FILE.exists():
        try:
            email = json.loads(settings.AUTH_EMAIL_FILE.read_text(encoding="utf-8")).get("email")
        except Exception as exc:
            logger.warning("Could not read auth-email file: %s", exc)

    logger.info("Gmail token is usable for %s", email or "an authenticated account")
    return {"authenticated": True, "email": email or "unknown"}