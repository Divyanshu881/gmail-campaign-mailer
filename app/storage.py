"""Supabase Storage helpers for campaign attachments.

Attachments are stored in a private Supabase Storage bucket rather than local
disk, so the web process and the background worker - separate processes, and
separate services in production - can both reach them regardless of which one
handled the upload.

Objects are keyed as "{campaign_id}/{filename}".
"""

import logging
from typing import Optional

from app.config import settings
from app.supabase_client import service_client

logger = logging.getLogger(__name__)

BUCKET = settings.ATTACHMENTS_BUCKET


def ensure_bucket() -> None:
    """Create the attachments bucket if it doesn't exist yet. Safe to call repeatedly."""
    client = service_client()
    if client is None:
        return
    try:
        client.storage.create_bucket(BUCKET, options={"public": False})
        logger.info("Created storage bucket '%s'", BUCKET)
    except Exception as exc:
        # Already exists (the common case after the first run) or a transient
        # issue - either way, not fatal; upload/download will surface real
        # problems on their own.
        logger.debug("create_bucket('%s') skipped: %s", BUCKET, exc)


def upload_attachment(path: str, data: bytes) -> bool:
    """Upload attachment bytes to the bucket at `path`. Returns True on success."""
    client = service_client()
    if client is None:
        logger.warning("Supabase service role not configured; cannot upload attachment.")
        return False
    try:
        client.storage.from_(BUCKET).upload(
            path, data, file_options={"upsert": "true"}
        )
        return True
    except Exception as exc:
        logger.error("Attachment upload failed for '%s': %s", path, exc)
        return False


def download_attachment(path: str) -> Optional[bytes]:
    """Download attachment bytes from the bucket. Returns None if unavailable."""
    client = service_client()
    if client is None:
        return None
    try:
        return client.storage.from_(BUCKET).download(path)
    except Exception as exc:
        logger.error("Attachment download failed for '%s': %s", path, exc)
        return None
