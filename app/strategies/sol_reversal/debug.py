"""Structured signal/trade debug tracing for Pine Script parity verification."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.models import utc_now_iso
from app.strategies.sol_reversal.db import get_sol_connection
from app.strategies.sol_reversal.indicators import compute_atr
from app.strategies.sol_reversal.strategy import _passes_atr, _passes_strong_candle, _streak_color

MAX_DEBUG_TRADES = 20


def explain_signal_at_index(
    ha: pd.DataFrame,
    settings: dict[str, Any],
    idx: int,
    *,
    atr: pd.Series | None = None,
) -> dict[str, Any]:
    """
    Full per-bar evaluation breakdown (maps to Pine Script variables).
  Returns every filter state even when no signal fires.
    """
    if idx < 1 or idx >= len(ha):
        return {"idx": idx, "signal": None, "reason": "index_out_of_range"}

    if atr is None:
        atr = compute_atr(ha, int(settings.get("atr_period", 14)))

    colors = ha["color"].tolist()
    row = ha.iloc[idx]
    prev_row = ha.iloc[idx - 1]
    atr_val = float(atr.iloc[idx]) if not pd.isna(atr.iloc[idx]) else 0.0

    min_red = int(settings.get("min_red_candles", 7))
    max_green = int(settings.get("max_green_candles", 3))

    color = colors[idx]
    is_red = color == "red"
    is_green = color == "green"
    is_doji = color == "doji"

    red_before = _streak_color(colors, idx - 1, "red")
    green_before = _streak_color(colors, idx - 1, "green")
    reds_now = _streak_color(colors, idx, "red") if is_red else 0
    greens_now = _streak_color(colors, idx, "green") if is_green else 0

    pine_consec_reds_prev = red_before if is_green else 0
    pine_consec_greens_now = greens_now

    body = float(row["close"]) - float(row["open"])
    strong_ok = _passes_strong_candle(row, atr_val, settings)
    atr_ok = _passes_atr(atr_val, settings)

    valid_green_seq = is_green and 1 <= greens_now <= max_green
    buy_streak_ok = red_before >= min_red
    buy_signal = valid_green_seq and buy_streak_ok and strong_ok and atr_ok
    signal = "BUY" if buy_signal else None

    return {
        "idx": idx,
        "time": int(row["time"]),
        "ha_open": round(float(row["open"]), 6),
        "ha_high": round(float(row["high"]), 6),
        "ha_low": round(float(row["low"]), 6),
        "ha_close": round(float(row["close"]), 6),
        "prev_ha_close": round(float(prev_row["close"]), 6),
        "color": color,
        "is_red": is_red,
        "is_green": is_green,
        "is_doji": is_doji,
        "pine_consec_reds_prev": pine_consec_reds_prev,
        "pine_consec_greens_now": pine_consec_greens_now,
        "red_streak_before": red_before,
        "green_streak_before": green_before,
        "red_streak_now": reds_now,
        "green_streak_now": greens_now,
        "min_red_required": min_red,
        "max_green_allowed": max_green,
        "valid_green_seq": valid_green_seq,
        "streak_ok_buy": buy_streak_ok,
        "body": round(body, 6),
        "atr": round(atr_val, 6),
        "strong_candle_ok": strong_ok,
        "atr_filter_ok": atr_ok,
        "buy_signal": buy_signal,
        "signal": signal,
        "settings_snapshot": {
            "min_red_candles": min_red,
            "max_green_candles": max_green,
            "strong_candle_enabled": settings.get("strong_candle_enabled"),
            "strong_candle_atr_mult": settings.get("strong_candle_atr_mult"),
            "atr_filter_enabled": settings.get("atr_filter_enabled"),
            "atr_minimum": settings.get("atr_minimum"),
            "enable_take_profit": settings.get("enable_take_profit"),
            "enable_stop_loss": settings.get("enable_stop_loss"),
            "process_orders_on_close": settings.get("process_orders_on_close"),
            "take_profit_pct": settings.get("take_profit_pct"),
            "stop_loss_pct": settings.get("stop_loss_pct"),
            "lock_profit_enabled": settings.get("lock_profit_enabled"),
            "lock_trigger_pct": settings.get("lock_trigger_pct"),
            "lock_distance_pct": settings.get("lock_distance_pct"),
        },
        "pine_gaps": [],
    }


def _trade_count() -> int:
    with get_sol_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM sol_debug_events WHERE event_type = 'TRADE_CLOSE'"
        ).fetchone()
    return int(row["c"]) if row else 0


def log_debug_event(event_type: str, payload: dict[str, Any]) -> int | None:
    """Persist debug event. Returns event id, or None if trade cap reached."""
    if event_type == "TRADE_CLOSE" and _trade_count() >= MAX_DEBUG_TRADES:
        return None
    now = utc_now_iso()
    with get_sol_connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO sol_debug_events (event_type, payload_json, created_at)
            VALUES (?, ?, ?)
            """,
            (event_type, json.dumps(payload, default=str), now),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_debug_events(
    *,
    event_type: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    with get_sol_connection() as conn:
        if event_type:
            rows = conn.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM sol_debug_events WHERE event_type = ?
                ORDER BY id DESC LIMIT ?
                """,
                (event_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, event_type, payload_json, created_at
                FROM sol_debug_events
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = json.loads(d.pop("payload_json"))
        out.append(d)
    return out


def clear_debug_events() -> int:
    with get_sol_connection() as conn:
        cur = conn.execute("DELETE FROM sol_debug_events")
        conn.commit()
        return cur.rowcount


def debug_summary() -> dict[str, Any]:
    with get_sol_connection() as conn:
        signals = conn.execute(
            "SELECT COUNT(*) AS c FROM sol_debug_events WHERE event_type IN ('SIGNAL', 'BUY_CONDITION')"
        ).fetchone()["c"]
        entries = conn.execute(
            "SELECT COUNT(*) AS c FROM sol_debug_events WHERE event_type = 'TRADE_OPEN'"
        ).fetchone()["c"]
        closes = conn.execute(
            "SELECT COUNT(*) AS c FROM sol_debug_events WHERE event_type = 'TRADE_CLOSE'"
        ).fetchone()["c"]
        evals = conn.execute(
            "SELECT COUNT(*) AS c FROM sol_debug_events WHERE event_type = 'BAR_EVAL'"
        ).fetchone()["c"]
    return {
        "max_trades": MAX_DEBUG_TRADES,
        "bar_evaluations": evals,
        "signals": signals,
        "trade_opens": entries,
        "trade_closes": closes,
        "trade_cap_reached": closes >= MAX_DEBUG_TRADES,
    }
