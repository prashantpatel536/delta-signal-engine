"""SQLite schema for backtest runs and persistent candle cache."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import PROJECT_ROOT

BACKTEST_DB_PATH = PROJECT_ROOT / "data" / "backtest.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candle_bars (
    symbol TEXT NOT NULL,
    resolution TEXT NOT NULL,
    time INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, resolution, time)
);

CREATE INDEX IF NOT EXISTS idx_candle_bars_range
    ON candle_bars(symbol, resolution, time);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    name TEXT,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_equity REAL NOT NULL,
    params_json TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_strategy ON backtest_runs(strategy_id);

CREATE TABLE IF NOT EXISTS backtest_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    trade_num INTEGER NOT NULL,
    side TEXT NOT NULL,
    entry_time INTEGER NOT NULL,
    exit_time INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL NOT NULL,
    price_move_pct REAL NOT NULL,
    pnl_usd REAL NOT NULL,
    bars_held INTEGER NOT NULL,
    exit_reason TEXT NOT NULL,
    mfe_pct REAL,
    mae_pct REAL,
    lock_active INTEGER DEFAULT 0,
    highest_profit_pct REAL,
    stop_loss REAL,
    take_profit REAL,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    time INTEGER NOT NULL,
    equity REAL NOT NULL,
    drawdown_pct REAL NOT NULL,
    trade_num INTEGER,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS backtest_monthly (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    month TEXT NOT NULL,
    trades INTEGER NOT NULL,
    profit REAL NOT NULL,
    win_rate REAL NOT NULL,
    profit_factor REAL NOT NULL,
    FOREIGN KEY (run_id) REFERENCES backtest_runs(id) ON DELETE CASCADE
);
"""


def init_backtest_db() -> None:
    BACKTEST_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(BACKTEST_DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def get_backtest_connection() -> sqlite3.Connection:
    init_backtest_db()
    conn = sqlite3.connect(BACKTEST_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
