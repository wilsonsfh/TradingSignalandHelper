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

import hmac
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional

from flask import Flask, jsonify, render_template, request

from config import Config, load_config
from strategy.ema_crossover import EMACrossover
from signals.engine import SignalEngine
from broker.base import Broker
from broker.mock_broker import MockBroker
from trader.executor import Executor
from trader.runtime import TradingRuntime
from state.store import StateStore
from signals.alerts import AlertError, parse_alert
from models import Signal, Position


def _build_feed(cfg: Config, broker: Broker):
    if cfg.broker == "moomoo":
        from data.price_feed import MoomooPriceFeed, YFinanceFeed

        return MoomooPriceFeed(YFinanceFeed(), broker)
    if cfg.data_source == "yfinance":
        from data.price_feed import YFinanceFeed

        return YFinanceFeed()
    from data.synthetic_feed import SyntheticFeed

    return SyntheticFeed()


def build_broker(
    cfg: Config,
    initial_positions: Optional[Iterable[Position]] = None,
) -> Broker:
    """Select a broker from config. moomoo broker is returned *unconnected*;
    call .connect() before serving (see cli.py web)."""
    if cfg.broker == "moomoo":
        from broker.moomoo_broker import MoomooBroker

        return MoomooBroker(
            host=cfg.opend_host,
            port=cfg.opend_port,
            trd_env=cfg.trd_env,
            use_broker_stop_order=cfg.use_broker_stop_order,
            initial_positions=initial_positions,
        )
    return MockBroker(initial_positions)


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
    runtime: Optional[TradingRuntime] = None,
    store: Optional[StateStore] = None,
) -> Flask:
    cfg = config or load_config()
    cfg.validate()
    injected_dependencies = broker is not None or feed is not None
    store = store or StateStore(":memory:" if injected_dependencies else cfg.state_db_path)
    broker = broker or build_broker(
        cfg,
        initial_positions=store.load_positions(open_only=True),
    )
    feed = feed or _build_feed(cfg, broker)
    strategy = EMACrossover(cfg.ema_fast, cfg.ema_slow, cfg.take_profit_pct, cfg.stop_loss_pct)
    engine = SignalEngine(strategy, feed, cfg.candle_period, cfg.candle_interval)
    executor = Executor(broker, cfg.quantity)
    runtime = runtime or TradingRuntime(
        broker,
        feed,
        executor,
        store,
        poll_seconds=cfg.soft_stop_poll_seconds,
    )

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
    app.extensions["trading_runtime"] = runtime

    def _json_body():
        body = request.get_json(silent=True)
        if body is None:
            return None if request.is_json else {}
        return body if isinstance(body, dict) else None

    def _confirm_required_response(body):
        if cfg.is_real_money and body.get("confirm") is not True:
            return jsonify({
                "status": "CONFIRM_REQUIRED",
                "message": "Real-money order needs explicit confirmation.",
            }), 412
        return None

    def _safe_record_event(source, symbol, action, quantity, tp, sl, status, message, event_id=None):
        """Best-effort event-log write; telemetry must never break trading."""
        try:
            store.record_event(source, symbol, action, quantity, tp, sl, status, message, event_id)
        except Exception:
            pass

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
        try:
            generated = engine.run(cfg.watchlist)
            for signal in generated:
                store.save_signal(signal)
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        signals = [_signal_dict(signal) for signal in generated]
        return jsonify({
            "signals": signals,
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })

    @app.get("/api/state")
    def api_state():
        try:
            positions = []
            for p in broker.open_positions():
                try:
                    current = float(feed.last_price(p.symbol))
                except Exception:
                    current = None
                if p.status != "CLOSED":
                    positions.append(_position_dict(p, current))
            activity = store.recent_activity()
            for item in activity:
                item["time"] = datetime.fromisoformat(str(item["time"])).strftime("%H:%M:%S")
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        return jsonify({
            "positions": positions,
            "activity": activity,
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })

    @app.get("/api/events")
    def api_events():
        try:
            events = store.recent_events()
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        return jsonify({
            "events": events,
            "mode": cfg.mode_label,
            "real_money": cfg.is_real_money,
        })

    @app.post("/api/trade")
    def api_trade():
        body = _json_body()
        if body is None:
            return jsonify({"status": "ERROR", "message": "JSON body must be an object"}), 400
        gate = _confirm_required_response(body)
        if gate:
            return gate
        symbol_value = body.get("symbol")
        if symbol_value is not None and not isinstance(symbol_value, str):
            return jsonify({"status": "ERROR", "message": "symbol must be a string"}), 400
        symbol = (symbol_value or "").upper()
        if not symbol:
            return jsonify({"status": "ERROR", "message": "symbol is required"}), 400
        if symbol not in cfg.watchlist:
            return jsonify({"status": "FORBIDDEN", "message": "symbol is outside the watchlist"}), 403
        try:
            signal = engine.run([symbol])[0]
            result = runtime.execute(
                signal,
                source="dashboard",
                request_id=body.get("request_id"),
            )
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        payload = {"status": result["status"], "message": result["message"],
                   "signal": _signal_dict(signal)}
        if result.get("position"):
            payload["position"] = _position_dict(result["position"])
        return jsonify(payload)

    @app.post("/api/close")
    def api_close():
        body = _json_body()
        if body is None:
            return jsonify({"status": "ERROR", "message": "JSON body must be an object"}), 400
        gate = _confirm_required_response(body)
        if gate:
            return gate
        symbol_value = body.get("symbol")
        if symbol_value is not None and not isinstance(symbol_value, str):
            return jsonify({"status": "ERROR", "message": "symbol must be a string"}), 400
        symbol = (symbol_value or "").upper()
        if not symbol:
            return jsonify({"status": "ERROR", "message": "symbol is required"}), 400
        if symbol not in cfg.watchlist:
            return jsonify({"status": "FORBIDDEN", "message": "symbol is outside the watchlist"}), 403
        try:
            current = float(feed.last_price(symbol))
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": f"no price available: {exc}"}), 503
        try:
            result = runtime.close(
                symbol,
                current,
                source="dashboard",
                request_id=body.get("request_id"),
            )
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        payload = {"status": result["status"], "message": result["message"]}
        if result.get("position"):
            payload["position"] = _position_dict(result["position"])
        return jsonify(payload)

    @app.post("/webhook")
    def webhook():
        """Optional, replay-resistant TradingView paper-trading entry point."""
        if not cfg.webhook_enabled:
            return jsonify({"status": "DISABLED", "message": "webhook is disabled"}), 404
        if len(cfg.webhook_secret.strip()) < 32 or cfg.webhook_secret == "change-me":
            return jsonify({
                "status": "MISCONFIGURED",
                "message": "configure a non-default WEBHOOK_SECRET",
            }), 503
        body = _json_body()
        if body is None:
            return jsonify({"status": "ERROR", "message": "JSON body must be an object"}), 400
        supplied_key = str(body.get("key", ""))
        if not hmac.compare_digest(supplied_key, cfg.webhook_secret):
            return jsonify({"status": "UNAUTHORIZED", "message": "bad or missing key"}), 401
        if cfg.is_real_money:
            return jsonify({
                "status": "DISABLED",
                "message": "webhook auto-trading is disabled in REAL-money mode",
            }), 403

        try:
            alert = parse_alert(
                body,
                watchlist=cfg.watchlist,
                max_quantity=cfg.max_alert_quantity,
                max_age_seconds=cfg.webhook_max_age_seconds,
            )
        except AlertError as exc:
            _safe_record_event(
                "webhook",
                str(body.get("symbol", "?")).upper()[:12] or "?",
                str(body.get("action", "?"))[:12],
                None, None, None,
                exc.label, str(exc),
                (str(body.get("event_id") or "") or None),
            )
            return jsonify({"status": exc.label, "message": str(exc)}), exc.status

        event_id = alert.event_id
        symbol = alert.symbol

        try:
            price = float(feed.last_price(symbol))
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": f"no price available: {exc}"}), 503
        try:
            claimed = store.claim_webhook_event(event_id, alert.occurred_at.isoformat())
        except Exception as exc:
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        if not claimed:
            _safe_record_event(
                "webhook", symbol, alert.action, alert.quantity,
                alert.take_profit, alert.stop_loss,
                "REPLAY", "event_id was already processed", event_id,
            )
            return jsonify({"status": "REPLAY", "message": "event_id was already processed"}), 409

        # The alert (Pine script) is the brain: honor its tp/sl when present,
        # falling back to the configured risk percentages only when absent.
        take_profit = alert.take_profit
        stop_loss = alert.stop_loss
        if alert.action == "open":
            if take_profit is None:
                take_profit = round(price * (1 + cfg.take_profit_pct / 100), 2)
            if stop_loss is None:
                stop_loss = round(price * (1 - cfg.stop_loss_pct / 100), 2)
        else:
            take_profit = stop_loss = None

        signal = Signal(
            symbol,
            alert.side,
            price,
            take_profit=take_profit,
            stop_loss=stop_loss,
            reason="tradingview webhook",
            quantity=alert.quantity,
        )
        try:
            result = runtime.execute(signal, source="webhook", request_id=event_id)
        except Exception as exc:
            try:
                store.release_webhook_event(event_id)
            except Exception:
                pass
            return jsonify({"status": "ERROR", "message": str(exc)}), 503
        payload = {"status": result["status"], "message": result["message"]}
        if result.get("position"):
            payload["position"] = _position_dict(result["position"])
        _safe_record_event(
            "webhook", symbol, alert.action, alert.quantity,
            take_profit, stop_loss, result["status"], result["message"], event_id,
        )
        if result["status"] == "ERROR":
            try:
                store.release_webhook_event(event_id)
            except Exception:
                pass
            return jsonify(payload), 503
        return jsonify(payload)

    return app


def run() -> None:  # pragma: no cover - manual entry point
    from cli import cmd_web

    cmd_web(load_config())


if __name__ == "__main__":  # pragma: no cover
    run()
