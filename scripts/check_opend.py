#!/usr/bin/env python3
"""Read-only OpenD connectivity probe — places NO orders.

Run it AFTER OpenD is running and logged in, from the repo root:

    .venv/bin/python scripts/check_opend.py

It uses your .env (OPEND_HOST/PORT, MOOMOO_SECURITY_FIRM, TRD_ENV), opens a trade
context against your brokerage entity, lists your accounts, and tells you whether a
paper (SIMULATE) account is available. Nothing here can move money.
"""
from __future__ import annotations

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_config  # noqa: E402


def _port_open(host: str, port: int, timeout: float = 3.0) -> bool:
    """Fast pre-flight so we fail cleanly instead of the SDK retry-hanging."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def main() -> int:
    cfg = load_config()
    print(
        f"OpenD target {cfg.opend_host}:{cfg.opend_port} · entity {cfg.moomoo_security_firm} "
        f"· env {cfg.trd_env}"
    )
    try:
        import moomoo as sdk
    except Exception as exc:  # SDK not installed
        print("FAIL · moomoo SDK missing. Run: .venv/bin/pip install -r requirements-moomoo.txt")
        print(f"       ({exc})")
        return 2

    firm = getattr(sdk.SecurityFirm, cfg.moomoo_security_firm, None)
    if firm is None:
        print(f"FAIL · unknown MOOMOO_SECURITY_FIRM={cfg.moomoo_security_firm}")
        return 2

    if not _port_open(cfg.opend_host, cfg.opend_port):
        print(f"FAIL · nothing listening at {cfg.opend_host}:{cfg.opend_port}.")
        print("       Start OpenD and log in first, then re-run this probe.")
        return 1

    try:
        ctx = sdk.OpenSecTradeContext(
            filter_trdmarket=sdk.TrdMarket.US,
            host=cfg.opend_host,
            port=cfg.opend_port,
            security_firm=firm,
        )
    except Exception as exc:
        print(f"FAIL · cannot reach OpenD at {cfg.opend_host}:{cfg.opend_port}.")
        print("       Is OpenD running and logged in? Is the port right?")
        print(f"       ({exc})")
        return 1

    try:
        ret, data = ctx.get_acc_list()
        if ret != sdk.RET_OK:
            print(f"FAIL · get_acc_list error: {data}")
            print("       Hint: does MOOMOO_SECURITY_FIRM match your account's entity?")
            return 1
        print("OK · connected. Accounts:")
        print(data.to_string() if hasattr(data, "to_string") else data)
        try:
            envs = [str(v).upper() for v in list(data["trd_env"])] if "trd_env" in getattr(data, "columns", []) else []
            if any("SIMULATE" in e for e in envs):
                print("OK · a SIMULATE (paper) account is available → set TRD_ENV=SIMULATE.")
            else:
                print("WARN · no SIMULATE account listed → enable Paper Trading in the moomoo app.")
        except Exception:
            pass
        return 0
    finally:
        ctx.close()


if __name__ == "__main__":
    raise SystemExit(main())
