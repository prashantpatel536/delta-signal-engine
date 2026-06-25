"""Tests for BTC strategy optimizer (research)."""

import pandas as pd

from app.research.btc_backtest_engine import BtcBacktestParams, run_btc_backtest
from app.research.btc_optimizer_service import build_param_combinations
from app.research.scoring import overall_score


def _synthetic_btc_candles(n: int = 200, base: float = 60000.0) -> pd.DataFrame:
    rows = []
    t = 1_700_000_000
    price = base
    for i in range(n):
        drift = (i % 17 - 8) * 25
        o = price
        c = price + drift
        h = max(o, c) + 40
        l = min(o, c) - 40
        rows.append({
            "time": t + i * 300,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 100.0 + i,
        })
        price = c
    return pd.DataFrame(rows)


def test_build_param_combinations():
    combos = build_param_combinations({
        "gap_start": 0.8,
        "gap_end": 1.0,
        "gap_step": 0.1,
        "min_sl_start": 300,
        "min_sl_end": 400,
        "min_sl_step": 100,
        "max_sl_start": 600,
        "max_sl_end": 700,
        "max_sl_step": 100,
    })
    assert len(combos) == 3 * 2 * 2  # 12
    assert all(c["min_sl_points"] <= c["max_sl_points"] for c in combos)


def test_overall_score_formula():
    score = overall_score({
        "profit_factor": 2.0,
        "return_pct": 10.0,
        "max_drawdown_pct": 5.0,
    })
    assert score == 2.0 * 100 + 10.0 - 5.0 * 5


def test_run_btc_backtest_returns_metrics():
    candles = _synthetic_btc_candles(250)
    params = BtcBacktestParams(
        gap_filter_pct=0.1,
        min_sl_points=100.0,
        max_sl_points=2000.0,
        initial_capital=1000.0,
    )
    result = run_btc_backtest(candles, params)
    assert "trade_count" in result.metrics
    assert "profit_factor" in result.metrics
    assert result.metrics["trade_count"] == len(result.trades)


def test_optimizer_api_start_validation():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research_optimizer_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post(
        "/research/btc-optimizer/start",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "gap": {"start": 0.8, "end": 0.9, "step": 0.1},
            "min_sl": {"start": 300, "end": 300, "step": 100},
            "max_sl": {"start": 600, "end": 600, "step": 100},
            "initial_capital": 1000,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "job_id" in body
    assert body["total_combinations"] >= 1
