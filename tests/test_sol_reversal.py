"""Tests for SOL Reversal Engine (isolated strategy)."""

import pandas as pd

from app.strategies.sol_reversal.ha import to_heikin_ashi
from app.strategies.sol_reversal.strategy import detect_signal_at_index, levels_for_side


def _ha_df(n: int = 30) -> pd.DataFrame:
    rows = []
    for i in range(n):
        c = 100 + i * 0.1
        rows.append({"time": i, "open": c, "high": c + 1, "low": c - 1, "close": c, "volume": 1})
    ohlc = pd.DataFrame(rows)
    return to_heikin_ashi(ohlc)


def test_heikin_ashi_colors():
    ha = _ha_df(10)
    assert "color" in ha.columns
    assert ha["color"].isin(["green", "red", "doji"]).all()


def test_levels_for_buy():
    tp, sl = levels_for_side("BUY", 100.0, {"take_profit_pct": 7.0, "stop_loss_pct": 1.0})
    assert tp == 107.0
    assert sl == 99.0


def test_sol_api_status_route():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.strategies.sol_reversal.api import router
    from app.strategies.sol_reversal.db import init_sol_db

    init_sol_db()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    resp = client.get("/sol/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["engine"]["mode"] == "PAPER"
    assert "settings" in body


def test_strategy_selector_route():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Strategy Selection" in resp.text or "Select Strategy" in resp.text
