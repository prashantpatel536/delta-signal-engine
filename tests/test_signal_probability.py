"""Tests for Signal Probability Optimizer (research)."""

import numpy as np
import pandas as pd

from app.research.signal_probability import (
    SignalProbabilityParams,
    _detect_crossovers,
    _intrabar_result,
    analyze_signal_probability,
)


def _make_candles(closes: list[float], *, base_time: int = 1_700_000_000) -> pd.DataFrame:
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "time": base_time + i * 300,
            "open": c,
            "high": c + 2,
            "low": c - 2,
            "close": c,
            "volume": 100.0,
        })
    return pd.DataFrame(rows)


def test_buy_crossover_detection():
    closes = [100.0] * 90 + [99.0, 101.0, 103.0, 105.0]
    sma = pd.Series(closes).rolling(84).mean().to_numpy()
    close = np.array(closes, dtype=np.float64)
    buy_mask, _ = _detect_crossovers(close, sma, "BUY")
    assert buy_mask.sum() >= 1


def test_intrabar_target_before_stop():
    assert _intrabar_result("BUY", 100.0, 104.0, 99.5, 103.0, 98.0) == "TARGET"
    assert _intrabar_result("BUY", 100.0, 100.5, 97.0, 103.0, 98.0) == "STOP"


def test_analyze_buy_signal_resolves():
    closes = [100.0] * 99 + [98.0, 102.0]
    for i in range(10):
        closes.append(102.0 + i * 0.6)
    candles = _make_candles(closes)
    candles["high"] = candles["close"] + 2
    candles["low"] = candles["close"] - 1

    params = SignalProbabilityParams(
        sma_length=84,
        target_points=3.0,
        stop_loss_points=1.0,
        direction="BUY",
    )
    report = analyze_signal_probability(candles, params)
    assert report["buy"]["total"] >= 1
    assert report["signals"]


def test_synthetic_analysis_metrics():
    n = 200
    rng = np.random.default_rng(42)
    closes = 100 + np.cumsum(rng.normal(0, 0.5, n))
    candles = _make_candles(closes.tolist())
    candles["high"] = candles["close"] + 2
    candles["low"] = candles["close"] - 2

    report = analyze_signal_probability(
        candles,
        SignalProbabilityParams(sma_length=20, months_back=1, direction="BOTH"),
    )
    assert "combined" in report
    assert "charts" in report
    assert report["meta"]["candle_count"] == n


def test_signal_probability_api():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.research_signal_probability_api import router

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Use mocked small analysis path - API will try real fetch; skip if no network
    # Test validation only with bad symbol
    resp = client.post(
        "/research/signal-probability/analyze",
        json={
            "symbol": "INVALID",
            "timeframe": "5m",
            "months_back": 1,
            "sma_length": 84,
            "target_points": 3.0,
            "stop_loss_points": 1.0,
            "direction": "BOTH",
        },
    )
    assert resp.status_code == 400
