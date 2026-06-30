"""Persist and load backtest runs."""

from __future__ import annotations

import json
from typing import Any

from app.backtest.db import get_backtest_connection
from app.models import utc_now_iso


def save_run(result: dict[str, Any], name: str | None = None) -> int:
    stats = result["statistics"]
    config = result.get("config", {})
    params = {
        "settings": result.get("settings"),
        "config": config,
    }
    now = utc_now_iso()
    with get_backtest_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO backtest_runs (
                strategy_id, name, symbol, timeframe, start_date, end_date,
                initial_capital, final_equity, params_json, stats_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result["strategy_id"],
                name or f"Run {now[:16]}",
                result["symbol"],
                result["timeframe"],
                result["start_date"],
                result["end_date"],
                stats["initial_capital"],
                stats["final_equity"],
                json.dumps(params),
                json.dumps(stats),
                now,
            ),
        )
        run_id = int(cur.lastrowid)

        for tr in result.get("trades", []):
            conn.execute(
                """
                INSERT INTO backtest_trades (
                    run_id, trade_num, side, entry_time, exit_time, entry_price, exit_price,
                    price_move_pct, pnl_usd, bars_held, exit_reason, mfe_pct, mae_pct,
                    lock_active, highest_profit_pct, stop_loss, take_profit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tr.get("trade_num"),
                    tr["side"],
                    tr["entry_time"],
                    tr["exit_time"],
                    tr["entry_price"],
                    tr["exit_price"],
                    tr.get("price_move_pct", 0),
                    tr["pnl_usd"],
                    tr.get("bars_held", 0),
                    tr.get("exit_reason", ""),
                    tr.get("mfe_pct"),
                    tr.get("mae_pct"),
                    int(bool(tr.get("lock_active"))),
                    tr.get("highest_profit_pct"),
                    tr.get("stop_loss"),
                    tr.get("take_profit"),
                ),
            )

        for pt in result.get("equity_curve", []):
            if pt.get("time") is None:
                continue
            conn.execute(
                """
                INSERT INTO backtest_equity (run_id, time, equity, drawdown_pct, trade_num)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    int(pt["time"]),
                    pt["equity"],
                    pt.get("drawdown_pct", 0),
                    pt.get("trade_num"),
                ),
            )

        for row in result.get("monthly_report", []):
            conn.execute(
                """
                INSERT INTO backtest_monthly (run_id, month, trades, profit, win_rate, profit_factor)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    row["month"],
                    row["trades"],
                    row["profit"],
                    row["win_rate"],
                    row["profit_factor"],
                ),
            )
        conn.commit()
    return run_id


def list_runs(strategy_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with get_backtest_connection() as conn:
        if strategy_id:
            rows = conn.execute(
                """
                SELECT id, strategy_id, name, symbol, timeframe, start_date, end_date,
                       initial_capital, final_equity, stats_json, created_at
                FROM backtest_runs WHERE strategy_id = ? ORDER BY id DESC LIMIT ?
                """,
                (strategy_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, strategy_id, name, symbol, timeframe, start_date, end_date,
                       initial_capital, final_equity, stats_json, created_at
                FROM backtest_runs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["statistics"] = json.loads(d.pop("stats_json"))
        out.append(d)
    return out


def get_run(run_id: int) -> dict[str, Any] | None:
    with get_backtest_connection() as conn:
        row = conn.execute("SELECT * FROM backtest_runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        trades = conn.execute(
            "SELECT * FROM backtest_trades WHERE run_id = ? ORDER BY trade_num",
            (run_id,),
        ).fetchall()
        equity = conn.execute(
            "SELECT time, equity, drawdown_pct, trade_num FROM backtest_equity WHERE run_id = ? ORDER BY time",
            (run_id,),
        ).fetchall()
        monthly = conn.execute(
            "SELECT month, trades, profit, win_rate, profit_factor FROM backtest_monthly WHERE run_id = ? ORDER BY month",
            (run_id,),
        ).fetchall()
    result = dict(row)
    result["statistics"] = json.loads(result.pop("stats_json"))
    result["params"] = json.loads(result.pop("params_json"))
    result["trades"] = [dict(t) for t in trades]
    result["equity_curve"] = [dict(e) for e in equity]
    result["monthly_report"] = [dict(m) for m in monthly]
    return result
