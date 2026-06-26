"""Flask app: the dashboard + the one-button trade API.

Endpoints
  GET  /              dashboard page
  GET  /api/signals   current signals for the watchlist (+ mode)
  GET  /api/state     open positions with live P&L + recent activity
  POST /api/trade     {symbol[, confirm]} -> execute the latest signal (the button)
  POST /api/close     {symbol[, confirm]} -> manually close an open position

Real-money mode (BROKER=moomoo + TRD_ENV=REAL) requires "confirm": true in the body.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template, request

from config import Config, load_config
from strategy.ema_crossover import EMACrossover
from signals.engine import SignalEngine
from broker.base import Broker
from broker.mock_broker import MockBroker
from trader.executor import Executor
from models import Signal, Position


def _build_feed(cfg: Config):
    if cfg.data_source == "yfinance":
        from data.price_feed import YFinanceFeed

        return YFinanceFeed()
    from data.synthetic_feed import SyntheticFeed

    return SyntheticFeed()


def _signal_dict(s: Signal) -> Dict[str, Any]:
    return {
        "symbol": s.symbol,
        "action": s.action.value,
        "price": s.price,
        "take_profit": s.take_profit,
        "stop_loss": s.stop_loss,
        "reason": s.reason,
    }


def _position_dict(p: Position, current: Optional[float] = None) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "symbol": p.symbol,
        "quantity": p.quantity,
        "avg_price": p.avg_price,
        "take_profit": p.take_profit,
        "stop_loss": p.stop_loss,
        "status": p.status,
        "close_price": p.close_price,
        "close_reason": p.close_reason,
    }
    if current is not None:
        d["current_price"] = current
        d["pnl"] = round((current - p.avg_price) * p.quantity, 2)
        d["pnl_pct"] = round((current / p.avg_price - 1) * 100, 2) if p.avg_price else 0.0
    return d


def create_app(
    config: Optional[Config] = None,
    broker: Optional[Broker] = None,
    feed=None,
) -> Flask:
    cfg = config or load_config()
    feed = feed or _build_feed(cfg)
    broker = broker or MockBroker()
    strategy = EMACrossover(cfg.ema_fast, cfg.ema_slow, cfg.take_profit_pct, cfg.stop_loss_pct)
    engine = SignalEngine(strategy, feed, cfg.candle_period, cfg.candle_interval)
    executor = Executor(broker, cfg.quantity)
    activity: List[Dict[str, Any]] = []

    app = Flask(__name__)

    def log(kind: str, symbol: str, message: str) -> None:
        activity.insert(0, {
            "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "type": kind,
            "symbol": symbol,
            "message": message,
        })
        del activity[50:]

    def _confirm_required_response():
        if cfg.is_real_money and not (request.get_json(silent=True) or {}).get("confirm"):
            return jsonify({
                "status": "CONFIRM_REQUIRED",
                "message": "Real-money order needs explicit confirmation.",
            }), 412
        return None

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            mode=cfg.mode_label,
            real_money=cfg.is_real_money,
            watchlist=cfg.watchlist,
            quantity=cfg.quantity,
            ema_fast=cfg.ema_fast,
            ema_slow=cfg.ema_slow,
            tp_pct=cfg.take_profit_pct,
            sl_pct=cfg.stop_loss_pct,
        )

    @app.get("/api/signals")
    def api_signals():
        signals = [_signal_dict(s) for s in engine.run(cfg.watchlist)]
        return jsonify({
            "signals": signals,
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })

    @app.get("/api/state")
    def api_state():
        positions = []
        for p in broker.open_positions():
            try:
                current = float(feed.last_price(p.symbol))
            except Exception:
                current = None
            if current is not None:
                closed = broker.update_price(p.symbol, current)
                for c in closed:
                    log("auto", c.symbol, f"{c.close_reason} @ {c.close_price}")
            if p.status == "OPEN":
                positions.append(_position_dict(p, current))
        return jsonify({
            "positions": positions,
            "activity": activity[:20],
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })

    @app.post("/api/trade")
    def api_trade():
        gate = _confirm_required_response()
        if gate:
            return gate
        body = request.get_json(silent=True) or {}
        symbol = (body.get("symbol") or "").upper()
        if not symbol:
            return jsonify({"status": "ERROR", "message": "symbol is required"}), 400
        signal = engine.run([symbol])[0]
        result = executor.execute(signal)
        log("trade", symbol, result["message"])
        payload = {"status": result["status"], "message": result["message"],
                   "signal": _signal_dict(signal)}
        if result.get("position"):
            payload["position"] = _position_dict(result["position"])
        return jsonify(payload)

    @app.post("/api/close")
    def api_close():
        gate = _confirm_required_response()
        if gate:
            return gate
        body = request.get_json(silent=True) or {}
        symbol = (body.get("symbol") or "").upper()
        if not symbol:
            return jsonify({"status": "ERROR", "message": "symbol is required"}), 400
        try:
            current = float(feed.last_price(symbol))
        except Exception:
            current = None
        try:
            pos = broker.close(symbol, current if current is not None else 0.0, reason="MANUAL")
        except ValueError as exc:
            return jsonify({"status": "NOOP", "message": str(exc)}), 200
        log("close", symbol, f"Closed @ {pos.close_price}")
        return jsonify({"status": "CLOSED", "message": f"Closed {symbol}",
                        "position": _position_dict(pos)})

    return app


def run() -> None:  # pragma: no cover - manual entry point
    cfg = load_config()
    app = create_app(cfg)
    app.run(host=cfg.web_host, port=cfg.web_port, debug=False)


if __name__ == "__main__":  # pragma: no cover
    run()
