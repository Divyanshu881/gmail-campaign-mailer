"""Credential encryption helpers.

Gmail OAuth tokens are stored in the `email_connections` table, never in
plaintext. Tokens are encrypted at rest with Fernet (AES-128-CBC + HMAC).

The key comes from EMAIL_TOKEN_ENCRYPTION_KEY. For local development a
persistent key file (ENCRYPTION_KEY_FILE, gitignored) is used so tokens
survive restarts without manual setup. In production, always set the env var.
"""

import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

def _load_or_create_key() -> str:
    env_key = settings.EMAIL_TOKEN_ENCRYPTION_KEY
    if env_key:
        return env_key.strip()

    key_file = settings.ENCRYPTION_KEY_FILE
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()

    key = Fernet.generate_key().decode("utf-8")
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(key, encoding="utf-8")
    logger.warning(
        "EMAIL_TOKEN_ENCRYPTION_KEY not set; generated one and saved to %s. "
        "Set the env var in production.",
        key_file,
    )
    return key


def _fernet() -> Fernet:
    key = _load_or_create_key()
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.error("EMAIL_TOKEN_ENCRYPTION_KEY is invalid: %s", exc)
        raise RuntimeError(
            "EMAIL_TOKEN_ENCRYPTION_KEY is invalid. Generate one with: "
            "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string; returns a URL-safe token (str)."""
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by encrypt(). Raises if the key is wrong."""
    if not token:
        return token
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        logger.error("Could not decrypt credential (wrong EMAIL_TOKEN_ENCRYPTION_KEY?).")
        raise ValueError(
            "Could not decrypt stored credentials. "
            "If EMAIL_TOKEN_ENCRYPTION_KEY changed, reconnect the provider."
        ) from exc
