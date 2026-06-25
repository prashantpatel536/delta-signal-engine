"""Tests for BTC strategy optimizer (research)."""

import pandas as pd

from app.research.btc_backtest_engine import BtcBacktestParams, run_btc_backtest
from app.research.btc_optimizer_service import build_param_combinations
from app.research.param_grid import analyze_param_grid
from app.research.scoring import is_rankable, overall_score, rank_disqualify_reason


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


def test_param_grid_expected_vs_final():
    plan = analyze_param_grid({
        "gap_start": 0.8,
        "gap_end": 1.0,
        "gap_step": 0.1,
        "min_sl_start": 300,
        "min_sl_end": 500,
        "min_sl_step": 100,
        "max_sl_start": 400,
        "max_sl_end": 600,
        "max_sl_step": 100,
    })
    assert plan["expected_combinations"] == 3 * 3 * 3
    assert plan["skipped_combinations"] > 0
    assert plan["expected_combinations"] == plan["skipped_combinations"] + plan["final_tested_combinations"]
    assert "MinSL > MaxSL" in plan["skip_reasons"]


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
    assert len(combos) == 3 * 2 * 2
    assert all(c["min_sl_points"] <= c["max_sl_points"] for c in combos)


def test_overall_score_formula():
    low = overall_score({"trade_count": 10, "profit_factor": 2.0, "return_pct": 10.0, "win_rate": 50.0, "max_drawdown_pct": 5.0})
    assert low == -999999

    score = overall_score({
        "trade_count": 25,
        "profit_factor": 2.0,
        "return_pct": 10.0,
        "win_rate": 50.0,
        "max_drawdown_pct": 5.0,
    })
    expected = (2.0 * 100 + 10.0 * 2 + 50.0) / (5.0 * 5)
    assert score == round(expected, 4)


def test_rankable_filters():
    bad = {"trade_count": 10, "profit_factor": 2.0, "return_pct": 5.0, "win_rate": 40.0}
    assert not is_rankable(bad)
    assert rank_disqualify_reason(bad) == "Trades < 20"

    good = {"trade_count": 25, "profit_factor": 1.5, "return_pct": 5.0, "win_rate": 40.0}
    assert is_rankable(good)


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
    assert "longest_winning_streak" in result.metrics
    assert "equity_curve" in result.metrics
    assert result.metrics["trade_count"] == len(result.trades)


def test_optimizer_preview_api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research_optimizer_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.post(
        "/research/btc-optimizer/preview",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "gap": {"start": 0.8, "end": 0.9, "step": 0.1},
            "min_sl": {"start": 300, "end": 500, "step": 100},
            "max_sl": {"start": 400, "end": 600, "step": 100},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["expected_combinations"] == 2 * 3 * 3
    assert body["final_tested_combinations"] < body["expected_combinations"]


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
    assert "grid_plan" in body
    assert body["grid_plan"]["expected_combinations"] >= body["total_combinations"]
