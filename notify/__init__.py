"""Outbound notification channels (best-effort; never block or break trading)."""
from notify.telegram import TelegramNotifier

__all__ = ["TelegramNotifier"]
