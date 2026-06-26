"""Command-line entry point.

  python cli.py demo       # offline end-to-end demo in mock mode (no network)
  python cli.py signals    # compute live signals for your watchlist (uses yfinance)
"""
from __future__ import annotations

import argparse

from config import load_config
from strategy.ema_crossover import EMACrossover
from signals.engine import SignalEngine
from broker.mock_broker import MockBroker
from trader.executor import Executor


def cmd_signals(cfg) -> None:
    from data.price_feed import YFinanceFeed

    strat = EMACrossover(cfg.ema_fast, cfg.ema_slow, cfg.take_profit_pct, cfg.stop_loss_pct)
    engine = SignalEngine(strat, YFinanceFeed(), cfg.candle_period, cfg.candle_interval)
    print(f"Signals for {', '.join(cfg.watchlist)}  (EMA{cfg.ema_fast}/{cfg.ema_slow}, {cfg.candle_interval}):")
    for s in engine.run(cfg.watchlist):
        tp = f"  TP {s.take_profit}" if s.take_profit else ""
        sl = f"  SL {s.stop_loss}" if s.stop_loss else ""
        print(f"  {s.symbol:6} {s.action.value:4} @ {s.price:>8.2f}{tp}{sl}   — {s.reason}")


def cmd_demo(cfg) -> None:
    import pandas as pd

    print("OFFLINE DEMO (mock mode) — no network, no broker needed\n")
    strat = EMACrossover(fast=2, slow=4, take_profit_pct=3.0, stop_loss_pct=2.0)
    candles = pd.DataFrame({"Close": [10, 10, 10, 10, 10, 10, 12]})
    sig = strat.generate("DEMO", candles)
    print(f"1) Signal      : {sig.action.value} {sig.symbol} @ {sig.price}  (TP {sig.take_profit}, SL {sig.stop_loss})")

    broker = MockBroker()
    ex = Executor(broker, quantity=1)
    res = ex.execute(sig)
    print(f"2) Trade button: {res['status']} — {res['message']}")

    print("3) Soft-stop watch (feeding live prices):")
    for px in [12.20, 12.30, sig.take_profit]:
        closed = broker.update_price("DEMO", px)
        tag = f"  -> CLOSED ({closed[0].close_reason} @ {closed[0].close_price})" if closed else ""
        print(f"     price {px:>6.2f}{tag}")

    print("\nDone — the position automatically took profit. (All fake money.)")


def cmd_web(cfg) -> None:
    from web.app import create_app, build_broker

    broker = build_broker(cfg)
    if cfg.broker == "moomoo":
        try:
            broker.connect()
            print("Connected to moomoo via OpenD.")
        except Exception as exc:
            print(f"WARNING: moomoo not connected — {exc}\nServing dashboard anyway; trades will error until connected.")
    app = create_app(cfg, broker=broker)
    print(f"Dashboard: http://{cfg.web_host}:{cfg.web_port}   (mode: {cfg.mode_label}, data: {cfg.data_source})")
    app.run(host=cfg.web_host, port=cfg.web_port, debug=False)


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="tsh", description="TradingSignalandHelper")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("signals", help="compute signals for the watchlist (uses yfinance)")
    sub.add_parser("demo", help="offline end-to-end demo in mock mode")
    sub.add_parser("web", help="launch the local dashboard + one-button trader")
    args = parser.parse_args()

    if args.cmd == "signals":
        cmd_signals(cfg)
    elif args.cmd == "demo":
        cmd_demo(cfg)
    elif args.cmd == "web":
        cmd_web(cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
