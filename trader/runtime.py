"""Application runtime: durable execution and browser-independent risk checks."""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional
from uuid import uuid4

from broker.base import Broker, BrokerOrderRejected
from data.price_feed import PriceFeed
from models import Action, Position, Signal
from state.store import StateStore
from trader.executor import Executor


class TradingRuntime:
    def __init__(
        self,
        broker: Broker,
        feed: PriceFeed,
        executor: Executor,
        store: StateStore,
        poll_seconds: float = 4.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.broker = broker
        self.feed = feed
        self.executor = executor
        self.store = store
        self.poll_seconds = poll_seconds
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._disconnected = False
        try:
            active_positions = self.broker.open_positions()
        except Exception as exc:
            self._safe_activity("error", "SYSTEM", str(exc))
            active_positions = []
        for position in active_positions:
            self.store.claim_symbol(position.symbol, f"restore:{position.position_id}")

    def _safe_activity(self, kind: str, symbol: str, message: str) -> None:
        try:
            self.store.add_activity(kind, symbol, message)
        except Exception:
            pass

    def _position_by_id(self, position_id: Optional[str]) -> Optional[Position]:
        if position_id is None:
            return None
        return next(
            (position for position in self.broker.positions() if position.position_id == position_id),
            None,
        )

    def _replay(self, request_id: str) -> Dict[str, Any]:
        order = self.store.get_order(request_id)
        if order is None:
            raise RuntimeError(f"order {request_id!r} disappeared during replay")
        return {
            "status": order["status"],
            "message": order["message"],
            "position": self._position_by_id(order.get("position_id")),
        }

    def execute(
        self,
        signal: Signal,
        source: str = "dashboard",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            request_id = request_id or uuid4().hex
            self.store.save_signal(signal)
            if not self.store.begin_order(
                request_id,
                signal,
                self.executor.quantity,
                source,
            ):
                return self._replay(request_id)

            claimed_symbol = False
            if signal.action is Action.BUY:
                if any(
                    position.symbol == signal.symbol
                    for position in self.broker.open_positions()
                ):
                    result = {
                        "status": "NOOP",
                        "message": f"An open {signal.symbol} position already exists",
                        "position": None,
                    }
                elif not self.store.claim_symbol(signal.symbol, request_id):
                    result = {
                        "status": "NOOP",
                        "message": f"An active {signal.symbol} order or position already exists",
                        "position": None,
                    }
                else:
                    claimed_symbol = True
                    result = self._execute_broker(signal, request_id)
            else:
                result = self._execute_broker(signal, request_id)

            position = result.get("position")
            if position is not None:
                self.store.save_position(position)
            self.store.finish_order(
                request_id,
                result["status"],
                result["message"],
                position,
            )
            kind = "hook" if source == "webhook" else "trade"
            self.store.add_activity(kind, signal.symbol, result["message"])
            if claimed_symbol and result["status"] != "OPENED" and position is None:
                self.store.release_symbol(signal.symbol)
            return result

    def _execute_broker(self, signal: Signal, request_id: str) -> Dict[str, Any]:
        try:
            return self.executor.execute(signal)
        except BrokerOrderRejected as exc:
            self.store.finish_order(request_id, "REJECTED", str(exc))
            self._safe_activity("error", signal.symbol, str(exc))
            if signal.action is Action.BUY:
                self.store.release_symbol(signal.symbol)
            raise
        except Exception as exc:
            for current in self.broker.positions():
                if current.symbol == signal.symbol:
                    self.store.save_position(current)
            self.store.finish_order(request_id, "ERROR", str(exc))
            self._safe_activity("error", signal.symbol, str(exc))
            raise

    def close(
        self,
        symbol: str,
        price: float,
        source: str = "dashboard",
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        signal = Signal(symbol, Action.SELL, price, reason="manual close")
        with self._lock:
            request_id = request_id or uuid4().hex
            self.store.save_signal(signal)
            if not self.store.begin_order(
                request_id,
                signal,
                self.executor.quantity,
                source,
            ):
                return self._replay(request_id)
            try:
                position = self.broker.close(symbol, price, reason="MANUAL")
            except ValueError as exc:
                result = {"status": "NOOP", "message": str(exc), "position": None}
                self.store.release_symbol(symbol)
            except Exception as exc:
                for current in self.broker.positions():
                    if current.symbol == symbol:
                        self.store.save_position(current)
                self.store.finish_order(request_id, "ERROR", str(exc))
                self._safe_activity("error", symbol, str(exc))
                raise
            else:
                self.store.save_position(position)
                result_status = "CLOSED" if position.status == "CLOSED" else position.status
                result = {
                    "status": result_status,
                    "message": (
                        f"Closed {symbol} @ {position.close_price}"
                        if result_status == "CLOSED"
                        else f"Exit submitted for {symbol}"
                    ),
                    "position": position,
                }
                if result_status == "CLOSED":
                    self.store.release_symbol(symbol)
            self.store.finish_order(
                request_id,
                result["status"],
                result["message"],
                result.get("position"),
            )
            self.store.add_activity("close", symbol, result["message"])
            return result

    def poll_once(self) -> List[Position]:
        closed: List[Position] = []
        with self._lock:
            try:
                positions = list(self.broker.open_positions())
            except Exception as exc:
                self._safe_activity("error", "SYSTEM", str(exc))
                return closed
            for position in positions:
                try:
                    price = float(self.feed.last_price(position.symbol))
                    triggered = self.broker.update_price(position.symbol, price)
                    self.store.save_position(position)
                    for item in triggered:
                        self.store.release_symbol(item.symbol)
                        self._safe_activity(
                            "auto",
                            item.symbol,
                            f"{item.close_reason} @ {item.close_price}",
                        )
                    closed.extend(triggered)
                except Exception as exc:
                    try:
                        self.store.save_position(position)
                    except Exception:
                        pass
                    self._safe_activity("error", position.symbol, str(exc))
        return closed

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._monitor,
            name="soft-stop-monitor",
            daemon=True,
        )
        self._thread.start()

    def _monitor(self) -> None:
        while not self._stop_event.wait(self.poll_seconds):
            try:
                self.poll_once()
            except Exception as exc:
                self._safe_activity("error", "SYSTEM", str(exc))

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=max(1.0, self.poll_seconds + 1.0))
            if self._thread.is_alive():
                raise RuntimeError("soft-stop monitor did not stop; broker left connected")
        if not self._disconnected:
            disconnect = getattr(self.broker, "disconnect", None)
            if callable(disconnect):
                disconnect()
            self._disconnected = True
