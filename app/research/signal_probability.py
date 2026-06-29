"""
SMA crossover signal probability analyzer — research only.

Statistical analysis of whether price reaches target or stop first after SMA crossovers.
Not a trading strategy; does not affect live or paper engines.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

import numpy as np
import pandas as pd

Direction = Literal["BUY", "SELL", "BOTH"]
ResultKind = Literal["TARGET", "STOP", "UNRESOLVED"]


@dataclass(frozen=True)
class SignalProbabilityParams:
    symbol: str = "SOLUSDT"
    timeframe: str = "5m"
    months_back: int = 6
    sma_length: int = 84
    target_points: float = 3.0
    stop_loss_points: float = 1.0
    direction: Direction = "BOTH"


def _iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _intrabar_result(
    side: str,
    open_px: float,
    high: float,
    low: float,
    target: float,
    stop: float,
) -> str | None:
    """Return TARGET, STOP, or None if neither hit on this bar."""
    if side == "BUY":
        hit_target = high >= target
        hit_stop = low <= stop
        if hit_target and hit_stop:
            return "STOP" if abs(open_px - stop) <= abs(open_px - target) else "TARGET"
        if hit_stop:
            return "STOP"
        if hit_target:
            return "TARGET"
    else:
        hit_target = low <= target
        hit_stop = high >= stop
        if hit_target and hit_stop:
            return "STOP" if abs(open_px - stop) <= abs(open_px - target) else "TARGET"
        if hit_stop:
            return "STOP"
        if hit_target:
            return "TARGET"
    return None


def _resolve_signal(
    candles: pd.DataFrame,
    entry_idx: int,
    side: str,
    entry: float,
    target_points: float,
    stop_loss_points: float,
) -> dict[str, Any]:
    if side == "BUY":
        target = entry + target_points
        stop = entry - stop_loss_points
    else:
        target = entry - target_points
        stop = entry + stop_loss_points

    highs = candles["high"].to_numpy(dtype=np.float64)
    lows = candles["low"].to_numpy(dtype=np.float64)
    opens = candles["open"].to_numpy(dtype=np.float64)
    times = candles["time"].to_numpy(dtype=np.int64)

    n = len(candles)
    for bar in range(entry_idx + 1, n):
        outcome = _intrabar_result(
            side,
            float(opens[bar]),
            float(highs[bar]),
            float(lows[bar]),
            target,
            stop,
        )
        if outcome is None:
            continue
        bars = bar - entry_idx
        exit_px = target if outcome == "TARGET" else stop
        pnl = target_points if outcome == "TARGET" else -stop_loss_points
        duration_sec = int(times[bar] - times[entry_idx])
        return {
            "exit_idx": bar,
            "exit_price": round(exit_px, 4),
            "target_price": round(target, 4),
            "stop_price": round(stop, 4),
            "bars": bars,
            "result": outcome,
            "duration_seconds": duration_sec,
            "pnl_points": round(pnl, 4),
            "exit_time": _iso_from_unix(int(times[bar])),
        }

    last = n - 1
    close = float(candles["close"].iloc[last])
    return {
        "exit_idx": last,
        "exit_price": round(close, 4),
        "target_price": round(target, 4),
        "stop_price": round(stop, 4),
        "bars": last - entry_idx,
        "result": "UNRESOLVED",
        "duration_seconds": int(times[last] - times[entry_idx]),
        "pnl_points": 0.0,
        "exit_time": _iso_from_unix(int(times[last])),
    }


def _detect_crossovers(
    close: np.ndarray,
    sma: np.ndarray,
    direction: Direction,
) -> tuple[np.ndarray, np.ndarray]:
    """Vectorized SMA crossover masks (valid where sma is finite)."""
    valid = np.isfinite(sma) & np.isfinite(close)
    prev_close = np.roll(close, 1)
    prev_sma = np.roll(sma, 1)
    valid[0] = False

    buy_mask = valid & (prev_close <= prev_sma) & (close > sma)
    sell_mask = valid & (prev_close >= prev_sma) & (close < sma)

    if direction == "BUY":
        sell_mask = np.zeros_like(sell_mask, dtype=bool)
    elif direction == "SELL":
        buy_mask = np.zeros_like(buy_mask, dtype=bool)

    return buy_mask, sell_mask


def _side_stats(signals: list[dict[str, Any]]) -> dict[str, Any]:
    if not signals:
        return {
            "total": 0,
            "target_hits": 0,
            "stop_loss": 0,
            "unresolved": 0,
            "win_rate_pct": 0.0,
            "avg_bars_to_target": 0.0,
            "avg_bars_to_stop": 0.0,
        }
    targets = [s for s in signals if s["result"] == "TARGET"]
    stops = [s for s in signals if s["result"] == "STOP"]
    resolved = targets + stops
    win_rate = round(len(targets) / len(resolved) * 100.0, 2) if resolved else 0.0
    return {
        "total": len(signals),
        "target_hits": len(targets),
        "stop_loss": len(stops),
        "unresolved": sum(1 for s in signals if s["result"] == "UNRESOLVED"),
        "win_rate_pct": win_rate,
        "avg_bars_to_target": round(
            sum(s["bars"] for s in targets) / len(targets), 2
        ) if targets else 0.0,
        "avg_bars_to_stop": round(
            sum(s["bars"] for s in stops) / len(stops), 2
        ) if stops else 0.0,
    }


def _streaks(results: list[str]) -> tuple[int, int]:
    longest_win = longest_loss = 0
    cur_win = cur_loss = 0
    for r in results:
        if r == "TARGET":
            cur_win += 1
            cur_loss = 0
        elif r == "STOP":
            cur_loss += 1
            cur_win = 0
        else:
            cur_win = cur_loss = 0
        longest_win = max(longest_win, cur_win)
        longest_loss = max(longest_loss, cur_loss)
    return longest_win, longest_loss


def _histogram(values: list[int], *, bins: int = 20) -> list[dict[str, Any]]:
    if not values:
        return []
    arr = np.array(values, dtype=np.int32)
    counts, edges = np.histogram(arr, bins=min(bins, max(len(set(values)), 1)))
    return [
        {"bin_start": int(edges[i]), "bin_end": int(edges[i + 1]), "count": int(counts[i])}
        for i in range(len(counts))
    ]


def _monthly_win_rate(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, int]] = {}
    for sig in signals:
        if sig["result"] not in ("TARGET", "STOP"):
            continue
        month = (sig.get("entry_time") or "")[:7]
        if not month:
            continue
        b = buckets.setdefault(month, {"wins": 0, "total": 0})
        b["total"] += 1
        if sig["result"] == "TARGET":
            b["wins"] += 1
    return [
        {
            "month": month,
            "win_rate_pct": round(data["wins"] / data["total"] * 100.0, 2),
            "signals": data["total"],
        }
        for month, data in sorted(buckets.items())
    ]


def analyze_signal_probability(
    candles: pd.DataFrame,
    params: SignalProbabilityParams,
) -> dict[str, Any]:
    """Run SMA crossover target/stop probability analysis."""
    if candles.empty or len(candles) < params.sma_length + 2:
        return _empty_report(params, candle_count=len(candles))

    close = candles["close"].to_numpy(dtype=np.float64)
    sma = (
        pd.Series(close)
        .rolling(window=params.sma_length, min_periods=params.sma_length)
        .mean()
        .to_numpy(dtype=np.float64)
    )
    times = candles["time"].to_numpy(dtype=np.int64)

    buy_mask, sell_mask = _detect_crossovers(close, sma, params.direction)

    signals: list[dict[str, Any]] = []
    i = params.sma_length
    n = len(candles)

    while i < n:
        side: str | None = None
        if buy_mask[i]:
            side = "BUY"
        elif sell_mask[i]:
            side = "SELL"

        if side is None:
            i += 1
            continue

        entry = float(close[i])
        entry_time = _iso_from_unix(int(times[i]))
        resolved = _resolve_signal(
            candles,
            i,
            side,
            entry,
            params.target_points,
            params.stop_loss_points,
        )
        signals.append({
            "date": entry_time[:10],
            "time": entry_time[11:19],
            "entry_time": entry_time,
            "direction": side,
            "entry": round(entry, 4),
            "exit": resolved["exit_price"],
            "target": resolved["target_price"],
            "stop": resolved["stop_price"],
            "bars": resolved["bars"],
            "result": resolved["result"],
            "duration_seconds": resolved["duration_seconds"],
            "pnl_points": resolved["pnl_points"],
            "exit_time": resolved["exit_time"],
        })
        i = int(resolved["exit_idx"]) + 1

    buy_sigs = [s for s in signals if s["direction"] == "BUY"]
    sell_sigs = [s for s in signals if s["direction"] == "SELL"]
    resolved_sigs = [s for s in signals if s["result"] in ("TARGET", "STOP")]

    wins = [s for s in resolved_sigs if s["result"] == "TARGET"]
    losses = [s for s in resolved_sigs if s["result"] == "STOP"]
    gross_win = sum(s["pnl_points"] for s in wins)
    gross_loss = abs(sum(s["pnl_points"] for s in losses))
    pf = round(gross_win / gross_loss, 4) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    overall_wr = round(len(wins) / len(resolved_sigs) * 100.0, 2) if resolved_sigs else 0.0
    ev = round(
        (overall_wr / 100.0) * params.target_points
        - (1.0 - overall_wr / 100.0) * params.stop_loss_points,
        4,
    ) if resolved_sigs else 0.0

    result_order = [s["result"] for s in signals if s["result"] in ("TARGET", "STOP")]
    longest_win, longest_loss = _streaks(result_order)

    target_bars = [s["bars"] for s in signals if s["result"] == "TARGET"]
    stop_bars = [s["bars"] for s in signals if s["result"] == "STOP"]

    scatter = [
        {
            "bars": s["bars"],
            "result": s["result"],
            "direction": s["direction"],
            "pnl_points": s["pnl_points"],
        }
        for s in resolved_sigs
    ]

    return {
        "params": {
            "symbol": params.symbol,
            "timeframe": params.timeframe,
            "months_back": params.months_back,
            "sma_length": params.sma_length,
            "target_points": params.target_points,
            "stop_loss_points": params.stop_loss_points,
            "direction": params.direction,
        },
        "meta": {
            "candle_count": len(candles),
            "signal_count": len(signals),
            "date_range": {
                "start": _iso_from_unix(int(times[0]))[:10],
                "end": _iso_from_unix(int(times[-1]))[:10],
            },
        },
        "buy": _side_stats(buy_sigs),
        "sell": _side_stats(sell_sigs),
        "combined": {
            "total_signals": len(signals),
            "resolved": len(resolved_sigs),
            "overall_win_rate_pct": overall_wr,
            "expected_value_points": ev,
            "profit_factor": pf,
            "longest_win_streak": longest_win,
            "longest_loss_streak": longest_loss,
        },
        "charts": {
            "bars_to_target_histogram": _histogram(target_bars),
            "bars_to_stop_histogram": _histogram(stop_bars),
            "monthly_win_rate": _monthly_win_rate(signals),
            "target_vs_stop_scatter": scatter,
        },
        "signals": signals,
    }


def _empty_report(params: SignalProbabilityParams, *, candle_count: int) -> dict[str, Any]:
    return {
        "params": {
            "symbol": params.symbol,
            "timeframe": params.timeframe,
            "months_back": params.months_back,
            "sma_length": params.sma_length,
            "target_points": params.target_points,
            "stop_loss_points": params.stop_loss_points,
            "direction": params.direction,
        },
        "meta": {"candle_count": candle_count, "signal_count": 0, "date_range": {}},
        "buy": _side_stats([]),
        "sell": _side_stats([]),
        "combined": {
            "total_signals": 0,
            "resolved": 0,
            "overall_win_rate_pct": 0.0,
            "expected_value_points": 0.0,
            "profit_factor": 0.0,
            "longest_win_streak": 0,
            "longest_loss_streak": 0,
        },
        "charts": {
            "bars_to_target_histogram": [],
            "bars_to_stop_histogram": [],
            "monthly_win_rate": [],
            "target_vs_stop_scatter": [],
        },
        "signals": [],
    }
