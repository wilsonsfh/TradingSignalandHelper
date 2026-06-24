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


@dataclass
class Config:
    broker: str = field(default_factory=lambda: os.getenv("BROKER", "mock").lower())
    trd_env: str = field(default_factory=lambda: os.getenv("TRD_ENV", "SIMULATE").upper())
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
    opend_host: str = field(default_factory=lambda: os.getenv("OPEND_HOST", "127.0.0.1"))
    opend_port: int = field(default_factory=lambda: int(os.getenv("OPEND_PORT", "11111")))
    webhook_secret: str = field(default_factory=lambda: os.getenv("WEBHOOK_SECRET", "change-me"))
    web_host: str = field(default_factory=lambda: os.getenv("WEB_HOST", "127.0.0.1"))
    web_port: int = field(default_factory=lambda: int(os.getenv("WEB_PORT", "5000")))

    @property
    def is_real_money(self) -> bool:
        """True only when configured to place LIVE orders with real money."""
        return self.broker == "moomoo" and self.trd_env == "REAL"


def load_config() -> Config:
    return Config()
