"""Repositories for SOL Reversal isolated database."""

from __future__ import annotations

import json
from typing import Any

from app.models import utc_now_iso
from app.strategies.sol_reversal.db import get_sol_connection
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS


class SolAccountRepository:
    def ensure(self, initial: float = 1000.0) -> dict[str, Any]:
        now = utc_now_iso()
        with get_sol_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sol_account (id, balance, realized_pnl, updated_at) VALUES (1, ?, 0, ?)",
                (initial, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sol_account WHERE id = 1").fetchone()
        return dict(row)

    def get(self) -> dict[str, Any]:
        return self.ensure()

    def apply_pnl(self, pnl: float) -> dict[str, Any]:
        now = utc_now_iso()
        with get_sol_connection() as conn:
            conn.execute(
                "UPDATE sol_account SET balance = balance + ?, realized_pnl = realized_pnl + ?, updated_at = ? WHERE id = 1",
                (pnl, pnl, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sol_account WHERE id = 1").fetchone()
        return dict(row)


class SolSettingsRepository:
    def get_all(self) -> dict[str, Any]:
        with get_sol_connection() as conn:
            rows = conn.execute("SELECT key, value FROM sol_settings").fetchall()
        settings = dict(DEFAULT_SETTINGS)
        for row in rows:
            try:
                settings[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                settings[row["key"]] = row["value"]
        return settings

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.get_all()
        current.update(updates)
        now = utc_now_iso()
        with get_sol_connection() as conn:
            for key, value in updates.items():
                conn.execute(
                    """
                    INSERT INTO sol_settings (key, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), now),
                )
            conn.commit()
        return current


class SolPositionRepository:
    def open_position(self, data: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        with get_sol_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO sol_positions (
                    symbol, side, entry, stop_loss, take_profit, quantity, leverage,
                    margin_used, position_value, status, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?)
                """,
                (
                    data["symbol"], data["side"], data["entry"], data["stop_loss"],
                    data["take_profit"], data["quantity"], data["leverage"],
                    data["margin_used"], data["position_value"], now,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sol_positions WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(row)

    def get_open(self) -> dict[str, Any] | None:
        with get_sol_connection() as conn:
            row = conn.execute(
                "SELECT * FROM sol_positions WHERE status = 'OPEN' ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def update_position(self, pos_id: int, updates: dict[str, Any]) -> None:
        if not updates:
            return
        cols = ", ".join(f"{k} = ?" for k in updates)
        vals = list(updates.values()) + [pos_id]
        with get_sol_connection() as conn:
            conn.execute(f"UPDATE sol_positions SET {cols} WHERE id = ?", vals)
            conn.commit()

    def close_position(self, pos_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with get_sol_connection() as conn:
            conn.execute(
                """
                UPDATE sol_positions SET
                    status = 'CLOSED', closed_at = ?, exit_price = ?, exit_reason = ?,
                    pnl_usd = ?, pnl_pct = ?, bars_held = ?, lock_active = ?, lock_stop = ?,
                    highest_profit_pct = ?, mfe_pct = ?, mae_pct = ?
                WHERE id = ?
                """,
                (
                    data["closed_at"], data["exit_price"], data["exit_reason"],
                    data["pnl_usd"], data["pnl_pct"], data["bars_held"],
                    int(data.get("lock_active", 0)), data.get("lock_stop"),
                    data.get("highest_profit_pct", 0), data.get("mfe_pct", 0), data.get("mae_pct", 0),
                    pos_id,
                ),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM sol_positions WHERE id = ?", (pos_id,)).fetchone()
        return dict(row)

    def list_closed(self, limit: int = 500) -> list[dict[str, Any]]:
        with get_sol_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sol_positions WHERE status = 'CLOSED' ORDER BY closed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


class SolTradeRepository:
    def insert(self, trade: dict[str, Any]) -> None:
        with get_sol_connection() as conn:
            conn.execute(
                """
                INSERT INTO sol_trades (
                    position_id, symbol, side, entry_time, exit_time, entry, exit,
                    pnl_pct, pnl_usd, bars_held, exit_reason, mfe_pct, mae_pct
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.get("position_id"), trade["symbol"], trade["side"],
                    trade["entry_time"], trade["exit_time"], trade["entry"], trade["exit"],
                    trade["pnl_pct"], trade["pnl_usd"], trade["bars_held"],
                    trade["exit_reason"], trade.get("mfe_pct", 0), trade.get("mae_pct", 0),
                ),
            )
            conn.commit()


class SolEngineRepository:
    def ensure(self) -> None:
        now = utc_now_iso()
        with get_sol_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sol_engine_state (id, running, updated_at) VALUES (1, 1, ?)",
                (now,),
            )
            conn.commit()

    def update(self, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now_iso()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_sol_connection() as conn:
            conn.execute(f"UPDATE sol_engine_state SET {cols} WHERE id = 1", list(fields.values()))
            conn.commit()

    def get(self) -> dict[str, Any]:
        self.ensure()
        with get_sol_connection() as conn:
            row = conn.execute("SELECT * FROM sol_engine_state WHERE id = 1").fetchone()
        return dict(row)

    def log(self, level: str, message: str) -> None:
        with get_sol_connection() as conn:
            conn.execute(
                "INSERT INTO sol_engine_log (level, message, created_at) VALUES (?, ?, ?)",
                (level, message, utc_now_iso()),
            )
            conn.commit()

    def recent_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        with get_sol_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sol_engine_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
