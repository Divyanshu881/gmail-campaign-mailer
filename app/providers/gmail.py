"""GmailProvider - Gmail implementation of EmailProvider.

Owns the Google OAuth flow (built on app/gmail.py) and persists connections in
the `email_connections` table with the token encrypted at rest.
"""

import json
import logging
import secrets
from typing import Optional

from google_auth_oauthlib.flow import Flow

from app import connections, gmail, security
from app.config import settings
from app.providers.base import EmailProvider, ProviderError
from app.providers import register
from app.queue import redis_client as _queue_redis_client

logger = logging.getLogger(__name__)

# Pending OAuth flows are stored in Redis (keyed by the CSRF state) so the state
# survives uvicorn --reload restarts and multi-worker deployments. A TTL expires
# abandoned flows. If Redis is unavailable we fall back to an in-memory dict so
# the dev flow still works (but then a server restart mid-flow aborts it).
_PENDING_FLOW_TTL = 600
_PENDING_FLOW_PREFIX = "oauth:pending:"
_pending_flows: dict[str, dict] = {}


def _store_pending_flow(state: str, data: dict) -> None:
    client = _queue_redis_client()
    if client is not None:
        try:
            client.set(
                f"{_PENDING_FLOW_PREFIX}{state}",
                json.dumps(data),
                ex=_PENDING_FLOW_TTL,
            )
            return
        except Exception as exc:
            logger.warning("Redis unavailable for OAuth state; using in-memory store: %s", exc)
    _pending_flows[state] = data


def _pop_pending_flow(state: str) -> Optional[dict]:
    client = _queue_redis_client()
    if client is not None:
        key = f"{_PENDING_FLOW_PREFIX}{state}"
        try:
            raw = client.get(key)
            if raw is not None:
                client.delete(key)
                try:
                    return json.loads(raw)
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Dropping malformed pending OAuth flow for state=%s: %s", state, exc)
                    return None
        except Exception as exc:
            logger.warning("Redis unavailable for OAuth state; using in-memory store: %s", exc)
    return _pending_flows.pop(state, None)


def _rehydrate_flow(data: dict) -> Flow:
    """Rebuild a Flow from the pieces stored by connect().

    The full google_auth_oauthlib Flow has no from_json(); reconstructing it from
    the client config + the PKCE code_verifier is enough for fetch_token().
    """
    flow = Flow.from_client_config(data["client_config"], scopes=data.get("scopes") or gmail.SCOPES)
    flow.redirect_uri = data["redirect_uri"]
    code_verifier = data.get("code_verifier")
    if code_verifier:
        flow.code_verifier = code_verifier
    return flow


@register
class GmailProvider(EmailProvider):
    provider_type = "gmail"

    # --- authorization flow ------------------------------------------------

    def connect(self, user_id: str) -> dict:
        if not gmail.credentials_configured():
            raise ProviderError(
                "Google OAuth credentials are not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env (see .env.example)."
            )

        flow = gmail.build_flow()
        state = secrets.token_urlsafe(32)

        # authorization_url() is what generates flow.code_verifier (PKCE) - it
        # must run before we read it, and it lives on the Flow itself, not on
        # flow.oauth2session.
        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
        )

        _store_pending_flow(
            state,
            {
                "client_config": gmail.client_config(),
                "redirect_uri": settings.OAUTH_REDIRECT_URI,
                "code_verifier": flow.code_verifier,
                "scopes": list(gmail.SCOPES),
                "user_id": user_id,
            },
        )
        logger.info("Starting Gmail OAuth flow for user %s (state=%s)", user_id, state)
        return {"auth_url": authorization_url}

    def handle_callback(self, state: str, params: dict) -> dict:
        error = params.get("error")
        if error:
            raise ProviderError(f"Google returned an OAuth error: {error}")

        pending = _pop_pending_flow(state)
        if pending is None:
            raise ProviderError("Invalid or missing OAuth state (possible CSRF).")
        flow: Flow = _rehydrate_flow(pending)
        user_id: str = pending["user_id"]

        code = params.get("code")
        if not code:
            raise ProviderError("No authorization code was returned by Google.")

        if not gmail.credentials_configured():
            raise ProviderError(
                "Google OAuth credentials are not configured. "
                "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env (see .env.example)."
            )

        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            logger.exception("Failed to exchange authorization code")
            raise ProviderError(f"Could not exchange the code for a token: {exc}")

        creds = flow.credentials
        email = gmail.id_token_email(creds)
        if not email:
            logger.warning("Could not determine the authenticated Gmail email from the id_token.")

        encrypted = security.encrypt(gmail.credentials_to_json(creds))
        stored = connections.create_connection(
            user_id=user_id,
            provider=self.provider_type,
            encrypted_token=encrypted,
            account_email=email,
            status="active",
        )
        if stored is None:
            raise ProviderError(
                "Gmail authorized, but the connection could not be saved "
                "(Supabase service role not configured?)."
            )

        logger.info("Gmail connected for user %s (account=%s)", user_id, email or "unknown")
        return stored

    # --- connection management --------------------------------------------

    def disconnect(self, connection: dict) -> None:
        self._revoke(connection)
        connections.delete_connection(connection.get("id", ""))

    def validate(self, connection: dict) -> dict:
        creds = self._credentials(connection)
        if creds is None:
            self._record_invalid(connection)
            return {"valid": False, "email": connection.get("account_email"), "detail": "Stored credentials are no longer usable; reconnect Gmail."}

        valid = creds.valid or (creds.expired and creds.refresh_token)
        if not valid:
            self._record_invalid(connection)
            return {"valid": False, "email": connection.get("account_email"), "detail": "Stored credentials are invalid; reconnect Gmail."}

        connections.update_connection(
            connection.get("id", ""),
            status="active",
            last_validated_at=connections.now_iso(),
        )
        return {
            "valid": True,
            "email": connection.get("account_email"),
            "detail": "Connected and usable.",
        }

    def send_email(
        self,
        connection: dict,
        *,
        to: str,
        subject: str,
        body: str,
        html: Optional[str] = None,
        attachments: Optional[list] = None,
    ) -> dict:
        creds = self._credentials(connection)
        if creds is None:
            raise ProviderError("Stored Gmail credentials are no longer usable; reconnect Gmail.")
        return gmail.send_message(creds, to, subject, body, html=html, attachments=attachments)

    # --- helpers -----------------------------------------------------------

    def _credentials(self, connection: dict):
        """Decrypt stored credentials and restore a usable Credentials object."""
        encrypted = connection.get("encrypted_token") or ""
        if not encrypted:
            return None
        try:
            json_str = security.decrypt(encrypted)
        except ValueError as exc:
            logger.error("Decryption failed for connection %s: %s", connection.get("id"), exc)
            return None
        return gmail.credentials_from_json(json_str)

    def _revoke(self, connection: dict) -> None:
        """Best-effort Google token revocation; never blocks disconnect."""
        creds = self._credentials(connection)
        if creds is None:
            return
        token = creds.refresh_token or creds.token
        if not token:
            return
        try:
            import requests

            requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
                timeout=10,
            )
            logger.info("Revoked Google token for connection %s", connection.get("id"))
        except Exception as exc:
            logger.warning("Google token revoke failed (ignoring): %s", exc)

    def _record_invalid(self, connection: dict) -> None:
        connections.update_connection(
            connection.get("id", ""),
            status="error",
            last_validated_at=connections.now_iso(),
        )