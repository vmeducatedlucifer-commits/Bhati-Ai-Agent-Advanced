"""Login brute-force brake: per-key lockout, global bucket, escalation."""

from __future__ import annotations

import pytest

from app.api.v1 import auth as auth_module


@pytest.fixture(autouse=True)
def _clean_brake():
    auth_module._LOGIN_FAILURES.clear()
    auth_module._GLOBAL_FAILURES.clear()
    auth_module._BLOCKED_UNTIL.clear()
    auth_module._LOCKOUT_STRIKES.clear()
    yield
    auth_module._LOGIN_FAILURES.clear()
    auth_module._GLOBAL_FAILURES.clear()
    auth_module._BLOCKED_UNTIL.clear()
    auth_module._LOCKOUT_STRIKES.clear()


def test_five_failures_then_lockout_with_retry_after():
    now = 1_000_000.0
    for _ in range(5):
        auth_module._record_failure("9.9.9.9", now)
        now += 1.0
    remaining = auth_module._lockout_remaining("9.9.9.9", now)
    assert remaining == auth_module.BASE_BLOCK_S
    resp = auth_module._rate_limited_response(remaining)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == str(auth_module.BASE_BLOCK_S)


def test_lockout_escalates_on_repeat_offense():
    now = 2_000_000.0
    for _ in range(5):
        auth_module._record_failure("1.1.1.1", now)
    first = auth_module._lockout_remaining("1.1.1.1", now)
    assert first == auth_module.BASE_BLOCK_S
    # Offense during a later window escalates: 5min -> 10min.
    later = now + auth_module.MAX_BLOCK_S + 10
    for _ in range(5):
        auth_module._record_failure("1.1.1.1", later)
    second = auth_module._lockout_remaining("1.1.1.1", later)
    assert second == auth_module.BASE_BLOCK_S * 2


def test_global_bucket_catches_xff_rotation():
    """Attacker rotating X-Forwarded-For still trips the global brake."""
    now = 3_000_000.0
    for i in range(auth_module.GLOBAL_MAX_FAILURES):
        auth_module._record_failure(f"10.0.0.{i}", now)
    # A brand-new "IP" with zero personal failures is still limited.
    assert auth_module._lockout_remaining("192.168.99.99", now) > 0


def test_success_resets_the_key():
    now = 4_000_000.0
    for _ in range(3):
        auth_module._record_failure("5.5.5.5", now)
    auth_module._reset_key("5.5.5.5")
    assert auth_module._lockout_remaining("5.5.5.5", now) == 0
    assert "5.5.5.5" not in auth_module._LOGIN_FAILURES


def test_old_failures_age_out():
    now = 5_000_000.0
    auth_module._record_failure("6.6.6.6", now)
    far_future = now + auth_module.LOGIN_WINDOW_S + 1
    assert auth_module._lockout_remaining("6.6.6.6", far_future) == 0
