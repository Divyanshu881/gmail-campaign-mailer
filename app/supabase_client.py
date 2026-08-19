"""Shared Supabase clients.

A single lazy, cached service-role client is used by auth.py (user upsert) and
connections.py (email_connections). The service role key bypasses RLS and must
only ever be used server-side.
"""

import logging

from app.config import settings

logger = logging.getLogger(__name__)

_service_client = None


def service_client():
    """Lazily build a PostgREST client with the service role key (bypasses RLS)."""
    global _service_client
    if _service_client is None:
        if not (settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY):
            return None
        from supabase import create_client

        _service_client = create_client(
            settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY
        )
    return _service_client
