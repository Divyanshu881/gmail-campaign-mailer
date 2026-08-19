"""EmailProvider abstraction (Phase 3).

Campaign/business logic depends only on this interface, never on Gmail (or any
provider) directly. New providers (SMTP, SES, Resend) implement the same
methods and register themselves; nothing in campaign logic changes.

A connection is a dict as stored in the `email_connections` table:
    {
        "id": "...",
        "user_id": "...",
        "provider": "gmail",
        "account_email": "me@gmail.com",
        "encrypted_token": "<encrypted>",
        "status": "active",
        ...
    }
"""

from abc import ABC, abstractmethod
from typing import Optional


class EmailProvider(ABC):
    """Operations every email provider must support.

    Methods receive the connection record (with its encrypted credentials) and
    are responsible for turning that into a usable provider session. Throwing
    a ProviderError with a user-facing message is the expected failure mode.
    """

    provider_type: str = "base"

    @abstractmethod
    def connect(self, user_id: str) -> dict:
        """Start authorization for a user.

        Returns {"auth_url": "<redirect the browser to>"}.
        """

    @abstractmethod
    def handle_callback(self, state: str, params: dict) -> dict:
        """Complete an authorization flow and persist the connection.

        `params` carries provider-specific callback data (e.g. OAuth code).
        Returns the stored connection record.
        """

    @abstractmethod
    def disconnect(self, connection: dict) -> None:
        """Revoke/remove the connection (best-effort provider-side revoke)."""

    @abstractmethod
    def validate(self, connection: dict) -> dict:
        """Confirm the connection is usable right now.

        Returns {"valid": bool, "email": str, "detail": str}.
        """

    @abstractmethod
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
        """Send one email through this provider.

        Returns {"status": "sent", "message_id": "...", "to": "..."}.
        """

    def send_test_email(
        self, connection: dict, *, to: str, subject: str, body: str
    ) -> dict:
        """Convenience: send a plain test email via send_email()."""
        return self.send_email(
            connection, to=to, subject=subject, body=body, html=None, attachments=None
        )


class ProviderError(Exception):
    """Raised by a provider when an operation fails with a user-facing message."""