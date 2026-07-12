"""Tests for the REAL-mode safety gate (pure logic, no Flask/broker).

Long-only bridge. These guards only ever run in REAL-money mode; SIMULATE and
mock are untouched. Everything defaults OFF so importing/enabling the module
cannot, by itself, place a real order.
"""
from __future__ import annotations

from datetime import datetime, timezone

from trader.safety import evaluate_real, within_regular_hours

# 2026-01-05 is a Monday; January is EST (UTC-5), so 14:30Z == 09:30 ET.
MON_OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=timezone.utc)   # 09:30 ET exactly
MON_MID = datetime(2026, 1, 5, 18, 0, tzinfo=timezone.utc)     # 13:00 ET
MON_CLOSE = datetime(2026, 1, 5, 21, 0, tzinfo=timezone.utc)   # 16:00 ET exactly
MON_EARLY = datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc)   # 08:00 ET
SUN = datetime(2026, 1, 4, 18, 0, tzinfo=timezone.utc)         # Sunday midday ET


# ---- within_regular_hours -------------------------------------------------

def test_rth_open_boundary_is_inclusive():
    assert within_regular_hours(MON_OPEN) is True


def test_rth_midday_is_open():
    assert within_regular_hours(MON_MID) is True


def test_rth_close_boundary_is_exclusive():
    assert within_regular_hours(MON_CLOSE) is False


def test_rth_before_open_is_closed():
    assert within_regular_hours(MON_EARLY) is False


def test_rth_weekend_is_closed():
    assert within_regular_hours(SUN) is False


def _open(**over):
    base = dict(
        action="open",
        allow_real_webhook=True,
        confirm=True,
        price=100.0,
        quantity=1,
        max_notional=0.0,
        max_daily_loss=0.0,
        realized_pnl_today=0.0,
        now_utc=MON_MID,
        enforce_market_hours=True,
    )
    base.update(over)
    return evaluate_real(**base)


# ---- opt-in ---------------------------------------------------------------

def test_open_happy_path_is_allowed():
    d = _open()
    assert d.ok is True and d.label == "OK"


def test_flag_off_is_disabled():
    d = _open(allow_real_webhook=False)
    assert d.ok is False and d.label == "DISABLED"


def test_missing_confirm_is_rejected():
    d = _open(confirm=False)
    assert d.ok is False and d.label == "CONFIRM_REQUIRED"


def test_confirm_must_be_boolean_true_not_truthy():
    d = _open(confirm="true")
    assert d.ok is False and d.label == "CONFIRM_REQUIRED"


# ---- circuit breakers -----------------------------------------------------

def test_market_closed_blocks_open():
    d = _open(now_utc=SUN)
    assert d.ok is False and d.label == "MARKET_CLOSED"


def test_market_hours_guard_can_be_disabled():
    d = _open(now_utc=SUN, enforce_market_hours=False)
    assert d.ok is True


def test_notional_cap_blocks_when_exceeded():
    d = _open(price=100.0, quantity=1, max_notional=50.0)
    assert d.ok is False and d.label == "NOTIONAL_EXCEEDED"


def test_notional_cap_allows_at_or_below_limit():
    assert _open(price=100.0, quantity=1, max_notional=100.0).ok is True


def test_notional_cap_disabled_when_zero():
    assert _open(price=1e9, quantity=1000, max_notional=0.0).ok is True


def test_daily_loss_kill_switch_trips():
    d = _open(max_daily_loss=100.0, realized_pnl_today=-150.0)
    assert d.ok is False and d.label == "KILL_SWITCH"


def test_daily_loss_below_threshold_is_allowed():
    assert _open(max_daily_loss=100.0, realized_pnl_today=-50.0).ok is True


def test_daily_loss_disabled_when_zero():
    assert _open(max_daily_loss=0.0, realized_pnl_today=-1e9).ok is True


# ---- closing must always be possible (only opt-in applies) ----------------

def test_close_allowed_outside_hours_and_over_notional():
    d = evaluate_real(
        action="close",
        allow_real_webhook=True,
        confirm=True,
        price=1e9,
        quantity=1000,
        max_notional=1.0,
        max_daily_loss=1.0,
        realized_pnl_today=-1e9,
        now_utc=SUN,
        enforce_market_hours=True,
    )
    assert d.ok is True and d.label == "OK"


def test_close_still_needs_confirmation():
    d = evaluate_real(
        action="close",
        allow_real_webhook=True,
        confirm=False,
        price=100.0,
        quantity=1,
        max_notional=0.0,
        max_daily_loss=0.0,
        realized_pnl_today=0.0,
        now_utc=MON_MID,
        enforce_market_hours=True,
    )
    assert d.ok is False and d.label == "CONFIRM_REQUIRED"


def test_close_flag_off_is_disabled():
    d = evaluate_real(
        action="close",
        allow_real_webhook=False,
        confirm=True,
        price=100.0,
        quantity=1,
        max_notional=0.0,
        max_daily_loss=0.0,
        realized_pnl_today=0.0,
        now_utc=MON_MID,
        enforce_market_hours=True,
    )
    assert d.ok is False and d.label == "DISABLED"
