"""Durable SQLite state for signals, orders, positions, and activity."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Union
from uuid import uuid4

from models import Action, Position, Signal


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _datetime(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


class StateStore:
    """Small thread-safe-by-connection SQLite repository."""

    def __init__(self, path: Union[str, Path]) -> None:
        raw_path = str(path)
        self._keeper: Optional[sqlite3.Connection] = None
        if raw_path == ":memory:":
            self.path = raw_path
            self._database = f"file:trading-helper-{uuid4().hex}?mode=memory&cache=shared"
            self._uri = True
            self._keeper = self._connect()
        else:
            self.path = raw_path
            db_path = Path(raw_path)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._database = raw_path
            self._uri = False
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self._database,
            uri=self._uri,
            timeout=5.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def _initialize(self) -> None:
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS signals (
                    symbol TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    take_profit REAL,
                    stop_loss REAL,
                    reason TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS positions (
                    position_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    avg_price REAL NOT NULL,
                    take_profit REAL,
                    stop_loss REAL,
                    status TEXT NOT NULL,
                    close_price REAL,
                    close_reason TEXT NOT NULL,
                    opened_at TEXT NOT NULL,
                    closed_at TEXT,
                    entry_order_id TEXT,
                    take_profit_order_id TEXT,
                    take_profit_order_quantity REAL,
                    stop_loss_order_id TEXT,
                    stop_loss_order_quantity REAL,
                    exit_order_id TEXT,
                    exit_order_quantity REAL
                );

                CREATE UNIQUE INDEX IF NOT EXISTS one_open_position_per_symbol
                ON positions(symbol) WHERE status != 'CLOSED';

                CREATE TABLE IF NOT EXISTS orders (
                    request_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    position_id TEXT REFERENCES positions(position_id),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS activity (
                    activity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    time TEXT NOT NULL,
                    type TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    message TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS webhook_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    claimed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS symbol_claims (
                    symbol TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    claimed_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    source TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER,
                    tp REAL,
                    sl REAL,
                    status TEXT NOT NULL,
                    message TEXT NOT NULL,
                    event_id TEXT
                );
                """
            )
            position_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(positions)")
            }
            expected_columns = {
                "take_profit_order_quantity": "REAL",
                "exit_order_quantity": "REAL",
                "stop_loss_order_id": "TEXT",
                "stop_loss_order_quantity": "REAL",
            }
            for name, coltype in expected_columns.items():
                if name not in position_columns:
                    conn.execute(f"ALTER TABLE positions ADD COLUMN {name} {coltype}")

    def save_signal(self, signal: Signal) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO signals (
                    symbol, action, price, take_profit, stop_loss, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    action = excluded.action,
                    price = excluded.price,
                    take_profit = excluded.take_profit,
                    stop_loss = excluded.stop_loss,
                    reason = excluded.reason,
                    timestamp = excluded.timestamp
                """,
                (
                    signal.symbol,
                    signal.action.value,
                    signal.price,
                    signal.take_profit,
                    signal.stop_loss,
                    signal.reason,
                    signal.timestamp.isoformat(),
                ),
            )

    def load_positions(self, open_only: bool = False) -> List[Position]:
        query = "SELECT * FROM positions"
        if open_only:
            query += " WHERE status != 'CLOSED'"
        query += " ORDER BY opened_at, position_id"
        with self._connection() as conn:
            rows = conn.execute(query).fetchall()
        return [
            Position(
                symbol=row["symbol"],
                quantity=row["quantity"],
                avg_price=row["avg_price"],
                take_profit=row["take_profit"],
                stop_loss=row["stop_loss"],
                status=row["status"],
                close_price=row["close_price"],
                close_reason=row["close_reason"],
                opened_at=datetime.fromisoformat(row["opened_at"]),
                closed_at=_datetime(row["closed_at"]),
                position_id=row["position_id"],
                entry_order_id=row["entry_order_id"],
                take_profit_order_id=row["take_profit_order_id"],
                take_profit_order_quantity=row["take_profit_order_quantity"],
                stop_loss_order_id=row["stop_loss_order_id"],
                stop_loss_order_quantity=row["stop_loss_order_quantity"],
                exit_order_id=row["exit_order_id"],
                exit_order_quantity=row["exit_order_quantity"],
            )
            for row in rows
        ]

    def begin_order(
        self,
        request_id: str,
        signal: Signal,
        quantity: int,
        source: str,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO orders (
                        request_id, source, symbol, side, quantity, status, message,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'PENDING', '', ?, ?)
                    """,
                    (
                        request_id,
                        source,
                        signal.symbol,
                        signal.action.value,
                        quantity,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def finish_order(
        self,
        request_id: str,
        status: str,
        message: str,
        position: Optional[Position] = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET status = ?, message = ?, position_id = ?, updated_at = ?
                WHERE request_id = ?
                """,
                (
                    status,
                    message,
                    position.position_id if position else None,
                    datetime.now(timezone.utc).isoformat(),
                    request_id,
                ),
            )

    def get_order(self, request_id: str) -> Optional[Dict[str, object]]:
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT request_id, source, symbol, side, quantity, status, message,
                       position_id
                FROM orders WHERE request_id = ?
                """,
                (request_id,),
            ).fetchone()
        return dict(row) if row else None

    def add_activity(self, kind: str, symbol: str, message: str) -> None:
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO activity (time, type, symbol, message) VALUES (?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), kind, symbol, message),
            )

    def recent_activity(self, limit: int = 20) -> List[Dict[str, object]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT time, type, symbol, message
                FROM activity ORDER BY activity_id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_event(
        self,
        source: str,
        symbol: str,
        action: str,
        quantity: Optional[int],
        tp: Optional[float],
        sl: Optional[float],
        status: str,
        message: str,
        event_id: Optional[str] = None,
    ) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    ts, source, symbol, action, quantity, tp, sl, status, message, event_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    source,
                    symbol,
                    action,
                    quantity,
                    tp,
                    sl,
                    status,
                    message,
                    event_id,
                ),
            )

    def recent_events(self, limit: int = 50) -> List[Dict[str, object]]:
        with self._connection() as conn:
            rows = conn.execute(
                """
                SELECT ts, source, symbol, action, quantity, tp, sl, status, message, event_id
                FROM events ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        events: List[Dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["time"] = datetime.fromisoformat(str(item["ts"])).strftime("%H:%M:%S")
            events.append(item)
        return events

    def claim_webhook_event(self, event_id: str, occurred_at: str) -> bool:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO webhook_events (event_id, occurred_at, claimed_at)
                    VALUES (?, ?, ?)
                    """,
                    (event_id, occurred_at, datetime.now(timezone.utc).isoformat()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_webhook_event(self, event_id: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM webhook_events WHERE event_id = ?", (event_id,))

    def claim_symbol(self, symbol: str, request_id: str) -> bool:
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    INSERT INTO symbol_claims (symbol, request_id, claimed_at)
                    VALUES (?, ?, ?)
                    """,
                    (symbol, request_id, datetime.now(timezone.utc).isoformat()),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def release_symbol(self, symbol: str) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM symbol_claims WHERE symbol = ?", (symbol,))

    def realized_pnl_since(self, start_iso: str) -> float:
        """Sum realized P&L of long positions CLOSED at/after ``start_iso``.

        Long-only: realized P&L = (close_price - avg_price) * quantity. Open
        positions and closes before the window are excluded. Feeds the REAL-mode
        daily-loss kill-switch.
        """
        with self._connection() as conn:
            row = conn.execute(
                """
                SELECT COALESCE(SUM((close_price - avg_price) * quantity), 0.0)
                FROM positions
                WHERE status = 'CLOSED'
                  AND close_price IS NOT NULL
                  AND closed_at >= ?
                """,
                (start_iso,),
            ).fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0

    def close(self) -> None:
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    def latest_signals(self) -> List[Signal]:
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM signals ORDER BY symbol").fetchall()
        return [
            Signal(
                symbol=row["symbol"],
                action=Action(row["action"]),
                price=row["price"],
                take_profit=row["take_profit"],
                stop_loss=row["stop_loss"],
                reason=row["reason"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
            )
            for row in rows
        ]

    def save_position(self, position: Position) -> None:
        with self._connection() as conn:
            conn.execute(
                """
                INSERT INTO positions (
                    position_id, symbol, quantity, avg_price, take_profit, stop_loss,
                    status, close_price, close_reason, opened_at, closed_at,
                    entry_order_id, take_profit_order_id, take_profit_order_quantity,
                    stop_loss_order_id, stop_loss_order_quantity,
                    exit_order_id, exit_order_quantity
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(position_id) DO UPDATE SET
                    symbol = excluded.symbol,
                    quantity = excluded.quantity,
                    avg_price = excluded.avg_price,
                    take_profit = excluded.take_profit,
                    stop_loss = excluded.stop_loss,
                    status = excluded.status,
                    close_price = excluded.close_price,
                    close_reason = excluded.close_reason,
                    opened_at = excluded.opened_at,
                    closed_at = excluded.closed_at,
                    entry_order_id = excluded.entry_order_id,
                    take_profit_order_id = excluded.take_profit_order_id,
                    take_profit_order_quantity = excluded.take_profit_order_quantity,
                    stop_loss_order_id = excluded.stop_loss_order_id,
                    stop_loss_order_quantity = excluded.stop_loss_order_quantity,
                    exit_order_id = excluded.exit_order_id,
                    exit_order_quantity = excluded.exit_order_quantity
                """,
                (
                    position.position_id,
                    position.symbol,
                    position.quantity,
                    position.avg_price,
                    position.take_profit,
                    position.stop_loss,
                    position.status,
                    position.close_price,
                    position.close_reason,
                    position.opened_at.isoformat(),
                    _iso(position.closed_at),
                    position.entry_order_id,
                    position.take_profit_order_id,
                    position.take_profit_order_quantity,
                    position.stop_loss_order_id,
                    position.stop_loss_order_quantity,
                    position.exit_order_id,
                    position.exit_order_quantity,
                ),
            )
