"""
SMA crossover trade simulation — research only.

Shared core for signal probability and SMA optimizer tools.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
import pandas as pd

AmbiguousRule = Literal["STOP_FIRST", "TARGET_FIRST", "IGNORE"]


def iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def compute_sma(close: np.ndarray, length: int) -> np.ndarray:
    return (
        pd.Series(close)
        .rolling(window=length, min_periods=length)
        .mean()
        .to_numpy(dtype=np.float64)
    )


def crossover_masks(close: np.ndarray, sma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    valid = np.isfinite(sma) & np.isfinite(close)
    prev_close = np.roll(close, 1)
    prev_sma = np.roll(sma, 1)
    valid[0] = False
    buy = valid & (prev_close <= prev_sma) & (close > sma)
    sell = valid & (prev_close >= prev_sma) & (close < sma)
    return buy, sell


def intrabar_outcome(
    side: str,
    open_px: float,
    high: float,
    low: float,
    target: float,
    stop: float,
    *,
    ambiguous: AmbiguousRule = "STOP_FIRST",
) -> str | None:
    """Return WIN (target), LOSS (stop), AMBIGUOUS, or None."""
    if side == "BUY":
        hit_target = high >= target
        hit_stop = low <= stop
    else:
        hit_target = low <= target
        hit_stop = high >= stop

    if hit_target and hit_stop:
        if ambiguous == "IGNORE":
            return "AMBIGUOUS"
        if ambiguous == "TARGET_FIRST":
            return "WIN"
        return "LOSS"
    if hit_stop:
        return "LOSS"
    if hit_target:
        return "WIN"
    return None


def resolve_trade(
    *,
    highs: np.ndarray,
    lows: np.ndarray,
    opens: np.ndarray,
    times: np.ndarray,
    entry_idx: int,
    side: str,
    entry: float,
    target_points: float,
    stop_points: float,
    ambiguous: AmbiguousRule,
) -> dict[str, Any] | None:
    if side == "BUY":
        target = entry + target_points
        stop = entry - stop_points
    else:
        target = entry - target_points
        stop = entry + stop_points

    n = len(highs)
    for bar in range(entry_idx + 1, n):
        outcome = intrabar_outcome(
            side,
            float(opens[bar]),
            float(highs[bar]),
            float(lows[bar]),
            target,
            stop,
            ambiguous=ambiguous,
        )
        if outcome == "AMBIGUOUS":
            return None
        if outcome is None:
            continue
        bars = bar - entry_idx
        win = outcome == "WIN"
        exit_px = target if win else stop
        pnl = target_points if win else -stop_points
        return {
            "exit_idx": bar,
            "entry_time": iso_from_unix(int(times[entry_idx])),
            "exit_time": iso_from_unix(int(times[bar])),
            "direction": side,
            "entry": round(entry, 4),
            "exit_price": round(exit_px, 4),
            "target": round(target, 4),
            "stop": round(stop, 4),
            "bars": bars,
            "result": "WIN" if win else "LOSS",
            "duration_seconds": int(times[bar] - times[entry_idx]),
            "pnl_points": round(pnl, 4),
        }

    return None


def simulate_sma_combo(
    candles: pd.DataFrame,
    *,
    sma_length: int,
    stop_points: float,
    target_points: float,
    ambiguous: AmbiguousRule = "STOP_FIRST",
    sma: np.ndarray | None = None,
) -> list[dict[str, Any]]:
    """Simulate all BUY/SELL SMA crossover trades for one parameter set."""
    if candles.empty or len(candles) < sma_length + 2:
        return []

    close = candles["close"].to_numpy(dtype=np.float64)
    highs = candles["high"].to_numpy(dtype=np.float64)
    lows = candles["low"].to_numpy(dtype=np.float64)
    opens = candles["open"].to_numpy(dtype=np.float64)
    times = candles["time"].to_numpy(dtype=np.int64)

    if sma is None:
        sma = compute_sma(close, sma_length)

    buy_mask, sell_mask = crossover_masks(close, sma)
    trades: list[dict[str, Any]] = []
    n = len(close)
    i = sma_length
    buy_allowed = sma_length
    sell_allowed = sma_length

    while i < n:
        side: str | None = None
        if buy_mask[i] and i >= buy_allowed:
            side = "BUY"
        elif sell_mask[i] and i >= sell_allowed:
            side = "SELL"

        if side is None:
            i += 1
            continue

        entry = float(close[i])
        resolved = resolve_trade(
            highs=highs,
            lows=lows,
            opens=opens,
            times=times,
            entry_idx=i,
            side=side,
            entry=entry,
            target_points=target_points,
            stop_points=stop_points,
            ambiguous=ambiguous,
        )

        if resolved is None:
            if ambiguous == "IGNORE":
                i += 1
                continue
            i += 1
            continue

        trades.append(resolved)
        next_i = int(resolved["exit_idx"]) + 1
        if side == "BUY":
            buy_allowed = next_i
        else:
            sell_allowed = next_i
        i = next_i

    return trades


def aggregate_trade_stats(trades: list[dict[str, Any]]) -> dict[str, Any]:
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "avg_bars_to_target": 0.0,
            "avg_bars_to_stop": 0.0,
            "profit_factor": 0.0,
            "expected_value": 0.0,
            "net_points": 0.0,
            "total_profit": 0.0,
            "max_drawdown_points": 0.0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
            "largest_win": 0.0,
            "largest_loss": 0.0,
            "avg_duration_seconds": 0.0,
        }

    wins = [t for t in trades if t["result"] == "WIN"]
    losses = [t for t in trades if t["result"] == "LOSS"]
    pnls = [t["pnl_points"] for t in trades]
    gross_win = sum(t["pnl_points"] for t in wins)
    gross_loss = abs(sum(t["pnl_points"] for t in losses))
    pf = round(gross_win / gross_loss, 4) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    wr = round(len(wins) / len(trades) * 100.0, 2)

    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    max_w = max_l = cur_w = cur_l = 0
    for t in trades:
        if t["result"] == "WIN":
            cur_w += 1
            cur_l = 0
        else:
            cur_l += 1
            cur_w = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)

    net = round(sum(pnls), 4)
    ev = round(net / len(trades), 4)

    return {
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": wr,
        "avg_win": round(gross_win / len(wins), 4) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 4) if losses else 0.0,
        "avg_bars_to_target": round(sum(t["bars"] for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_bars_to_stop": round(sum(t["bars"] for t in losses) / len(losses), 2) if losses else 0.0,
        "profit_factor": pf,
        "expected_value": ev,
        "net_points": net,
        "total_profit": net,
        "max_drawdown_points": round(max_dd, 4),
        "max_consecutive_wins": max_w,
        "max_consecutive_losses": max_l,
        "largest_win": round(max((t["pnl_points"] for t in wins), default=0.0), 4),
        "largest_loss": round(min((t["pnl_points"] for t in losses), default=0.0), 4),
        "avg_duration_seconds": round(sum(t["duration_seconds"] for t in trades) / len(trades), 0),
    }


def custom_score(metrics: dict[str, Any]) -> float:
    """Configurable ranking score for SMA optimizer."""
    if metrics.get("total_trades", 0) < 10:
        return -999999.0
    pf = float(metrics.get("profit_factor") or 0)
    ev = float(metrics.get("expected_value") or 0)
    wr = float(metrics.get("win_rate") or 0)
    dd = max(float(metrics.get("max_drawdown_points") or 0), 0.01)
    return round((pf * 100 + ev * 50 + wr) / dd, 4)
