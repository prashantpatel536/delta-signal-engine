"""Tests for SMA Signal Optimizer (research)."""

import numpy as np
import pandas as pd

from app.research.sma_crossover_sim import (
    aggregate_trade_stats,
    intrabar_outcome,
    simulate_sma_combo,
)
from app.research.sma_optimizer_grid import build_sma_grid


def _candles(closes: list[float]) -> pd.DataFrame:
    t0 = 1_700_000_000
    return pd.DataFrame({
        "time": [t0 + i * 300 for i in range(len(closes))],
        "open": closes,
        "high": [c + 2 for c in closes],
        "low": [c - 2 for c in closes],
        "close": closes,
        "volume": [100.0] * len(closes),
    })


def test_grid_combination_count():
    plan = build_sma_grid({
        "sma_start": 20,
        "sma_end": 24,
        "sma_step": 2,
        "stop_start": 0.5,
        "stop_end": 1.0,
        "stop_step": 0.5,
        "target_start": 1.0,
        "target_end": 2.0,
        "target_step": 0.5,
    })
    assert plan["expected_combinations"] == 3 * 2 * 3
    assert len(plan["combinations"]) == 18


def test_intrabar_stop_first():
    assert intrabar_outcome("BUY", 100, 103, 98, 102, 99, ambiguous="STOP_FIRST") == "LOSS"
    assert intrabar_outcome("BUY", 100, 103, 98, 102, 99, ambiguous="TARGET_FIRST") == "WIN"
    assert intrabar_outcome("BUY", 100, 103, 98, 102, 99, ambiguous="IGNORE") == "AMBIGUOUS"


def test_simulate_produces_stats():
    n = 150
    rng = np.random.default_rng(1)
    closes = (100 + np.cumsum(rng.normal(0, 0.4, n))).tolist()
    candles = _candles(closes)
    trades = simulate_sma_combo(candles, sma_length=20, stop_points=1.0, target_points=3.0)
    stats = aggregate_trade_stats(trades)
    assert "win_rate" in stats
    assert stats["total_trades"] == len(trades)


def test_sma_optimizer_preview_api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research_sma_optimizer_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post(
        "/research/sma-optimizer/preview",
        json={
            "symbol": "SOLUSDT",
            "sma": {"start": 20, "end": 22, "step": 2},
            "stop": {"start": 0.5, "end": 1.0, "step": 0.5},
            "target": {"start": 1.0, "end": 2.0, "step": 1.0},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["final_combinations"] == 2 * 2 * 2
