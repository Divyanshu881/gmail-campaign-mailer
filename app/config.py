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

    # --- Google OAuth / Gmail API --------------------------------------------
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    OAUTH_REDIRECT_URI = os.getenv(
        "OAUTH_REDIRECT_URI", "http://localhost:8000/auth/callback"
    )

    # --- Credential encryption ------------------------------------------------
    # Fernet key (URL-safe base64, 32 bytes) used to encrypt provider tokens at
    # rest. Generate one with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # If unset in dev, a key is generated and persisted to ENCRYPTION_KEY_FILE
    # (gitignored) so tokens survive restarts. In production, always set it.
    EMAIL_TOKEN_ENCRYPTION_KEY = os.getenv("EMAIL_TOKEN_ENCRYPTION_KEY", "").strip()
    ENCRYPTION_KEY_FILE = Path(os.getenv("ENCRYPTION_KEY_FILE", "encryption.key"))

    # --- Campaign attachments --------------------------------------------------
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))

    # --- Redis queue + worker ---------------------------------------------------
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
    # Fallback daily cap, used only when a user has no subscription row.
    DAILY_EMAIL_QUOTA = int(os.getenv("DAILY_EMAIL_QUOTA", os.getenv("MAX_EMAILS", "50") or "50"))

    # --- Supabase ----------------------------------------------------------------
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
    # Service role key bypasses RLS. Server-side secret. Never expose to a browser.
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    # Used to verify Supabase Auth access tokens (HS256).
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "").strip()

    # --- Frontend / CORS -----------------------------------------------------------
    # The React UI lives in a separate repo (gmail-campaign-mailer-ui) and calls
    # this API cross-origin. Comma-separated allowed origins.
    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:8000"
    )
    # Where the React UI is served; OAuth callbacks (Gmail connect) redirect here.
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").strip().rstrip("/")

    # --- Subscriptions ---------------------------------------------------------------
    # Admin email: only this user can access /api/admin/* endpoints.
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "").strip()
    # Free trial duration in days for new users.
    TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14") or "14")

    def gmail_configured(self) -> bool:
        return bool(self.GOOGLE_CLIENT_ID and self.GOOGLE_CLIENT_SECRET)

    def supabase_configured(self) -> bool:
        return bool(self.SUPABASE_URL and self.SUPABASE_JWT_SECRET)


settings = Settings()
