"""Real moomoo trading via OpenD — paper (SIMULATE) first.  [Phase 5 scaffold]

IMPORTANT
- No credentials are stored here. OpenD performs the moomoo login; this class only
  needs the local OpenD host/port (placeholders in .env).
- Live order placement requires the `moomoo-api` SDK AND a running OpenD. Until
  ``connect()`` succeeds, the trading methods raise a clear, actionable error.
- This is a structural scaffold. The SDK calls follow moomoo's documented API but
  MUST be verified against your account once OpenD is connected (see README →
  "Connect moomoo"). Paper mode supports only MARKET + LIMIT orders, so the
  stop-loss is a *soft* watch (same approach as MockBroker).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from models import Action, BracketOrder, Position
from broker.base import Broker

_NOT_CONNECTED = (
    "MoomooBroker is not connected.\n"
    "  1) pip install moomoo-api\n"
    "  2) download & run OpenD, then log in with your moomoo account\n"
    "  3) call broker.connect()\n"
    "See README → 'Connect moomoo (Phase 5)'."
)


class MoomooBroker(Broker):
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 11111,
        trd_env: str = "SIMULATE",
        market: str = "US",
        trade_password: Optional[str] = None,  # placeholder; only needed for REAL orders
    ) -> None:
        self.host = host
        self.port = port
        self.trd_env = trd_env.upper()
        self.market = market.upper()
        self._trade_password = trade_password
        self._ctx = None       # moomoo OpenSecTradeContext (set in connect())
        self._quote = None      # moomoo OpenQuoteContext
        self._positions: List[Position] = []
        self._tp_orders: Dict[str, object] = {}  # symbol -> take-profit order id

    # ── connection ───────────────────────────────────────────────
    def connect(self) -> "MoomooBroker":
        try:
            import moomoo as mm  # noqa: F401
        except Exception as exc:  # SDK not installed
            raise RuntimeError(f"{_NOT_CONNECTED}\n(import error: {exc})")
        market = getattr(mm.TrdMarket, self.market, mm.TrdMarket.US)
        self._ctx = mm.OpenSecTradeContext(filter_trdmarket=market, host=self.host, port=self.port)
        self._quote = mm.OpenQuoteContext(host=self.host, port=self.port)
        return self

    def _require(self) -> None:
        if self._ctx is None:
            raise RuntimeError(_NOT_CONNECTED)

    def _env(self):
        import moomoo as mm
        return mm.TrdEnv.SIMULATE if self.trd_env == "SIMULATE" else mm.TrdEnv.REAL

    def _code(self, symbol: str) -> str:
        return f"{self.market}.{symbol}"  # moomoo format, e.g. "US.AAPL"

    # ── Broker API ────────────────────────────────────────────────
    def positions(self) -> List[Position]:
        return list(self._positions)

    def open_positions(self) -> List[Position]:
        return [p for p in self._positions if p.status == "OPEN"]

    def place_bracket(self, order: BracketOrder) -> Position:
        self._require()
        import moomoo as mm

        if order.side is not Action.BUY:
            raise ValueError("place_bracket only opens long positions (BUY)")
        env, code = self._env(), self._code(order.symbol)

        # 1) Market entry (paper supports MARKET).
        ret, data = self._ctx.place_order(
            price=0, qty=order.quantity, code=code,
            trd_side=mm.TrdSide.BUY, order_type=mm.OrderType.MARKET, trd_env=env,
        )
        if ret != mm.RET_OK:
            raise RuntimeError(f"moomoo entry order failed: {data}")

        avg = self._lookup_fill_price(code, env)
        pos = Position(order.symbol, order.quantity, avg,
                       order.take_profit, order.stop_loss, status="OPEN")
        self._positions.append(pos)

        # 2) Limit take-profit (paper supports NORMAL limit). Stop-loss is soft (below).
        if order.take_profit:
            tret, tdata = self._ctx.place_order(
                price=order.take_profit, qty=order.quantity, code=code,
                trd_side=mm.TrdSide.SELL, order_type=mm.OrderType.NORMAL, trd_env=env,
            )
            if tret == mm.RET_OK:
                self._tp_orders[order.symbol] = tdata
        return pos

    def update_price(self, symbol: str, price: float) -> List[Position]:
        """Soft TP/SL watch. Call this on a timer with the latest quote."""
        self._require()
        closed: List[Position] = []
        for p in self._positions:
            if p.status != "OPEN" or p.symbol != symbol:
                continue
            if p.take_profit is not None and price >= p.take_profit:
                # TP limit order should fill on the exchange; reconcile bookkeeping.
                self._mark_closed(p, price, "TAKE_PROFIT")
                closed.append(p)
            elif p.stop_loss is not None and price <= p.stop_loss:
                self._market_sell(symbol, p.quantity)
                self._cancel_tp(symbol)
                self._mark_closed(p, price, "STOP_LOSS")
                closed.append(p)
        return closed

    def close(self, symbol: str, price: float, reason: str = "MANUAL") -> Position:
        self._require()
        for p in self._positions:
            if p.status == "OPEN" and p.symbol == symbol:
                self._market_sell(symbol, p.quantity)
                self._cancel_tp(symbol)
                self._mark_closed(p, price, reason)
                return p
        raise ValueError(f"no open position for {symbol!r}")

    # ── helpers (verify against your account once connected) ──────
    def _lookup_fill_price(self, code: str, env) -> float:
        import moomoo as mm
        ret, data = self._ctx.position_list_query(code=code, trd_env=env)
        if ret == mm.RET_OK and len(data) > 0:
            return float(data.iloc[0]["cost_price"])
        return 0.0

    def _market_sell(self, symbol: str, qty: int) -> None:
        import moomoo as mm
        self._ctx.place_order(price=0, qty=qty, code=self._code(symbol),
                              trd_side=mm.TrdSide.SELL, order_type=mm.OrderType.MARKET,
                              trd_env=self._env())

    def _cancel_tp(self, symbol: str) -> None:
        # Cancel the resting take-profit order so it can't fill after we've exited.
        self._tp_orders.pop(symbol, None)
        # TODO(verify): call self._ctx.modify_order(ModifyOrderOp.CANCEL, ...) with the id.

    @staticmethod
    def _mark_closed(p: Position, price: float, reason: str) -> None:
        p.status = "CLOSED"
        p.close_price = price
        p.close_reason = reason
        p.closed_at = datetime.now(timezone.utc)
