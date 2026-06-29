"""SMA Signal Optimizer backtest worker (research only)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.research.sma_crossover_sim import (
    aggregate_trade_stats,
    compute_sma,
    custom_score,
    simulate_sma_combo,
)


def candles_to_arrays(candles: pd.DataFrame) -> dict[str, Any]:
    return {
        "time": candles["time"].astype(np.int64).tolist(),
        "open": candles["open"].astype(np.float64).tolist(),
        "high": candles["high"].astype(np.float64).tolist(),
        "low": candles["low"].astype(np.float64).tolist(),
        "close": candles["close"].astype(np.float64).tolist(),
    }


def arrays_to_candles(data: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(data)


def sma_optimizer_worker(payload: dict[str, Any]) -> dict[str, Any]:
    candles = arrays_to_candles(payload["candles"])
    sma_length = int(payload["sma_length"])
    stop_points = float(payload["stop_points"])
    target_points = float(payload["target_points"])
    ambiguous = payload.get("ambiguous", "STOP_FIRST")

    sma_arr = None
    precomputed = payload.get("sma_cache") or {}
    if str(sma_length) in precomputed:
        sma_arr = np.array(precomputed[str(sma_length)], dtype=np.float64)

    trades = simulate_sma_combo(
        candles,
        sma_length=sma_length,
        stop_points=stop_points,
        target_points=target_points,
        ambiguous=ambiguous,
        sma=sma_arr,
    )
    metrics = aggregate_trade_stats(trades)
    row = {
        "sma_length": sma_length,
        "stop_points": stop_points,
        "target_points": target_points,
        **metrics,
    }
    row["score"] = custom_score(metrics)
    row["trades"] = trades
    return row
