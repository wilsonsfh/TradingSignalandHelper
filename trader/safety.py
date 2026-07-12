"""REAL-money safety gate for the TradingView webhook.

Pure decision logic (no Flask, no broker) so it is trivially testable and can
never place an order by itself. These guards run ONLY in REAL-money mode; the
SIMULATE / mock paths never reach here. Every knob defaults OFF/absent, so the
gate's default answer for an un-opted-in host is "DISABLED".

Long-only bridge: `open` = enter long, `close` = exit long. Closing must always
be possible once opted in, so only the double opt-in applies to `close`; the
circuit breakers and market-hours guard apply to `open` only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone

try:  # Python 3.9+ standard library; relies on system tz database.
    from zoneinfo import ZoneInfo

    _NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - defensive; macOS/Linux ship tzdata
    _NY = None

_RTH_OPEN = time(9, 30)
_RTH_CLOSE = time(16, 0)


@dataclass(frozen=True)
class RealModeDecision:
    """Result of the REAL-mode gate. ok=True means the order may proceed."""
    ok: bool
    label: str
    message: str = ""


_OK = RealModeDecision(True, "OK", "")


def within_regular_hours(now_utc: datetime) -> bool:
    """True during US equity Regular Trading Hours (Mon-Fri, 09:30-16:00 ET).

    Open is inclusive, close is exclusive. Holidays are NOT modelled here (the
    broker still rejects a holiday order); this is a coarse safety fence, not a
    market calendar.
    """
    if _NY is None:  # pragma: no cover - no tz data available
        raise RuntimeError("time-zone data unavailable; cannot check market hours")
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    et = now_utc.astimezone(_NY)
    if et.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    return _RTH_OPEN <= et.timetz().replace(tzinfo=None) < _RTH_CLOSE


def evaluate_real(
    *,
    action: str,
    allow_real_webhook: bool,
    confirm: object,
    price: float,
    quantity: int,
    max_notional: float,
    max_daily_loss: float,
    realized_pnl_today: float,
    now_utc: datetime,
    enforce_market_hours: bool = True,
) -> RealModeDecision:
    """Decide whether a REAL-money webhook order may proceed.

    Checks, in order: (1) the ALLOW_REAL_WEBHOOK opt-in flag, (2) a per-alert
    literal ``confirm: true``. For ``open`` orders it then applies (3) the
    market-hours fence, (4) the per-order notional cap, and (5) the daily
    realized-loss kill-switch. A cap of 0 disables that particular breaker.
    """
    if not allow_real_webhook:
        return RealModeDecision(
            False, "DISABLED",
            "webhook auto-trading is disabled in REAL-money mode (set ALLOW_REAL_WEBHOOK=true)",
        )
    if confirm is not True:
        return RealModeDecision(
            False, "CONFIRM_REQUIRED",
            "REAL-money alert needs an explicit \"confirm\": true",
        )

    if action == "open":
        if enforce_market_hours and not within_regular_hours(now_utc):
            return RealModeDecision(
                False, "MARKET_CLOSED",
                "outside US regular trading hours (09:30-16:00 ET, Mon-Fri)",
            )
        if max_notional > 0 and price * quantity > max_notional:
            return RealModeDecision(
                False, "NOTIONAL_EXCEEDED",
                f"order notional {price * quantity:.2f} exceeds MAX_NOTIONAL {max_notional:.2f}",
            )
        if max_daily_loss > 0 and realized_pnl_today <= -max_daily_loss:
            return RealModeDecision(
                False, "KILL_SWITCH",
                f"daily realized loss {realized_pnl_today:.2f} tripped MAX_DAILY_LOSS {max_daily_loss:.2f}",
            )

    return _OK
