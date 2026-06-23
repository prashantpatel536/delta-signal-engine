"""SQLite database initialization and connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    side TEXT NOT NULL,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    risk_reward REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_tf ON signals(symbol, timeframe);
CREATE INDEX IF NOT EXISTS idx_signals_pending_side
    ON signals(symbol, timeframe, side, status);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    quantity REAL NOT NULL DEFAULT 1.0,
    leverage REAL NOT NULL DEFAULT 1.0,
    margin_used REAL NOT NULL DEFAULT 0.0,
    position_value REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl REAL,
    FOREIGN KEY (signal_id) REFERENCES signals(id)
);

CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_signal ON positions(signal_id);

CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    field_name TEXT,
    old_value REAL,
    new_value REAL,
    message TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(id)
);

CREATE INDEX IF NOT EXISTS idx_position_events_position ON position_events(position_id);

CREATE TABLE IF NOT EXISTS telegram_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    message_preview TEXT,
    sent_at TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_telegram_notifications_entity
    ON telegram_notifications(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance REAL NOT NULL DEFAULT 1000.0,
    realized_pnl REAL NOT NULL DEFAULT 0.0
);
"""

SIGNAL_MIGRATIONS = [
    "ALTER TABLE signals ADD COLUMN max_favorable_excursion REAL NOT NULL DEFAULT 0",
    "ALTER TABLE signals ADD COLUMN max_adverse_excursion REAL NOT NULL DEFAULT 0",
    "ALTER TABLE signals ADD COLUMN points_captured REAL",
    "ALTER TABLE signals ADD COLUMN missed_monitoring INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE signals ADD COLUMN monitoring_started_at TEXT",
    "ALTER TABLE signals ADD COLUMN missed_resolved_at TEXT",
    "ALTER TABLE signals ADD COLUMN missed_exit_reason TEXT",
    "ALTER TABLE signals ADD COLUMN missed_exit_price REAL",
]

MIGRATIONS = [
    "ALTER TABLE positions ADD COLUMN quantity REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE positions ADD COLUMN leverage REAL NOT NULL DEFAULT 1.0",
    "ALTER TABLE positions ADD COLUMN margin_used REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE positions ADD COLUMN position_value REAL NOT NULL DEFAULT 0.0",
    "ALTER TABLE positions ADD COLUMN original_stop_loss REAL",
    "ALTER TABLE positions ADD COLUMN original_take_profit REAL",
    "ALTER TABLE positions ADD COLUMN risk_reward REAL NOT NULL DEFAULT 0.0",
]


def _signal_id_requires_migration(conn: sqlite3.Connection) -> bool:
    rows = conn.execute("PRAGMA table_info(positions)").fetchall()
    for row in rows:
        if row[1] == "signal_id" and row[3] == 1:
            return True
    return False


def _migrate_nullable_signal_id(conn: sqlite3.Connection) -> None:
    """Legacy DBs enforced NOT NULL on signal_id; paper trades omit it."""
    if not _signal_id_requires_migration(conn):
        return
    conn.executescript(
        """
        CREATE TABLE positions_migrated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            signal_id INTEGER,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            entry REAL NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL,
            quantity REAL NOT NULL DEFAULT 1.0,
            leverage REAL NOT NULL DEFAULT 1.0,
            margin_used REAL NOT NULL DEFAULT 0.0,
            position_value REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            opened_at TEXT NOT NULL,
            closed_at TEXT,
            exit_price REAL,
            exit_reason TEXT,
            pnl REAL,
            FOREIGN KEY (signal_id) REFERENCES signals(id)
        );
        INSERT INTO positions_migrated (
            id, signal_id, symbol, side, entry, stop_loss, take_profit,
            quantity, leverage, margin_used, position_value,
            status, opened_at, closed_at, exit_price, exit_reason, pnl
        )
        SELECT
            id, signal_id, symbol, side, entry, stop_loss, take_profit,
            quantity, leverage, margin_used, position_value,
            status, opened_at, closed_at, exit_price, exit_reason, pnl
        FROM positions;
        DROP TABLE positions;
        ALTER TABLE positions_migrated RENAME TO positions;
        CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
        CREATE INDEX IF NOT EXISTS idx_positions_signal ON positions(signal_id);
        """
    )


def _apply_signal_migrations(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(signals)").fetchall()}
    for sql in SIGNAL_MIGRATIONS:
        col = sql.split("ADD COLUMN ")[1].split()[0]
        if col not in existing:
            conn.execute(sql)
            existing.add(col)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    _apply_signal_migrations(conn)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
    for sql in MIGRATIONS:
        col = sql.split("ADD COLUMN ")[1].split()[0]
        if col not in existing:
            conn.execute(sql)
            existing.add(col)
    conn.execute(
        """
        INSERT OR IGNORE INTO paper_account (id, balance, realized_pnl)
        VALUES (1, 1000.0, 0.0)
        """
    )
    _migrate_nullable_signal_id(conn)
    _backfill_position_originals(conn)


def _backfill_position_originals(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(positions)").fetchall()}
    if "original_stop_loss" not in cols:
        return
    conn.execute(
        """
        UPDATE positions
        SET original_stop_loss = stop_loss
        WHERE original_stop_loss IS NULL
        """
    )
    conn.execute(
        """
        UPDATE positions
        SET original_take_profit = take_profit
        WHERE original_take_profit IS NULL
        """
    )


def get_db_path() -> Path:
    return settings.database_path


def ensure_data_dir() -> None:
    get_db_path().parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    ensure_data_dir()
    conn = sqlite3.connect(get_db_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables if they do not exist."""
    ensure_data_dir()
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        _apply_migrations(conn)
        conn.commit()
