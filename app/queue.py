"""Redis-backed campaign job queue (Phase 5).

A campaign is enqueued as a single job containing {campaign_id, user_id}; the
worker (app/worker.py) pops one job at a time with BLPOP and processes its
pending contacts one email at a time with a configurable delay. Using a plain
Redis list keeps the queue dependency small (works with local Redis or Upstash
via REDIS_URL) and gives the worker full control over the send loop.

If Redis is not configured/reachable the queue degrades gracefully:
enqueue_campaign() returns False and the /start endpoint refuses to queue.
"""

import json
import logging
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from app.config import settings

logger = logging.getLogger(__name__)

_client = None

# redis-py lets connection-URL query args override kwargs ("querystring
# arguments always win"). A `socket_timeout` in the URL (common on shared/Upstash
# Redis) would abort blocking commands early: BLPOP raises "Timeout reading from
# socket" after that timeout even though the server is still holding the
# connection. Strip it, then pass socket_timeout=None explicitly below.
#
# NOTE: redis-py 8.x ALSO changed the default socket_timeout to 5s (7.x used
# None) - so we must pass socket_timeout=None ourselves or every BLPOP aborts
# after 5 seconds. None means "block for the full server-side timeout".
_BLOCKING_UNSAFE_PARAMS = {"socket_timeout"}


def _strip_blocking_unsafe_params(url: str) -> str:
    parsed = urlparse(url)
    query = {
        k: v for k, v in parse_qs(parsed.query).items()
        if k not in _BLOCKING_UNSAFE_PARAMS
    }
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def redis_client():
    """Lazily build a shared Redis client, or None when not configured."""
    global _client
    if not settings.REDIS_URL:
        return None
    if _client is None:
        try:
            import redis
        except ImportError:
            logger.warning("redis package is not installed; run: pip install redis")
            return None
        try:
            url = _strip_blocking_unsafe_params(settings.REDIS_URL)
            # socket_timeout=None is REQUIRED for blocking commands (BLPOP):
            # redis-py 8 defaults it to 5s and a URL ?socket_timeout would
            # override any kwargs, so both are handled here.
            _client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=None)
            _client.ping()
        except Exception as exc:
            logger.error("Redis connection failed (%s): %s", settings.REDIS_URL, exc)
            _client = None
            return None
    return _client


def queue_configured() -> bool:
    return redis_client() is not None


def enqueue_campaign(campaign_id: str, user_id: str) -> bool:
    """Push a campaign job onto the queue. Returns False if Redis is unavailable."""
    client = redis_client()
    if client is None:
        logger.warning("Redis not configured; cannot queue campaign %s", campaign_id)
        return False
    payload = json.dumps({"campaign_id": campaign_id, "user_id": user_id})
    client.rpush(settings.CAMPAIGN_QUEUE, payload)
    logger.info("Queued campaign %s (user %s) on queue '%s'", campaign_id, user_id, settings.CAMPAIGN_QUEUE)
    return True


def _is_transient_socket_error(exc) -> bool:
    """True for redis-py socket read/connect timeouts - retryable, not fatal."""
    try:
        from redis.exceptions import (
            ConnectionError as RedisConnectionError,
            TimeoutError as RedisTimeoutError,
        )
        return isinstance(exc, (RedisConnectionError, RedisTimeoutError))
    except ImportError:
        return type(exc).__name__ in (
            "TimeoutError", "ConnectionError", "ReadTimeoutError", "ConnectionTimeoutError",
        )


def dequeue_job(timeout: int = 30) -> dict | None:
    """Block until a job is available (or timeout elapses). Returns a dict or None.

    A socket timeout here does NOT lose the job (BLPOP is aborted client-side,
    the job stays in the list) - it is logged as a warning and we retry.
    """
    client = redis_client()
    if client is None:
        return None
    try:
        result = client.blpop(settings.CAMPAIGN_QUEUE, timeout=timeout)
    except Exception as exc:
        if _is_transient_socket_error(exc):
            logger.warning("Redis BLPOP interrupted (%s); job stays queued, retrying", exc)
        else:
            logger.error("Redis BLPOP failed: %s", exc)
        return None
    if result is None:
        return None
    _queue_name, payload = result
    try:
        return json.loads(payload)
    except (json.JSONDecodeError, TypeError) as exc:
        logger.warning("Dropping malformed queue payload: %s", exc)
        return None
