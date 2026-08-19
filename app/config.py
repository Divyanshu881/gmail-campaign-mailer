"""Central configuration loaded from environment variables.

All secrets live in .env (gitignored). Nothing here should ever be
hardcoded or committed.
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# oauthlib (used by google-auth-oauthlib) raises a spurious "Scope has changed"
# error because Google normalizes the "email" scope in the token response.
# Relax that strict check. This does NOT change the scopes requested from the
# user; it only stops oauthlib from aborting on the legitimate normalization.
os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


class Settings:
    """Read-only settings. Values come from environment variables only."""

    # --- Google OAuth / Gmail API (Phase 0) ---------------------------------
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    OAUTH_REDIRECT_URI = os.getenv(
        "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback"
    )
    # Legacy Phase 0 local token files. Phase 3 stores credentials in the
    # `email_connections` table (encrypted) instead; these are kept for the
    # old helpers in app/gmail.py and are no longer used by the routers.
    TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "token.json"))
    # Holds the authenticated Gmail address (from the OAuth id_token), stored
    # separately because Credentials.to_json() does not persist the id_token.
    AUTH_EMAIL_FILE = Path(os.getenv("AUTH_EMAIL_FILE", "token_email.json"))

    # --- Credential encryption (Phase 3) ------------------------------------
    # Fernet key (URL-safe base64, 32 bytes) used to encrypt provider tokens at
    # rest. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If unset in dev, a key is generated and persisted to ENCRYPTION_KEY_FILE
    # (gitignored) so tokens survive restarts. In production, always set it.
    EMAIL_TOKEN_ENCRYPTION_KEY = os.getenv("EMAIL_TOKEN_ENCRYPTION_KEY", "").strip()
    ENCRYPTION_KEY_FILE = Path(os.getenv("ENCRYPTION_KEY_FILE", "encryption.key"))

    # --- Campaign attachments (Phase 4) --------------------------------------
    # Local directory where uploaded campaign attachments are stored during
    # development. Supabase Storage will replace this later (deployment phase).
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))

    # --- Redis queue + worker (Phase 5) ---------------------------------------
    # Local: "redis://localhost:6379/0". Upstash: the rediss:// URL from the
    # dashboard works as-is with redis-py (TCP, not the REST endpoint).
    REDIS_URL = os.getenv("REDIS_URL", "").strip()
    # Redis list that holds campaign jobs. Worker pops from it with BLPOP.
    CAMPAIGN_QUEUE = os.getenv("CAMPAIGN_QUEUE", "campaigns")
    # Rate limiting between emails: a random delay within [MIN, MAX] seconds.
    # This is throttling, NOT a guarantee of inbox placement.
    SEND_DELAY_MIN = int(os.getenv("SEND_DELAY_MIN", os.getenv("MIN_DELAY", "30") or "30"))
    SEND_DELAY_MAX = int(os.getenv("SEND_DELAY_MAX", os.getenv("MAX_DELAY", "75") or "75"))
    # Seconds to wait before retrying a failed send.
    SEND_RETRY_DELAY = int(os.getenv("SEND_RETRY_DELAY", "10") or "10")
    # Total send attempts per contact (1 initial + 1 retry = 2).
    MAX_SEND_ATTEMPTS = int(os.getenv("MAX_SEND_ATTEMPTS", "2") or "2")
    # Hard server-side cap: emails a user may send per day (all campaigns).
    DAILY_EMAIL_QUOTA = int(os.getenv("DAILY_EMAIL_QUOTA", os.getenv("MAX_EMAILS", "50") or "50"))

    # --- Supabase (Phase 1) --------------------------------------------------
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
    # Service role key bypasses RLS. Server-side secret. Never expose to a browser.
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    # Used to verify Supabase Auth access tokens (HS256).
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()

    def gmail_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    def supabase_configured(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_JWT_SECRET)


settings = Settings()
