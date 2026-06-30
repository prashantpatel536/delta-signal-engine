"""Backtest module tests."""

from app.backtest.db import init_backtest_db
from app.backtest.metrics import aggregate_statistics, build_equity_curve, build_performance_insights
from app.backtest.registry import ensure_registry, get, list_strategies
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.simulation import open_position, process_bar
from app.strategies.sol_reversal.strategy import levels_for_side


def test_levels_price_based_not_roe():
    tp, sl = levels_for_side("BUY", 100.0, {"take_profit_pct": 7.0, "stop_loss_pct": 1.0})
    assert tp == 107.0
    assert sl == 99.0


def test_process_bar_hits_take_profit():
    settings = {**DEFAULT_SETTINGS, "lock_profit_enabled": False}
    pos = open_position("BUY", 100.0, 1000, settings, 1000.0)
    assert pos is not None
    _, closed = process_bar(
        pos, bar_time=2000, high=108.0, low=99.5, close=107.0, settings=settings
    )
    assert closed is not None
    assert closed["exit_reason"] == "TP"
    assert closed["exit_price"] == 107.0


def test_aggregate_statistics_basic():
    trades = [
        {"pnl_usd": 50, "exit_time": 1000, "bars_held": 3},
        {"pnl_usd": -20, "exit_time": 2000, "bars_held": 2},
    ]
    curve = build_equity_curve(1000, trades)
    stats = aggregate_statistics(1000, 1030, trades, curve)
    assert stats["total_trades"] == 2
    assert stats["net_profit"] == 30.0


def test_registry_has_strategies():
    ensure_registry()
    ids = {s["id"] for s in list_strategies()}
    assert "sol_reversal" in ids
    assert "btc_trend" in ids
    assert get("sol_reversal").display_name


def test_build_performance_insights():
    trades = [
        {"pnl_usd": 50, "exit_time": 1000, "bars_held": 3},
        {"pnl_usd": -20, "exit_time": 2000, "bars_held": 2},
    ]
    curve = build_equity_curve(1000, trades)
    perf = build_performance_insights(1000, trades, curve)
    assert "trade_distribution" in perf
    assert "holding_time_distribution" in perf


def test_backtest_api_routes():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.backtest.api import router

    init_backtest_db()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/backtest/api/strategies")
    assert resp.status_code == 200
    assert len(resp.json()["strategies"]) >= 2
