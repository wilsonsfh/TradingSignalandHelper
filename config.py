"""Configuration loaded from environment variables (.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

try:  # optional: load a local .env if python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is optional
    pass


def _split_csv(value: str) -> List[str]:
    return [item.strip().upper() for item in value.split(",") if item.strip()]


def _split_plain(value: str) -> List[str]:
    """Split a CSV without upper-casing (for IPs, which must not be mangled)."""
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Config:
    broker: str = field(default_factory=lambda: os.getenv("BROKER", "mock").lower())
    trd_env: str = field(default_factory=lambda: os.getenv("TRD_ENV", "SIMULATE").upper())
    data_source: str = field(default_factory=lambda: os.getenv("DATA_SOURCE", "demo").lower())
    watchlist: List[str] = field(
        default_factory=lambda: _split_csv(os.getenv("WATCHLIST", "AAPL,MSFT,NVDA,SPY"))
    )
    ema_fast: int = field(default_factory=lambda: int(os.getenv("EMA_FAST", "9")))
    ema_slow: int = field(default_factory=lambda: int(os.getenv("EMA_SLOW", "21")))
    candle_period: str = field(default_factory=lambda: os.getenv("CANDLE_PERIOD", "6mo"))
    candle_interval: str = field(default_factory=lambda: os.getenv("CANDLE_INTERVAL", "1d"))
    quantity: int = field(default_factory=lambda: int(os.getenv("QUANTITY", "1")))
    take_profit_pct: float = field(default_factory=lambda: float(os.getenv("TAKE_PROFIT_PCT", "3.0")))
    stop_loss_pct: float = field(default_factory=lambda: float(os.getenv("STOP_LOSS_PCT", "2.0")))
    state_db_path: str = field(default_factory=lambda: os.getenv("STATE_DB_PATH", "state/trading.sqlite"))
    soft_stop_poll_seconds: float = field(
        default_factory=lambda: float(os.getenv("SOFT_STOP_POLL_SECONDS", "4.0"))
    )
    opend_host: str = field(default_factory=lambda: os.getenv("OPEND_HOST", "127.0.0.1"))
    opend_port: int = field(default_factory=lambda: int(os.getenv("OPEND_PORT", "11111")))
    # moomoo brokerage entity — MUST match your account or OpenD returns no accounts.
    # FUTUSECURITIES=FUTU HK, FUTUINC=moomoo US, FUTUSG=moomoo SG, FUTUAU/CA/JP/MY.
    moomoo_security_firm: str = field(
        default_factory=lambda: os.getenv("MOOMOO_SECURITY_FIRM", "FUTUSECURITIES").upper()
    )
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "change-me"))
    webhook_enabled: bool = field(default_factory=lambda: _env_bool("WEBHOOK_ENABLED"))
    webhook_max_age_seconds: int = field(
        default_factory=lambda: int(os.getenv("WEBHOOK_MAX_AGE_SECONDS", "300"))
    )
    max_alert_quantity: int = field(
        default_factory=lambda: int(os.getenv("MAX_ALERT_QUANTITY", "100"))
    )
    use_broker_stop_order: bool = field(
        default_factory=lambda: _env_bool("USE_BROKER_STOP_ORDER", False)
    )
    webhook_signature_required: bool = field(
        default_factory=lambda: _env_bool("WEBHOOK_SIGNATURE_REQUIRED", False)
    )
    # Empty by default: enforce only when explicitly configured. In production put
    # TradingView's published webhook IPs here (and/or allow-list them at the edge,
    # e.g. Cloudflare WAF): 52.89.214.238,34.212.75.30,54.218.53.128,52.32.178.7
    webhook_ip_allowlist: List[str] = field(
        default_factory=lambda: _split_plain(os.getenv("WEBHOOK_IP_ALLOWLIST", ""))
    )
    webhook_rate_per_min: int = field(
        default_factory=lambda: int(os.getenv("WEBHOOK_RATE_PER_MIN", "5"))
    )
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    # --- REAL-money webhook enablement (all default OFF; see docs/HANDOVER) ---
    # Second half of the double opt-in: even in REAL mode the webhook stays
    # hard-blocked unless this is explicitly set true on the host.
    allow_real_webhook: bool = field(
        default_factory=lambda: _env_bool("ALLOW_REAL_WEBHOOK", False)
    )
    # Circuit breakers. 0 disables the individual breaker.
    max_notional: float = field(default_factory=lambda: float(os.getenv("MAX_NOTIONAL", "0")))
    max_daily_loss: float = field(default_factory=lambda: float(os.getenv("MAX_DAILY_LOSS", "0")))
    # Coarse RTH fence for REAL `open` orders (holidays not modelled).
    enforce_market_hours: bool = field(
        default_factory=lambda: _env_bool("ENFORCE_MARKET_HOURS", True)
    )
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "127.0.0.1"))
    web_port: int = field(default_factory=lambda: int(os.getenv("WEB_PORT", "5000")))

    @property
    def is_real_money(self) -> bool:
        """True only when configured to place LIVE orders with real money."""
        return self.broker == "moomoo" and self.trd_env == "REAL"

    @property
    def mode_label(self) -> str:
        """Human-readable mode shown in the UI, e.g. 'MOCK / SIMULATE'."""
        return f"{self.broker.upper()} / {self.trd_env}"

    def validate(self) -> None:
        if self.broker not in {"mock", "moomoo"}:
            raise ValueError("BROKER must be 'mock' or 'moomoo'")
        if self.trd_env not in {"SIMULATE", "REAL"}:
            raise ValueError("TRD_ENV must be 'SIMULATE' or 'REAL'")
        if self.data_source not in {"demo", "yfinance"}:
            raise ValueError("DATA_SOURCE must be 'demo' or 'yfinance'")
        if self.broker == "moomoo" and self.data_source != "yfinance":
            raise ValueError("BROKER=moomoo requires DATA_SOURCE=yfinance")
        known_firms = {"FUTUSECURITIES", "FUTUINC", "FUTUSG", "FUTUAU", "FUTUCA", "FUTUJP", "FUTUMY"}
        if self.moomoo_security_firm not in known_firms:
            raise ValueError(f"MOOMOO_SECURITY_FIRM must be one of {sorted(known_firms)}")
        if self.quantity <= 0 or self.soft_stop_poll_seconds <= 0:
            raise ValueError("QUANTITY and SOFT_STOP_POLL_SECONDS must be positive")
        if self.max_alert_quantity <= 0:
            raise ValueError("MAX_ALERT_QUANTITY must be positive")
        if self.webhook_rate_per_min <= 0:
            raise ValueError("WEBHOOK_RATE_PER_MIN must be positive")
        if self.max_notional < 0:
            raise ValueError("MAX_NOTIONAL must be zero (disabled) or positive")
        if self.max_daily_loss < 0:
            raise ValueError("MAX_DAILY_LOSS must be zero (disabled) or positive")


def load_config() -> Config:
    return Config()
