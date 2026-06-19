"""Tests for FastAPI endpoints."""

from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("healthy", "degraded", "fail")
    assert "market_data" in body
    assert "database" in body
    assert body["database"]["status"] in ("healthy", "fail", "degraded")


def test_debug_signals_page():
    assert client.get("/debug/signals").status_code == 200
    assert client.get("/debug/signals/data?symbol=ETH&timeframe=5m").status_code == 200


def test_health_page():
    assert client.get("/health/page").status_code == 200


def test_status_endpoint():
    response = client.get("/status")
    assert response.status_code == 200
    body = response.json()
    assert "BTC" in body["symbols"]
    assert "5m" in body["timeframes"]


def test_signals_endpoint():
    response = client.get("/live-signals")
    assert response.status_code == 200
    body = response.json()
    assert "signals" in body
    assert "count" in body


def test_dashboard_redirect():
    response = client.get("/dashboard", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"

    terminal = client.get("/")
    assert terminal.status_code == 200
    assert "Trading Terminal" in terminal.text


def test_chart_redirect():
    response = client.get("/chart", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_terminal_home():
    response = client.get("/")
    assert response.status_code == 200
    assert "TERMINAL" in response.text or "Trading Terminal" in response.text


def test_debug_raw_endpoint():
    sample_df = pd.DataFrame(
        {
            "time": [100, 200],
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.9, 1.9],
            "close": [1.2, 2.2],
            "volume": [10.0, 20.0],
        }
    )
    audit = {
        "raw_api_count": 3,
        "after_normalize_count": 2,
        "after_fetch_tail_count": 2,
        "dropna_removed": 1,
        "duplicate_removed": 0,
        "fetch_tail_removed": 0,
        "gap_count": 0,
        "flat_count": 0,
        "first_candle": {
            "time": 100,
            "open": 1.0,
            "high": 1.5,
            "low": 0.9,
            "close": 1.2,
            "volume": 10.0,
        },
        "last_candle": {
            "time": 200,
            "open": 2.0,
            "high": 2.5,
            "low": 1.9,
            "close": 2.2,
            "volume": 20.0,
        },
    }

    with patch(
        "app.api.delta_client.fetch_candles_with_audit",
        return_value=(sample_df, audit),
    ):
        response = client.get("/debug/raw/ETH?timeframe=5m")

    assert response.status_code == 200
    body = response.json()
    assert body["symbol"] == "ETHUSDT"
    assert body["raw_candle_count"] == 3
    assert body["processed_candle_count"] == 2
    assert body["first_candle"]["time"] == 100
    assert body["last_candle"]["time"] == 200
    assert body["pipeline"]["checks"]["dropna_in_normalize"] == 1


def test_debug_chart_endpoint_no_cache():
    response = client.get("/debug/chart/ETH/5m")
    assert response.status_code == 503


def test_chart_endpoint_with_cached_data():
    import pandas as pd

    from app.indicators import calculate_indicators
    from app.market_data import store

    df = pd.DataFrame(
        {
            "time": list(range(100, 100 + 50 * 300, 300)),
            "open": [2000.0] * 50,
            "high": [2010.0] * 50,
            "low": [1990.0] * 50,
            "close": [2005.0] * 50,
            "volume": [100.0] * 50,
        }
    )
    sma, hh, ll = calculate_indicators(df)
    store.update("ETHUSDT", "5m", df, sma, hh, ll, None, display_candles=df)

    response = client.get("/chart/ETH?timeframe=5m&limit=20")
    assert response.status_code == 200
    body = response.json()
    assert len(body["candles"]) == 20
    assert body["signal_context"]["timeframe"] == "5m"
    assert body["signal_context"]["candle_count"] == 20


def test_page_routes():
    for path in ("/", "/signals", "/positions", "/performance"):
        response = client.get(path)
        assert response.status_code == 200
        assert "Delta" in response.text or "DELTA" in response.text

    for path in ("/chart", "/dashboard"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    terminal = client.get("/")
    assert "chart-container" in terminal.text
    assert "chart-engine.js" in terminal.text
    assert "lightweight-charts" in terminal.text
    assert "signal-review" in terminal.text


def test_custom_404_html():
    response = client.get("/does-not-exist", headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "404" in response.text
