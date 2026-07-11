"""Executor — turns a Signal into broker actions. This is the "Trade" button.

- BUY  -> open a long position (market entry) with attached TP/SL.
- SELL -> close an existing open long for that symbol (if any).
- HOLD -> do nothing.

It is broker-agnostic: give it a MockBroker or a MoomooBroker.
"""
from __future__ import annotations

from typing import Any, Dict

from models import Action, BracketOrder, Signal
from broker.base import Broker


class Executor:
    def __init__(self, broker: Broker, quantity: int = 1) -> None:
        self.broker = broker
        self.quantity = quantity

    def execute(self, signal: Signal) -> Dict[str, Any]:
        if signal.action is Action.BUY:
            # Tell the broker the current price so a market order can fill and the
            # soft stop-loss / take-profit watch has a reference point.
            self.broker.update_price(signal.symbol, signal.price)
            order = BracketOrder(
                symbol=signal.symbol,
                side=Action.BUY,
                quantity=self.quantity,
                take_profit=signal.take_profit,
                stop_loss=signal.stop_loss,
            )
            pos = self.broker.place_bracket(order)
            status = "OPENED" if pos.status in {"OPEN", "OPEN_UNPROTECTED"} else pos.status
            return {
                "status": status,
                "message": (
                    f"Opened {self.quantity} {signal.symbol} @ {pos.avg_price}"
                    if status == "OPENED"
                    else f"Entry submitted for {signal.symbol}"
                ),
                "position": pos,
            }

        if signal.action is Action.SELL:
            open_for_symbol = [
                p for p in self.broker.open_positions() if p.symbol == signal.symbol
            ]
            if not open_for_symbol:
                return {
                    "status": "NOOP",
                    "message": f"No open {signal.symbol} position to close",
                    "position": None,
                }
            pos = self.broker.close(signal.symbol, signal.price, reason="SIGNAL_EXIT")
            status = "CLOSED" if pos.status == "CLOSED" else pos.status
            return {
                "status": status,
                "message": (
                    f"Closed {signal.symbol} @ {pos.close_price}"
                    if status == "CLOSED"
                    else f"Exit submitted for {signal.symbol}"
                ),
                "position": pos,
            }

        return {"status": "NOOP", "message": "HOLD — no action", "position": None}
