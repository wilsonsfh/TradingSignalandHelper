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
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "change-me"))
    webhook_enabled: bool = field(default_factory=lambda: _env_bool("WEBHOOK_ENABLED"))
    webhook_max_age_seconds: int = field(
        default_factory=lambda: int(os.getenv("WEBHOOK_MAX_AGE_SECONDS", "300"))
    )
    max_alert_quantity: int = field(
        default_factory=lambda: int(os.getenv("MAX_ALERT_QUANTITY", "100"))
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
        if self.quantity <= 0 or self.soft_stop_poll_seconds <= 0:
            raise ValueError("QUANTITY and SOFT_STOP_POLL_SECONDS must be positive")
        if self.max_alert_quantity <= 0:
            raise ValueError("MAX_ALERT_QUANTITY must be positive")


def load_config() -> Config:
    return Config()
