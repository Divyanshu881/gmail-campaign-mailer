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
    TOKEN_FILE = Path(os.getenv("TOKEN_FILE", "token.json"))
    # Holds the authenticated Gmail address (from the OAuth id_token), stored
    # separately because Credentials.to_json() does not persist the id_token.
    AUTH_EMAIL_FILE = Path(os.getenv("AUTH_EMAIL_FILE", "token_email.json"))

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
