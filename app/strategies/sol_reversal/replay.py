"""Chart markers from strategy replay — TV-style entries/exits only when flat."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.strategies.sol_reversal.indicators import compute_atr
from app.strategies.sol_reversal.simulation import replay_strategy


def replay_markers(
    candles: pd.DataFrame,
    settings: dict[str, Any],
    *,
    atr: pd.Series | None = None,
    initial_equity: float = 100_000.0,
) -> dict[str, Any]:
    """Returns TV-style entry/exit markers plus raw condition hits for comparison."""
    if atr is None and not candles.empty:
        atr = compute_atr(candles, int(settings.get("atr_period", 14)))
    return replay_strategy(
        candles,
        settings,
        atr=atr,
        initial_equity=initial_equity,
    )


def markers_for_chart(replay: dict[str, Any]) -> list[dict[str, Any]]:
    """One BUY entry marker per trade + exit markers (no raw conditions)."""
    out: list[dict[str, Any]] = []
    for e in replay.get("entries", []):
        out.append({
            "candle_time": e["candle_time"],
            "signal": "BUY",
            "status": "ENTRY",
        })
    for x in replay.get("exits", []):
        out.append({
            "candle_time": x["candle_time"],
            "signal": "BUY",
            "status": x["status"],
        })
    return out


def raw_condition_markers(
    raw: list[dict[str, Any]],
    *,
    entry_times: set[int] | None = None,
) -> list[dict[str, Any]]:
    """Optional debug markers — suppressed at bars that already have an entry."""
    taken = entry_times or set()
    out: list[dict[str, Any]] = []
    for s in raw:
        t = int(s["time"])
        if t in taken:
            continue
        out.append({
            "candle_time": t,
            "signal": "BUY",
            "status": "HA_CONDITION",
        })
    return out
