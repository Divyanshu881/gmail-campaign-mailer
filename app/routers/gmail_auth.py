"""Gmail connection routes, routed through EmailProvider.

The token is stored encrypted in the `email_connections` table instead of a
plaintext file.

`/auth/login` and `/auth/logout` are full-page browser redirects (Google's own
OAuth flow requires that), so they can't carry an `Authorization` header. The
caller instead passes their Supabase access token as a `token` query param,
which is verified here (same as every other protected endpoint) to derive the
user id - never trusted directly from the query string. `/auth/status` is
called via `fetch()`, so it uses the normal Bearer-token dependency.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app import auth, connections
from app.config import settings
from app.providers import get_provider
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

router = APIRouter()

PROVIDER = "gmail"
_provider = get_provider(PROVIDER)


def _error_page(title: str, message: str) -> HTMLResponse:
    return HTMLResponse(
        f"<h1>{title}</h1><p>{message}</p>"
        "<p><a href='/'>Back to home</a></p>",
        status_code=400,
    )


def _user_id_from_token(token: Optional[str]) -> str:
    """Verify the caller's Supabase access token and return its subject.

    Used instead of a raw `user_id` query param so a browser navigation can't
    be used to connect/disconnect Gmail for an arbitrary account.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing access token. Sign in first.")
    claims = auth.verify_supabase_token(token)
    return claims["sub"]


@router.get("/auth/login")
def auth_login(token: Optional[str] = Query(default=None)) -> RedirectResponse:
    """Start the Gmail OAuth flow. Redirects the user to Google's consent screen."""
    uid = _user_id_from_token(token)
    try:
        result = _provider.connect(user_id=uid)
    except ProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    logger.info("Redirecting user %s to Google consent screen", uid)
    return RedirectResponse(result["auth_url"])


@router.get("/auth/callback")
def auth_callback(
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
) -> HTMLResponse:
    """Handle Google's redirect after the user approves/denies consent."""
    params = {"code": code, "state": state, "error": error}
    try:
        connection = _provider.handle_callback(state=state, params=params)
    except ProviderError as exc:
        logger.error("Gmail OAuth callback failed: %s", exc)
        return _error_page("Authorization failed", str(exc))

    logger.info("Gmail connection saved for user %s", connection.get("user_id"))
    # Send the user back to the React UI's Settings page.
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings?auth=success")


@router.get("/auth/logout")
def auth_logout(token: Optional[str] = Query(default=None)) -> RedirectResponse:
    """Disconnect Gmail for the authenticated caller."""
    uid = _user_id_from_token(token)
    connection = connections.get_connection_by_user(uid, PROVIDER)
    if connection is not None:
        _provider.disconnect(connection)
        logger.info("Disconnected Gmail for user %s", uid)
    return RedirectResponse(url=f"{settings.FRONTEND_URL}/settings")


@router.get("/auth/status")
def auth_status(user: dict = Depends(auth.get_current_user)) -> dict:
    """Report whether the authenticated caller holds a usable Gmail connection.

    The stored (encrypted) token is decrypted and refreshed if needed.
    """
    uid = user["sub"]
    connection = connections.get_connection_by_user(uid, PROVIDER)
    if connection is None:
        return {
            "authenticated": False,
            "provider": PROVIDER,
            "detail": "No Gmail connection found. Visit /auth/login.",
        }

    result = _provider.validate(connection)
    logger.info(
        "Gmail connection status for user %s: valid=%s (%s)",
        uid,
        result["valid"],
        result.get("email"),
    )
    return {
        "authenticated": result["valid"],
        "provider": PROVIDER,
        "email": result.get("email"),
        "detail": result.get("detail"),
    }
