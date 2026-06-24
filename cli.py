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


def main() -> None:
    cfg = load_config()
    parser = argparse.ArgumentParser(prog="tsh", description="TradingSignalandHelper")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("signals", help="compute signals for the watchlist (uses yfinance)")
    sub.add_parser("demo", help="offline end-to-end demo in mock mode")
    args = parser.parse_args()

    if args.cmd == "signals":
        cmd_signals(cfg)
    elif args.cmd == "demo":
        cmd_demo(cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
