"""Moomoo trading through OpenD, with an offline-testable SDK boundary."""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable, List, Optional, Tuple

from broker.base import Broker, BrokerOrderRejected
from models import Action, BracketOrder, Position


_NOT_CONNECTED = (
    "MoomooBroker is not connected.\n"
    "  1) pip install -r requirements-moomoo.txt\n"
    "  2) download and run OpenD, then log in with your moomoo account\n"
    "  3) call broker.connect()\n"
    "See README: 'Connect moomoo'."
)


def _first(data: Any, key: str, default: Any = None) -> Any:
    """Read the first value from a DataFrame-like or dict-like SDK response."""
    if data is None:
        return default
    if hasattr(data, "empty") and data.empty:
        return default
    if hasattr(data, "columns"):
        if key not in data.columns:
            return default
        return data.iloc[0][key]
    if isinstance(data, dict):
        value = data.get(key, default)
        if isinstance(value, (list, tuple)):
            return value[0] if value else default
        return value
    return default


def _status_name(value: Any) -> str:
    return str(getattr(value, "name", value)).upper().split(".")[-1]


class MoomooBroker(Broker):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        trd_env: str = "SIMULATE",
        market: str = "US",
        trade_password: Optional[str] = None,
        sdk: Any = None,
        initial_positions: Optional[Iterable[Position]] = None,
    ) -> None:
        environment = trd_env.upper()
        if environment not in {"SIMULATE", "REAL"}:
            raise ValueError("TRD_ENV must be 'SIMULATE' or 'REAL'")
        if market.upper() != "US":
            raise ValueError("market must be 'US'")
        self.host = host
        self.port = port
        self.trd_env = environment
        self.market = market.upper()
        self._trade_password = trade_password
        self._sdk = sdk
        self._ctx = None
        self._quote = None
        self._positions: List[Position] = list(initial_positions or [])

    def connect(self) -> "MoomooBroker":
        if self._sdk is None:
            try:
                import moomoo as sdk
            except Exception as exc:
                raise RuntimeError(f"{_NOT_CONNECTED}\n(import error: {exc})") from exc
            self._sdk = sdk
        market = self._sdk.TrdMarket.US
        self._ctx = self._sdk.OpenSecTradeContext(
            filter_trdmarket=market,
            host=self.host,
            port=self.port,
        )
        try:
            self._quote = self._sdk.OpenQuoteContext(host=self.host, port=self.port)
        except Exception:
            self._ctx.close()
            self._ctx = None
            raise
        return self

    def disconnect(self) -> None:
        first_error = None
        for context in (self._ctx, self._quote):
            if context is not None:
                try:
                    context.close()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        self._ctx = None
        self._quote = None
        if first_error is not None:
            raise first_error

    def _require(self) -> None:
        if self._ctx is None or self._sdk is None:
            raise RuntimeError(_NOT_CONNECTED)

    def _env(self):
        self._require()
        return (
            self._sdk.TrdEnv.SIMULATE
            if self.trd_env == "SIMULATE"
            else self._sdk.TrdEnv.REAL
        )

    def _code(self, symbol: str) -> str:
        return f"{self.market}.{symbol}"

    def last_price(self, symbol: str) -> float:
        self._require()
        if self._quote is None:
            raise RuntimeError(_NOT_CONNECTED)
        ret, data = self._quote.get_market_snapshot([self._code(symbol)])
        if ret != self._sdk.RET_OK:
            raise RuntimeError(f"moomoo quote failed: {data}")
        value = _first(data, "last_price", None)
        try:
            price = float(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"moomoo quote returned no price for {symbol}") from exc
        if not math.isfinite(price) or price <= 0:
            raise RuntimeError(f"moomoo quote returned an invalid price for {symbol}")
        return price

    def positions(self) -> List[Position]:
        return list(self._positions)

    def open_positions(self) -> List[Position]:
        return [position for position in self._positions if position.status != "CLOSED"]

    def place_bracket(self, order: BracketOrder) -> Position:
        self._require()
        if order.side is not Action.BUY:
            raise ValueError("place_bracket only opens long positions (BUY)")
        if any(position.symbol == order.symbol for position in self.open_positions()):
            raise ValueError(f"an open position already exists for {order.symbol!r}")

        ret, data = self._ctx.place_order(
            price=0,
            qty=order.quantity,
            code=self._code(order.symbol),
            trd_side=self._sdk.TrdSide.BUY,
            order_type=self._sdk.OrderType.MARKET,
            trd_env=self._env(),
        )
        if ret != self._sdk.RET_OK:
            raise BrokerOrderRejected(f"moomoo entry order failed: {data}")
        status, average, dealt_quantity = self._snapshot(data)
        try:
            entry_id = self._order_id(data, "entry")
        except RuntimeError as exc:
            self._positions.append(
                Position(
                    symbol=order.symbol,
                    quantity=dealt_quantity or order.quantity,
                    avg_price=average,
                    take_profit=order.take_profit,
                    stop_loss=order.stop_loss,
                    status="ENTRY_UNKNOWN",
                )
            )
            raise RuntimeError(
                "moomoo accepted an entry without an order ID; manual reconciliation required"
            ) from exc

        position = Position(
            symbol=order.symbol,
            quantity=order.quantity,
            avg_price=average if self._is_filled(status) and average > 0 else 0.0,
            take_profit=order.take_profit,
            stop_loss=order.stop_loss,
            status="OPEN" if self._is_filled(status) and average > 0 else "ENTRY_PENDING",
            entry_order_id=entry_id,
        )
        self._positions.append(position)
        if position.status == "OPEN":
            self._place_take_profit(position)
        return position

    def update_price(self, symbol: str, price: float) -> List[Position]:
        self._require()
        closed: List[Position] = []
        for position in self._positions:
            if position.status == "CLOSED" or position.symbol != symbol:
                continue
            if position.status in {
                "ENTRY_UNKNOWN",
                "OPEN_PROTECTION_UNKNOWN",
                "EXIT_UNKNOWN",
            }:
                raise RuntimeError(
                    f"{position.symbol} has unknown broker orders; manual reconciliation required"
                )
            if position.status == "EXIT_PENDING":
                if self._reconcile_exit(position):
                    closed.append(position)
                continue
            if position.status in {"ENTRY_PENDING", "ENTRY_CANCEL_PENDING"}:
                self._reconcile_entry(position)
                continue
            if position.status == "TP_CANCEL_PENDING":
                self._exit_position(
                    position,
                    position.close_price or price,
                    position.close_reason or "EXIT",
                )
                if position.status == "CLOSED":
                    closed.append(position)
                continue
            if position.take_profit_order_id:
                status, fill_price, dealt_quantity = self._query_order(
                    position.take_profit_order_id
                )
                original_quantity = float(
                    position.take_profit_order_quantity or position.quantity
                )
                position.take_profit_order_quantity = original_quantity
                if self._is_filled(status) or dealt_quantity >= original_quantity:
                    self._mark_closed(
                        position,
                        fill_price or position.take_profit or price,
                        "TAKE_PROFIT",
                    )
                    closed.append(position)
                    continue
                if dealt_quantity > 0:
                    position.quantity = max(0.0, original_quantity - dealt_quantity)
                if self._is_terminal(status):
                    position.take_profit_order_id = None
                    position.take_profit_order_quantity = None
                    position.status = "OPEN_UNPROTECTED"
            if position.take_profit is not None and price >= position.take_profit:
                if not position.take_profit_order_id:
                    self._exit_position(position, price, "TAKE_PROFIT")
                    if position.status == "CLOSED":
                        closed.append(position)
            elif position.stop_loss is not None and price <= position.stop_loss:
                self._exit_position(position, price, "STOP_LOSS")
                if position.status == "CLOSED":
                    closed.append(position)
        return closed

    def close(self, symbol: str, price: float, reason: str = "MANUAL") -> Position:
        self._require()
        for position in self.open_positions():
            if position.symbol == symbol:
                self._exit_position(position, price, reason)
                return position
        raise ValueError(f"no open position for {symbol!r}")

    @staticmethod
    def _is_filled(status: str) -> bool:
        return status == "FILLED_ALL"

    @staticmethod
    def _is_terminal(status: str) -> bool:
        return status in {
            "CANCELLED_ALL",
            "CANCELLED_PART",
            "SUBMIT_FAILED",
            "FAILED",
            "DISABLED",
            "DELETED",
            "FILL_CANCELLED",
        }

    @staticmethod
    def _snapshot(data: Any) -> Tuple[str, float, float]:
        status = _status_name(_first(data, "order_status", ""))
        average = _first(data, "dealt_avg_price", None)
        if average is None:
            average = _first(data, "cost_price", 0.0)
        try:
            dealt_quantity = float(_first(data, "dealt_qty", 0.0) or 0.0)
            return status, float(average or 0.0), dealt_quantity
        except (TypeError, ValueError):
            return status, 0.0, 0.0

    @staticmethod
    def _order_id(data: Any, role: str) -> str:
        order_id = _first(data, "order_id", None)
        if order_id is None or not str(order_id).strip():
            raise RuntimeError(f"moomoo {role} response has no order_id")
        return str(order_id)

    def _place_take_profit(self, position: Position) -> None:
        if position.take_profit is None:
            return
        ret, data = self._ctx.place_order(
            price=position.take_profit,
            qty=position.quantity,
            code=self._code(position.symbol),
            trd_side=self._sdk.TrdSide.SELL,
            order_type=self._sdk.OrderType.NORMAL,
            trd_env=self._env(),
        )
        if ret != self._sdk.RET_OK:
            position.status = "OPEN_UNPROTECTED"
            return
        position.take_profit_order_quantity = float(position.quantity)
        try:
            position.take_profit_order_id = self._order_id(data, "take-profit")
        except RuntimeError as exc:
            position.status = "OPEN_PROTECTION_UNKNOWN"
            raise RuntimeError(
                "moomoo accepted take-profit protection without an order ID; "
                "manual reconciliation required"
            ) from exc

    def _query_order(self, order_id: str) -> Tuple[str, float, float]:
        ret, data = self._ctx.order_list_query(
            order_id=order_id,
            trd_env=self._env(),
            refresh_cache=True,
        )
        if ret != self._sdk.RET_OK:
            raise RuntimeError(f"moomoo order query failed for {order_id}: {data}")
        status, average, dealt_quantity = self._snapshot(data)
        if not status:
            raise RuntimeError(f"moomoo order query returned no status for {order_id}")
        return status, average, dealt_quantity

    def _reconcile_entry(self, position: Position) -> None:
        if not position.entry_order_id:
            raise RuntimeError(f"pending {position.symbol} entry has no order ID")
        status, average, dealt_quantity = self._query_order(position.entry_order_id)
        if self._is_filled(status) and average > 0:
            if dealt_quantity > 0:
                position.quantity = dealt_quantity
            position.avg_price = average
            position.status = "OPEN"
            self._place_take_profit(position)
        elif dealt_quantity > 0 and average > 0:
            if not self._is_terminal(status):
                if position.status != "ENTRY_CANCEL_PENDING":
                    self._cancel_order(position.entry_order_id, "entry")
                status, average, dealt_quantity = self._query_order(
                    position.entry_order_id
                )
                if self._is_filled(status) and average > 0:
                    position.quantity = dealt_quantity or position.quantity
                    position.avg_price = average
                    position.status = "OPEN"
                    self._place_take_profit(position)
                    return
                if not self._is_terminal(status):
                    position.status = "ENTRY_CANCEL_PENDING"
                    return
            position.quantity = dealt_quantity
            position.avg_price = average
            position.status = "OPEN"
            self._place_take_profit(position)
        elif self._is_terminal(status):
            self._mark_closed(position, 0.0, "ENTRY_CANCELLED")

    def _tp_fill(self, position: Position) -> Tuple[bool, float, float]:
        if not position.take_profit_order_id:
            return False, 0.0, 0.0
        status, average, dealt_quantity = self._query_order(position.take_profit_order_id)
        return self._is_filled(status), average, dealt_quantity

    def _cancel_order(self, order_id: str, role: str) -> None:
        ret, data = self._ctx.modify_order(
            self._sdk.ModifyOrderOp.CANCEL,
            order_id,
            0,
            0,
            trd_env=self._env(),
        )
        if ret != self._sdk.RET_OK:
            raise RuntimeError(f"moomoo {role} cancel failed: {data}")

    def _market_sell(
        self,
        position: Position,
        quantity: float,
    ) -> Tuple[str, str, float, float]:
        ret, data = self._ctx.place_order(
            price=0,
            qty=quantity,
            code=self._code(position.symbol),
            trd_side=self._sdk.TrdSide.SELL,
            order_type=self._sdk.OrderType.MARKET,
            trd_env=self._env(),
        )
        if ret != self._sdk.RET_OK:
            raise RuntimeError(f"moomoo exit order failed: {data}")
        status, average, dealt_quantity = self._snapshot(data)
        try:
            order_id = self._order_id(data, "exit")
        except RuntimeError as exc:
            position.status = "EXIT_UNKNOWN"
            position.exit_order_quantity = quantity
            raise RuntimeError(
                "moomoo accepted an exit without an order ID; manual reconciliation required"
            ) from exc
        return order_id, status, average, dealt_quantity

    def _reconcile_exit(self, position: Position) -> bool:
        if not position.exit_order_id:
            raise RuntimeError(f"pending {position.symbol} exit has no order ID")
        status, average, dealt_quantity = self._query_order(position.exit_order_id)
        requested_quantity = float(position.exit_order_quantity or position.quantity)
        position.exit_order_quantity = requested_quantity
        if self._is_filled(status) or dealt_quantity >= requested_quantity:
            self._mark_closed(
                position,
                average or position.close_price or 0.0,
                position.close_reason or "EXIT",
            )
            return True
        position.quantity = max(0.0, requested_quantity - dealt_quantity)
        if self._is_terminal(status):
            if position.quantity == 0:
                self._mark_closed(
                    position,
                    average or position.close_price or 0.0,
                    position.close_reason or "EXIT",
                )
                return True
            position.exit_order_id = None
            position.exit_order_quantity = None
            position.status = "OPEN_UNPROTECTED"
        return False

    def _exit_position(self, position: Position, price: float, reason: str) -> None:
        if position.status in {
            "ENTRY_UNKNOWN",
            "OPEN_PROTECTION_UNKNOWN",
            "EXIT_UNKNOWN",
        }:
            raise RuntimeError(
                f"{position.symbol} has unknown broker orders; manual reconciliation required"
            )
        if position.status == "EXIT_PENDING":
            self._reconcile_exit(position)
            return
        if position.status in {"ENTRY_PENDING", "ENTRY_CANCEL_PENDING"}:
            self._reconcile_entry(position)
            if position.status == "CLOSED":
                return
            if position.status == "ENTRY_PENDING":
                self._cancel_order(position.entry_order_id or "", "entry")
                position.status = "ENTRY_CANCEL_PENDING"
                return
            if position.status == "ENTRY_CANCEL_PENDING":
                return

        remaining_quantity = float(position.quantity)
        if position.take_profit_order_id:
            status, fill_price, dealt_quantity = self._query_order(
                position.take_profit_order_id
            )
            take_profit_quantity = float(
                position.take_profit_order_quantity or position.quantity
            )
            position.take_profit_order_quantity = take_profit_quantity
            if self._is_filled(status) or dealt_quantity >= take_profit_quantity:
                self._mark_closed(
                    position,
                    fill_price or position.take_profit or price,
                    "TAKE_PROFIT",
                )
                return
            if not self._is_terminal(status):
                try:
                    if position.status != "TP_CANCEL_PENDING":
                        self._cancel_order(
                            position.take_profit_order_id,
                            "take-profit",
                        )
                except RuntimeError:
                    filled, fill_price, dealt_quantity = self._tp_fill(position)
                    if filled or dealt_quantity >= take_profit_quantity:
                        self._mark_closed(
                            position,
                            fill_price or position.take_profit or price,
                            "TAKE_PROFIT",
                        )
                        return
                    raise
                status, fill_price, dealt_quantity = self._query_order(
                    position.take_profit_order_id
                )
                if self._is_filled(status) or dealt_quantity >= take_profit_quantity:
                    self._mark_closed(
                        position,
                        fill_price or position.take_profit or price,
                        "TAKE_PROFIT",
                    )
                    return
                if not self._is_terminal(status):
                    position.status = "TP_CANCEL_PENDING"
                    position.close_price = price
                    position.close_reason = reason
                    return
            remaining_quantity = max(0.0, take_profit_quantity - dealt_quantity)
            position.quantity = remaining_quantity
            position.take_profit_order_id = None
            position.take_profit_order_quantity = None
            if remaining_quantity == 0:
                self._mark_closed(
                    position,
                    fill_price or position.take_profit or price,
                    "TAKE_PROFIT",
                )
                return

        try:
            exit_id, status, average, dealt_quantity = self._market_sell(
                position,
                remaining_quantity,
            )
        except RuntimeError:
            if position.status != "EXIT_UNKNOWN":
                position.status = "OPEN_UNPROTECTED"
            raise
        position.exit_order_id = exit_id
        position.exit_order_quantity = remaining_quantity
        position.close_price = price
        position.close_reason = reason
        if self._is_filled(status) or dealt_quantity >= remaining_quantity:
            self._mark_closed(position, average or price, reason)
        else:
            position.status = "EXIT_PENDING"

    @staticmethod
    def _mark_closed(position: Position, price: float, reason: str) -> None:
        position.status = "CLOSED"
        position.close_price = price
        position.close_reason = reason
        position.closed_at = datetime.now(timezone.utc)
