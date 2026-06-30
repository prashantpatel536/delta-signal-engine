"""Isolated SQLite database for SOL Reversal Engine (sol_reversal.db)."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.config import PROJECT_ROOT

SOL_DB_PATH = PROJECT_ROOT / "data" / "sol_reversal.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sol_account (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    balance REAL NOT NULL DEFAULT 1000.0,
    realized_pnl REAL NOT NULL DEFAULT 0.0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sol_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sol_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL DEFAULT 'SOLUSDT',
    side TEXT NOT NULL,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL NOT NULL,
    quantity REAL NOT NULL,
    leverage REAL NOT NULL DEFAULT 25.0,
    margin_used REAL NOT NULL,
    position_value REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'OPEN',
    lock_active INTEGER NOT NULL DEFAULT 0,
    lock_stop REAL,
    highest_profit_pct REAL NOT NULL DEFAULT 0.0,
    highest_price REAL,
    mfe_pct REAL NOT NULL DEFAULT 0.0,
    mae_pct REAL NOT NULL DEFAULT 0.0,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price REAL,
    exit_reason TEXT,
    pnl_usd REAL,
    pnl_pct REAL,
    bars_held INTEGER
);

CREATE INDEX IF NOT EXISTS idx_sol_positions_status ON sol_positions(status);

CREATE TABLE IF NOT EXISTS sol_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    entry REAL NOT NULL,
    exit REAL NOT NULL,
    pnl_pct REAL NOT NULL,
    pnl_usd REAL NOT NULL,
    bars_held INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    mfe_pct REAL NOT NULL DEFAULT 0.0,
    mae_pct REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (position_id) REFERENCES sol_positions(id)
);

CREATE TABLE IF NOT EXISTS sol_engine_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sol_engine_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    running INTEGER NOT NULL DEFAULT 1,
    last_candle_time INTEGER,
    last_price REAL,
    last_signal TEXT,
    updated_at TEXT NOT NULL
);
"""


def init_sol_db() -> None:
    SOL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_sol_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_sol_connection():
    conn = sqlite3.connect(SOL_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()
