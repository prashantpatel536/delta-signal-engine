"""Tests for unified StrategyEngine, optimizer parity, and validation mode."""

from __future__ import annotations

import pandas as pd

from app.strategies.sol_reversal.engine_validation import (
    compare_engine_results,
    validate_engine_parity,
)
from app.strategies.sol_reversal.ha import to_heikin_ashi
from app.strategies.sol_reversal.optimizer_param_grid import analyze_sol_param_grid
from app.strategies.sol_reversal.optimizer_worker import (
    arrays_to_ohlc,
    ohlc_to_arrays,
    run_strategy_engine_iteration,
)
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.strategy_engine import ExecutionConfig, StrategyEngine


def _sample_ohlc(n: int = 40) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        if i < 10:
            o, c = price, price - 0.3
        elif i == 10:
            o, c = price, price + 1.2
        else:
            o, c = price, price + 0.05
        price = c
        rows.append({
            "time": 1_700_000_000 + i * 300,
            "open": o,
            "high": max(o, c) + 0.2,
            "low": min(o, c) - 0.2,
            "close": c,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def _settings() -> dict:
    return {
        **DEFAULT_SETTINGS,
        "min_red_candles": 3,
        "atr_filter_enabled": False,
        "strong_candle_enabled": False,
        "lock_profit_enabled": False,
        "process_orders_on_close": False,
    }


def test_strategy_engine_reset_clears_state():
    ohlc = _sample_ohlc()
    settings_a = {**_settings(), "stop_loss_pct": 5.0}
    settings_b = {**_settings(), "stop_loss_pct": 25.0}
    engine = StrategyEngine(settings_a, execution=ExecutionConfig(), raw_ohlc=ohlc)
    engine.use_standard_execution()
    r1 = engine.run()
    assert r1["trade_count"] >= 0

    engine.reset(settings_b)
    assert engine.position is None
    assert engine.pending_signal is False
    assert engine.trades == []
    assert engine.trade_num == 0
    assert engine.equity == engine.execution.initial_capital
    r2 = engine.run(reset=False)
    assert r2["trade_count"] >= 0


def test_optimizer_worker_matches_direct_engine():
    ohlc = _sample_ohlc()
    ha = to_heikin_ashi(ohlc)
    settings = _settings()
    execution = ExecutionConfig(initial_capital=1000)

    direct = StrategyEngine(settings, execution=execution, raw_ohlc=ohlc)
    direct.use_standard_execution()
    direct_result = direct.run()

    payload = {
        "ohlc": ohlc_to_arrays(ohlc),
        "base_settings": DEFAULT_SETTINGS,
        "param_overrides": {
            k: settings[k]
            for k in (
                "min_red_candles", "atr_filter_enabled", "strong_candle_enabled",
                "lock_profit_enabled", "process_orders_on_close", "stop_loss_pct",
                "take_profit_pct", "leverage", "position_size_pct",
            )
        },
        "initial_capital": 1000,
        "commission_pct": 0.05,
        "slippage_pct": 0.02,
        "symbol": "SOLUSDT",
        "timeframe": "5m",
    }
    opt_result = run_strategy_engine_iteration(payload)

    comparison = compare_engine_results(
        {
            "engine_path": "paper_strategy_engine",
            "trade_count": direct_result["trade_count"],
            "final_equity": round(direct_result["final_equity"], 4),
            "statistics": direct_result.get("statistics") or {},
            "trades": direct_result["trades"],
        },
        {
            "engine_path": "optimizer_worker",
            "trade_count": opt_result["trade_count"],
            "final_equity": opt_result["final_equity"],
            "statistics": opt_result["statistics"],
            "trades": opt_result["trades"],
        },
    )
    assert comparison["ok"], comparison["report"]


def test_param_grid_counts():
    plan = analyze_sol_param_grid({
        "ranges": {
            "stop_loss_pct": {"start": 1, "end": 3, "step": 1},
            "lock_trigger_pct": {"start": 2, "end": 4, "step": 1},
        },
    })
    assert plan["expected_combinations"] == 9
    assert len(plan["combinations"]) == 9


def test_each_optimizer_iteration_fresh_engine():
    ohlc = _sample_ohlc()
    arrays = ohlc_to_arrays(ohlc)
    base = {
        "ohlc": arrays,
        "base_settings": DEFAULT_SETTINGS,
        "initial_capital": 1000,
        "commission_pct": 0.05,
        "slippage_pct": 0.02,
        "symbol": "SOLUSDT",
        "timeframe": "5m",
    }
    r1 = run_strategy_engine_iteration({**base, "param_overrides": {"stop_loss_pct": 1.0}})
    r2 = run_strategy_engine_iteration({**base, "param_overrides": {"stop_loss_pct": 25.0}})
    assert r1["stop_loss_pct"] == 1.0
    assert r2["stop_loss_pct"] == 25.0
    # Different SL should not inherit trade state — trade counts may differ
    assert "trade_count" in r1 and "trade_count" in r2
