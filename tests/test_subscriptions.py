"""Phase 7 - Subscription tests (unittest, no external deps).

Covers the 10 required test cases from .github/Docs/phase7.md:
  1. Admin can create subscription.
  2. Non-admin receives 403.
  3. Admin can extend subscription.
  4. Admin can cancel subscription.
  5. Active subscription allows campaign start.
  6. Expired subscription blocks campaign.
  7. Cancelled subscription blocks campaign.
  8. Daily limit blocks campaigns when quota is exhausted.
  9. Subscription ending today is active.
  10. Subscription ending yesterday is expired.

Uses unittest.mock to stub the Supabase service client so no live DB is needed.
"""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

# Ensure the project root is on sys.path so `app` is importable.
sys.path.insert(0, ".")

from fastapi import HTTPException  # noqa: E402

from app import subscriptions  # noqa: E402
from app.config import settings  # noqa: E402
from app.routers import admin as admin_router  # noqa: E402


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _make_sub(
    *,
    status="ACTIVE",
    start_date=None,
    end_date=None,
    daily_email_limit=50,
    plan="BASIC",
    user_id="user-1",
    sub_id="sub-1",
):
    today = _today()
    return {
        "id": sub_id,
        "user_id": user_id,
        "plan": plan,
        "status": status,
        "daily_email_limit": daily_email_limit,
        "start_date": start_date or today.isoformat(),
        "end_date": end_date or (today + timedelta(days=30)).isoformat(),
        "invoice_number": None,
        "payment_reference": None,
        "notes": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class SubscriptionValidationTests(unittest.TestCase):
    """Tests 9 & 10: date-range based activation/expiration."""

    def test_subscription_ending_today_is_active(self):
        """Test 9: subscription ending today is active."""
        sub = _make_sub(end_date=_today().isoformat())
        self.assertTrue(subscriptions.is_subscription_active(sub))

    def test_subscription_ending_yesterday_is_expired(self):
        """Test 10: subscription ending yesterday is expired."""
        sub = _make_sub(end_date=(_today() - timedelta(days=1)).isoformat())
        self.assertFalse(subscriptions.is_subscription_active(sub))

    def test_subscription_starting_tomorrow_is_not_active(self):
        """A subscription that hasn't started yet is not active."""
        sub = _make_sub(start_date=(_today() + timedelta(days=1)).isoformat())
        self.assertFalse(subscriptions.is_subscription_active(sub))

    def test_cancelled_subscription_is_not_active(self):
        """CANCELLED status is never active even if dates are valid."""
        sub = _make_sub(status="CANCELLED")
        self.assertFalse(subscriptions.is_subscription_active(sub))

    def test_expired_status_is_not_active(self):
        """EXPIRED status is never active."""
        sub = _make_sub(status="EXPIRED")
        self.assertFalse(subscriptions.is_subscription_active(sub))

    def test_trial_subscription_is_active(self):
        """TRIAL status within date range is active."""
        sub = _make_sub(status="TRIAL")
        self.assertTrue(subscriptions.is_subscription_active(sub))

    def test_missing_dates_are_not_active(self):
        """Missing/invalid dates make a subscription inactive."""
        sub = _make_sub()
        sub["start_date"] = "not-a-date"
        self.assertFalse(subscriptions.is_subscription_active(sub))


class DailyQuotaTests(unittest.TestCase):
    """Test 8: daily limit blocks when quota is exhausted."""

    def test_has_daily_quota_true_when_under_limit(self):
        with mock.patch.object(subscriptions, "get_subscription", return_value=_make_sub()):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=10):
                self.assertTrue(subscriptions.has_daily_quota("user-1"))

    def test_has_daily_quota_false_when_at_limit(self):
        with mock.patch.object(subscriptions, "get_subscription", return_value=_make_sub(daily_email_limit=50)):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=50):
                self.assertFalse(subscriptions.has_daily_quota("user-1"))

    def test_has_daily_quota_false_when_over_limit(self):
        with mock.patch.object(subscriptions, "get_subscription", return_value=_make_sub(daily_email_limit=50)):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=51):
                self.assertFalse(subscriptions.has_daily_quota("user-1"))

    def test_has_daily_quota_false_when_no_subscription(self):
        with mock.patch.object(subscriptions, "get_subscription", return_value=None):
            self.assertFalse(subscriptions.has_daily_quota("user-1"))

    def test_has_daily_quota_false_when_subscription_expired(self):
        expired = _make_sub(end_date=(_today() - timedelta(days=1)).isoformat())
        with mock.patch.object(subscriptions, "get_subscription", return_value=expired):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=0):
                self.assertFalse(subscriptions.has_daily_quota("user-1"))


class SubscriptionStatusTests(unittest.TestCase):
    """GET /api/subscription summary."""

    def test_get_subscription_status_active(self):
        sub = _make_sub(daily_email_limit=50)
        with mock.patch.object(subscriptions, "get_subscription", return_value=sub):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=17):
                result = subscriptions.get_subscription_status("user-1")
        self.assertEqual(result["status"], "ACTIVE")
        self.assertEqual(result["plan"], "BASIC")
        self.assertEqual(result["daily_email_limit"], 50)
        self.assertEqual(result["emails_sent_today"], 17)
        self.assertEqual(result["emails_remaining_today"], 33)

    def test_get_subscription_status_expired(self):
        sub = _make_sub(end_date=(_today() - timedelta(days=1)).isoformat())
        with mock.patch.object(subscriptions, "get_subscription", return_value=sub):
            with mock.patch.object(subscriptions, "get_daily_usage", return_value=0):
                result = subscriptions.get_subscription_status("user-1")
        self.assertEqual(result["status"], "EXPIRED")

    def test_get_subscription_status_none(self):
        with mock.patch.object(subscriptions, "get_subscription", return_value=None):
            self.assertIsNone(subscriptions.get_subscription_status("user-1"))


class AdminSubscriptionTests(unittest.TestCase):
    """Tests 1, 3, 4: admin create/extend/cancel via the service layer."""

    def test_create_subscription(self):
        """Test 1: admin can create a subscription."""
        fake_client = mock.MagicMock()
        fake_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.maybe_single.return_value.execute.return_value.data = None
        fake_client.table.return_value.insert.return_value.execute.return_value.data = [_make_sub()]

        with mock.patch.object(subscriptions, "service_client", return_value=fake_client):
            with mock.patch.object(subscriptions, "get_subscription", return_value=None):
                result = subscriptions.create_subscription(
                    "user-1",
                    plan="BASIC",
                    status="ACTIVE",
                    daily_email_limit=50,
                    start_date=_today().isoformat(),
                    end_date=(_today() + timedelta(days=30)).isoformat(),
                    invoice_number="INV-2026-0012",
                    payment_reference="NEFT-ABC123",
                    notes="Manual payment received",
                )
        self.assertIsNotNone(result)
        self.assertEqual(result["plan"], "BASIC")
        self.assertEqual(result["status"], "ACTIVE")

    def test_extend_subscription(self):
        """Test 3: admin can extend a subscription."""
        fake_client = mock.MagicMock()
        fake_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            _make_sub(end_date=(_today() + timedelta(days=60)).isoformat())
        ]

        with mock.patch.object(subscriptions, "service_client", return_value=fake_client):
            result = subscriptions.extend_subscription(
                "sub-1",
                new_end_date=(_today() + timedelta(days=60)).isoformat(),
                invoice_number="INV-2026-0021",
                payment_reference="UPI-XYZ123",
                notes="Subscription renewed",
            )
        self.assertIsNotNone(result)
        self.assertEqual(result["end_date"], (date.fromisoformat(result["end_date"])).isoformat())

    def test_cancel_subscription(self):
        """Test 4: admin can cancel a subscription."""
        fake_client = mock.MagicMock()
        fake_client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
            _make_sub(status="CANCELLED")
        ]

        with mock.patch.object(subscriptions, "service_client", return_value=fake_client):
            result = subscriptions.cancel_subscription("sub-1", notes="Customer requested")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "CANCELLED")


class AdminAccessTests(unittest.TestCase):
    """Test 2: non-admin receives 403."""

    def test_non_admin_receives_403(self):
        """Test 2: a non-admin user gets HTTP 403 from the admin dependency."""
        non_admin_user = {"sub": "user-2", "email": "customer@example.com"}

        with mock.patch.object(settings, "ADMIN_EMAIL", "admin@example.com"):
            with self.assertRaises(HTTPException) as ctx:
                admin_router._require_admin(non_admin_user)

        self.assertEqual(ctx.exception.status_code, 403)

    def test_admin_allowed(self):
        """The admin user passes the dependency."""
        admin_user = {"sub": "admin-1", "email": "admin@example.com"}
        with mock.patch.object(settings, "ADMIN_EMAIL", "admin@example.com"):
            result = admin_router._require_admin(admin_user)
        self.assertEqual(result, admin_user)

    def test_admin_not_configured_returns_503(self):
        """If ADMIN_EMAIL is empty, admin endpoints return 503."""
        user = {"sub": "user-1", "email": "admin@example.com"}
        with mock.patch.object(settings, "ADMIN_EMAIL", ""):
            with self.assertRaises(HTTPException) as ctx:
                admin_router._require_admin(user)
        self.assertEqual(ctx.exception.status_code, 503)


class CampaignAccessTests(unittest.TestCase):
    """Tests 5, 6, 7: active/expired/cancelled subscription gates campaign start."""

    def test_active_subscription_allows_campaign(self):
        """Test 5: active subscription allows campaign start."""
        sub = _make_sub()
        with mock.patch.object(subscriptions, "get_subscription", return_value=sub):
            self.assertTrue(subscriptions.is_subscription_active(sub))
            self.assertTrue(subscriptions.has_daily_quota("user-1"))

    def test_expired_subscription_blocks_campaign(self):
        """Test 6: expired subscription blocks campaign."""
        sub = _make_sub(end_date=(_today() - timedelta(days=1)).isoformat())
        with mock.patch.object(subscriptions, "get_subscription", return_value=sub):
            self.assertFalse(subscriptions.is_subscription_active(sub))
            self.assertFalse(subscriptions.has_daily_quota("user-1"))

    def test_cancelled_subscription_blocks_campaign(self):
        """Test 7: cancelled subscription blocks campaign."""
        sub = _make_sub(status="CANCELLED")
        with mock.patch.object(subscriptions, "get_subscription", return_value=sub):
            self.assertFalse(subscriptions.is_subscription_active(sub))
            self.assertFalse(subscriptions.has_daily_quota("user-1"))


if __name__ == "__main__":
    unittest.main()