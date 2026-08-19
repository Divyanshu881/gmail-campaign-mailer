"""Phase 5 - background worker that executes queued campaigns.

Run it in its own process, separate from the FastAPI app (no HTTP request ever
stays open while sending):

    venv/bin/python -m app.worker                     # watch the queue forever
    venv/bin/python -m app.worker --once              # process a single job, then exit
    venv/bin/python -m app.worker --campaign <id>     # force-process one campaign now

For a local Redis on macOS: `brew install redis && redis-server`. Or point
REDIS_URL at an Upstash redis:// (or rediss://) URL and run this on Render as a
Background Worker.

The worker pops one campaign job at a time, sends that campaign's pending
contacts ONE email at a time with a configurable delay (SEND_DELAY_MIN/MAX,
default 30-75s) used as rate limiting - not a delivery guarantee. Each failed
email is retried once (MAX_SEND_ATTEMPTS=2), failures are recorded and sending
continues. The daily quota (DAILY_EMAIL_QUOTA) is enforced here server-side,
per email, before every send.
"""

import argparse
import logging
import random
import time

from app import campaign_validation, campaigns, connections, queue
from app.config import settings
from app.providers import get_provider
from app.providers.base import ProviderError

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_PAUSED = "paused"
STATUS_FAILED = "failed"


# --------------------------------------------------------------------------- #
# One campaign
# --------------------------------------------------------------------------- #


def process_campaign(campaign_id: str) -> None:
    """Send a queued campaign's pending contacts, one at a time."""
    campaign = campaigns.get_campaign(campaign_id)
    if campaign is None:
        logger.error("Campaign %s not found; dropping job", campaign_id)
        return
    if campaign.get("status") not in (STATUS_QUEUED, STATUS_RUNNING):
        logger.info("Campaign %s is '%s'; skipping (not queued/running)", campaign_id, campaign.get("status"))
        return

    user_id = campaign.get("user_id", "")
    logger.info("Starting campaign %s for user %s", campaign_id, user_id)

    connection = connections.get_connection(campaign.get("email_connection_id") or "")
    if connection is None:
        campaigns.update_campaign(campaign_id, status=STATUS_FAILED)
        logger.error("Campaign %s: email connection not found; marking failed", campaign_id)
        return

    try:
        provider = get_provider(connection.get("provider", "gmail"))
    except ProviderError as exc:
        campaigns.update_campaign(campaign_id, status=STATUS_FAILED)
        logger.error("Campaign %s: %s; marking failed", campaign_id, exc)
        return

    attachment_paths = [
        a.get("path")
        for a in campaign.get("attachments") or []
        if isinstance(a, dict) and a.get("path")
    ]

    started = campaign.get("started_at") or campaigns.now_iso()
    campaigns.update_campaign(
        campaign_id,
        status=STATUS_RUNNING,
        started_at=started,
        sent_count=campaign.get("sent_count") or 0,
        failed_count=campaign.get("failed_count") or 0,
    )

    pending = campaigns.get_contacts_by_status(campaign_id, "pending")
    logger.info("Campaign %s: %d pending contact(s) to send", campaign_id, len(pending))

    sent_count = campaign.get("sent_count") or 0
    failed_count = campaign.get("failed_count") or 0
    quota_hit = False

    for i, contact in enumerate(pending, start=1):
        # Server-side daily quota check - authoritative, never trust the client.
        used_today = campaigns.count_sent_today(user_id)
        if used_today >= settings.DAILY_EMAIL_QUOTA:
            quota_hit = True
            logger.warning(
                "Campaign %s: user %s hit the daily quota (%d/%d); pausing campaign",
                campaign_id, user_id, used_today, settings.DAILY_EMAIL_QUOTA,
            )
            break

        email = contact.get("email", "")
        try:
            subject, body = campaign_validation.render_templates(
                campaign.get("subject_template", ""),
                campaign.get("body_template", ""),
                contact.get("data") or {},
            )
        except Exception as exc:
            logger.warning("Campaign %s: template render failed for %s: %s", campaign_id, email, exc)
            campaigns.update_contact_status(
                contact["id"], status=STATUS_FAILED, reason=f"template error: {exc}", attempts=1
            )
            failed_count += 1
            campaigns.update_campaign(campaign_id, sent_count=sent_count, failed_count=failed_count)
            _rate_limit_delay(contact_id=contact["id"], campaign_id=campaign_id, last=(i == len(pending)))
            continue

        attempts, last_error = _send_with_retry(
            provider, connection, to=email, subject=subject, body=body, attachments=attachment_paths
        )

        if last_error is None:
            sent_count += 1
            campaigns.update_contact_status(
                contact["id"],
                status="sent",
                reason=None,
                sent_at=campaigns.now_iso(),
                attempts=attempts,
            )
            logger.info(
                "Campaign %s [%d/%d] sent to %s (attempts=%d)",
                campaign_id, i, len(pending), email, attempts,
            )
        else:
            failed_count += 1
            campaigns.update_contact_status(
                contact["id"], status=STATUS_FAILED, reason=last_error, attempts=attempts
            )
            logger.warning(
                "Campaign %s [%d/%d] FAILED for %s after %d attempt(s): %s",
                campaign_id, i, len(pending), email, attempts, last_error,
            )

        campaigns.update_campaign(campaign_id, sent_count=sent_count, failed_count=failed_count)
        _rate_limit_delay(contact_id=contact["id"], campaign_id=campaign_id, last=(i == len(pending)))

    # --- finalize ----------------------------------------------------------- #
    remaining = campaigns.get_contacts_by_status(campaign_id, "pending")
    if quota_hit:
        status = STATUS_PAUSED
        logger.warning(
            "Campaign %s paused: sent=%d failed=%d, %d still pending (quota). "
            "Restart tomorrow to resume.",
            campaign_id, sent_count, failed_count, len(remaining),
        )
    elif sent_count + failed_count >= len(pending) and not remaining:
        status = STATUS_COMPLETED
        campaigns.update_campaign(campaign_id, completed_at=campaigns.now_iso())
        logger.info(
            "Campaign %s completed: %d sent, %d failed.",
            campaign_id, sent_count, failed_count,
        )
    else:
        status = STATUS_PAUSED
        logger.warning(
            "Campaign %s paused unexpectedly: sent=%d failed=%d, %d pending remain.",
            campaign_id, sent_count, failed_count, len(remaining),
        )

    campaigns.update_campaign(
        campaign_id, status=status, sent_count=sent_count, failed_count=failed_count
    )


def _send_with_retry(provider, connection, *, to, subject, body, attachments):
    """Try sending up to MAX_SEND_ATTEMPTS times. Returns (attempts, error_or_None)."""
    attempts = 0
    last_error = None
    while attempts < settings.MAX_SEND_ATTEMPTS:
        attempts += 1
        try:
            provider.send_email(
                connection, to=to, subject=subject, body=body, html=None, attachments=attachments
            )
            return attempts, None
        except Exception as exc:
            last_error = str(exc)
            logger.warning("Send to %s failed on attempt %d: %s", to, attempts, exc)
            if attempts < settings.MAX_SEND_ATTEMPTS:
                logger.info("Retrying %s in %ds...", to, settings.SEND_RETRY_DELAY)
                time.sleep(settings.SEND_RETRY_DELAY)
    return attempts, last_error or "send failed"


def _rate_limit_delay(*, contact_id: str, campaign_id: str, last: bool) -> None:
    """Sleep between emails (rate limiting, not delivery guarantee)."""
    if last:
        return
    seconds = random.uniform(settings.SEND_DELAY_MIN, settings.SEND_DELAY_MAX)
    logger.info(
        "Campaign %s: rate-limit delay %.1fs before next email (contact %s)",
        campaign_id, seconds, contact_id,
    )
    time.sleep(seconds)


# --------------------------------------------------------------------------- #
# Crash recovery + main loop
# --------------------------------------------------------------------------- #


def recover_stuck_campaigns() -> int:
    """Requeue campaigns left in 'running'/'queued' by a crashed worker.

    The worker is the only process that clears these statuses, so on startup
    any campaign in 'running' was abandoned mid-run (or 'queued' lost its job).
    Requeueing them lets the loop resume. Duplicates are harmless: when a job is
    popped a second time the status guard in process_campaign skips it.
    """
    recovered = 0
    for status in (STATUS_QUEUED, STATUS_RUNNING):
        for campaign in campaigns.list_all_campaigns(status=status):
            if queue.enqueue_campaign(campaign.get("id", ""), campaign.get("user_id", "")):
                recovered += 1
    if recovered:
        logger.info("Recovered %d stuck campaign(s) back onto the queue", recovered)
    return recovered


def run_worker(*, once: bool = False, campaign_id: str | None = None) -> None:
    if campaign_id:
        process_campaign(campaign_id)
        return

    if not queue.queue_configured():
        logger.error(
            "Redis is not configured/reachable. Set REDIS_URL (e.g. redis://localhost:6379/0 "
            "or an Upstash URL) in .env. Local server: `brew install redis && redis-server`."
        )
        return

    recover_stuck_campaigns()
    logger.info(
        "Worker listening on Redis queue '%s' (delay %.0f-%.0fs, retries=%d, quota=%d/day). "
        "Ctrl+C to stop.",
        settings.CAMPAIGN_QUEUE,
        settings.SEND_DELAY_MIN,
        settings.SEND_DELAY_MAX,
        settings.MAX_SEND_ATTEMPTS - 1,
        settings.DAILY_EMAIL_QUOTA,
    )

    while True:
        job = queue.dequeue_job(timeout=30)
        if job is None:
            continue
        cid = job.get("campaign_id")
        if not cid:
            logger.warning("Skipping job without campaign_id: %s", job)
            continue
        logger.info("Dequeued campaign job: %s", cid)
        try:
            process_campaign(cid)
        except Exception as exc:
            logger.exception("Unhandled error while processing campaign %s: %s", cid, exc)
        if once:
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail Campaign Mailer background worker (Phase 5)")
    parser.add_argument("--once", action="store_true", help="Process a single queued job, then exit")
    parser.add_argument("--campaign", help="Force-process one campaign by id, then exit")
    args = parser.parse_args()
    run_worker(once=args.once, campaign_id=args.campaign)


if __name__ == "__main__":
    main()
