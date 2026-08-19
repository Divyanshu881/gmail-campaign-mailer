"""Phase 3 - Gmail connection routes, routed through EmailProvider.

The /auth/* paths are unchanged for the dev page; internally they now go
through GmailProvider, and the token is stored encrypted in the
`email_connections` table instead of a plaintext file.

`user_id` is optional: dev flows without a Supabase session fall back to a
fixed dev user id.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from app import connections
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


@router.get("/auth/login")
def auth_login(user_id: Optional[str] = Query(default=None)) -> RedirectResponse:
    """Start the Gmail OAuth flow. Redirects the user to Google's consent screen."""
    uid = connections.resolve_user_id(user_id)
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
    return RedirectResponse(url="/?auth=success")


@router.get("/auth/logout")
def auth_logout(user_id: Optional[str] = Query(default=None)) -> RedirectResponse:
    """Disconnect Gmail for the given user (dev convenience)."""
    uid = connections.resolve_user_id(user_id)
    connection = connections.get_connection_by_user(uid, PROVIDER)
    if connection is not None:
        _provider.disconnect(connection)
        logger.info("Disconnected Gmail for user %s", uid)
    return RedirectResponse(url="/")


@router.get("/auth/status")
def auth_status(user_id: Optional[str] = Query(default=None)) -> dict:
    """Report whether the user holds a usable Gmail connection.

    The stored (encrypted) token is decrypted and refreshed if needed.
    """
    uid = connections.resolve_user_id(user_id)
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