"""GmailProvider - Phase 3 Gmail implementation of EmailProvider.

Owns the Google OAuth flow (built on app/gmail.py) and persists connections in
the `email_connections` table with the token encrypted at rest.
"""

import logging
import secrets
from typing import Optional

from google_auth_oauthlib.flow import Flow

from app import connections, gmail, security
from app.providers.base import EmailProvider, ProviderError
from app.providers import register

logger = logging.getLogger(__name__)

# In-memory store of pending OAuth flows keyed by state (CSRF protection and
# PKCE code_verifier continuity between the two OAuth steps). Fine for the
# single-process dev server; swap for shared/session storage when the app runs
# on multiple workers.
_pending_flows: dict[str, dict] = {}


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
        _pending_flows[state] = {"flow": flow, "user_id": user_id}

        authorization_url, _ = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            state=state,
        )
        logger.info("Starting Gmail OAuth flow for user %s (state=%s)", user_id, state)
        return {"auth_url": authorization_url}

    def handle_callback(self, state: str, params: dict) -> dict:
        error = params.get("error")
        if error:
            raise ProviderError(f"Google returned an OAuth error: {error}")

        pending = _pending_flows.pop(state, None)
        if pending is None:
            raise ProviderError("Invalid or missing OAuth state (possible CSRF).")
        flow: Flow = pending["flow"]
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