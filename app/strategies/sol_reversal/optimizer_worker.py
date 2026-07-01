"""SOL optimizer worker — thin wrapper around StrategyEngine."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.backtest.metrics import aggregate_statistics, build_equity_curve
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.strategy_engine import ExecutionConfig, StrategyEngine


def ohlc_to_arrays(df: pd.DataFrame) -> dict[str, Any]:
    return {
        "time": df["time"].astype(np.int64).tolist(),
        "open": df["open"].astype(np.float64).tolist(),
        "high": df["high"].astype(np.float64).tolist(),
        "low": df["low"].astype(np.float64).tolist(),
        "close": df["close"].astype(np.float64).tolist(),
        "volume": df.get("volume", pd.Series([0.0] * len(df))).astype(np.float64).tolist(),
    }


def arrays_to_ohlc(data: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(data)


def run_strategy_engine_iteration(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Single optimizer iteration — creates a fresh StrategyEngine with full state reset.

  This is the ONLY simulation path the optimizer may use.
    """
    base_settings = {**DEFAULT_SETTINGS, **(payload.get("base_settings") or {})}
    overrides = payload.get("param_overrides") or {}
    settings = {**base_settings, **overrides}

    initial_capital = float(payload.get("initial_capital", 1000))
    commission_pct = float(payload.get("commission_pct", 0.05))
    slippage_pct = float(payload.get("slippage_pct", 0.02))
    symbol = payload.get("symbol", "SOLUSDT")
    timeframe = payload.get("timeframe", "5m")
    settings["initial_capital"] = initial_capital

    ohlc = arrays_to_ohlc(payload["ohlc"])
    execution = ExecutionConfig(
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        symbol=symbol,
        timeframe=timeframe,
    )

    engine = StrategyEngine(settings, execution=execution, raw_ohlc=ohlc)
    engine.use_standard_execution()
    replay = engine.run()

    trades = list(replay["trades"])
    equity_curve = build_equity_curve(initial_capital, trades)
    stats = aggregate_statistics(initial_capital, float(replay["final_equity"]), trades, equity_curve)

    return {
        **overrides,
        "statistics": stats,
        "trade_count": len(trades),
        "final_equity": round(float(replay["final_equity"]), 4),
        "trades": trades,
        "score": float(stats.get("total_return_pct") or 0),
        "engine_path": "optimizer_worker",
    }


def sol_optimizer_worker(payload: dict[str, Any]) -> dict[str, Any]:
    """Process-pool entry point — must remain a thin wrapper."""
    return run_strategy_engine_iteration(payload)
