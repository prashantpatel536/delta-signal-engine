"""Tests for historical signal detection."""

import pandas as pd

from app.indicators import calculate_hh50, calculate_ll50, calculate_sma84
from app.signals import _append_if_alternating, detect_all_signals, detect_signal


def _frame(closes: list[float], highs: list[float] | None = None, lows: list[float] | None = None) -> pd.DataFrame:
    highs = highs or [c + 1 for c in closes]
    lows = lows or [c - 1 for c in closes]
    return pd.DataFrame(
        {
            "time": [1_700_000_000 + i * 300 for i in range(len(closes))],
            "open": closes,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": [1000] * len(closes),
        }
    )


def test_detect_all_signals_includes_candle_time():
    count = 120
    closes = [100.0] * count
    closes[-2] = 100.0
    closes[-1] = 130.0

    highs = [100.0] * count
    highs[-51:-1] = [110.0] * 50
    highs[-1] = 130.0

    candles = _frame(closes, highs=highs)
    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    signals = detect_all_signals(candles, sma84, hh50, ll50, "ETHUSDT", "5m")

    assert len(signals) >= 1
    assert signals[-1]["signal"] == "BUY"
    assert all("candle_time" in s for s in signals)


def test_buy_signal_on_cross_above_hh50_and_above_sma84():
    count = 121
    closes = [100.0] * count
    closes[-3] = 100.0
    closes[-2] = 130.0
    closes[-1] = 131.0

    highs = [100.0] * count
    highs[-52:-2] = [110.0] * 50
    highs[-2] = 130.0
    highs[-1] = 131.0

    candles = _frame(closes, highs=highs)
    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    signal = detect_signal(candles, sma84, hh50, ll50, "ETHUSDT", "5m")
    assert signal is not None
    assert signal["signal"] == "BUY"
    assert signal["price"] == 130.0
    assert signal["candle_time"] == int(candles["time"].iloc[-2])


def test_sell_signal_on_cross_below_ll50_and_below_sma84():
    count = 121
    closes = [100.0] * count
    closes[-3] = 100.0
    closes[-2] = 70.0
    closes[-1] = 69.0

    lows = [100.0] * count
    lows[-52:-2] = [90.0] * 50
    lows[-2] = 70.0
    lows[-1] = 69.0

    candles = _frame(closes, lows=lows)
    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    signal = detect_signal(candles, sma84, hh50, ll50, "ETHUSDT", "5m")
    assert signal is not None
    assert signal["signal"] == "SELL"
    assert signal["price"] == 70.0
    assert signal["candle_time"] == int(candles["time"].iloc[-2])


def test_no_signal_on_forming_bar_only():
    count = 121
    closes = [100.0] * count
    closes[-2] = 100.0
    closes[-1] = 130.0

    highs = [100.0] * count
    highs[-52:-2] = [110.0] * 50
    highs[-2] = 100.0
    highs[-1] = 130.0

    candles = _frame(closes, highs=highs)
    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    signal = detect_signal(candles, sma84, hh50, ll50, "ETHUSDT", "5m")
    assert signal is None


def test_no_signal_without_cross():
    count = 120
    closes = [float(i) for i in range(count)]
    candles = _frame(closes)
    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    signal = detect_signal(candles, sma84, hh50, ll50, "ETHUSDT", "5m")
    assert signal is None


def test_alternating_signals_no_repeat_until_opposite():
    """Same-side signals are suppressed until the opposite side fires."""
    signals: list = []
    last_type = None
    buy = {"signal": "BUY", "candle_time": 1}
    sell = {"signal": "SELL", "candle_time": 2}

    last_type = _append_if_alternating(signals, buy, last_type)
    last_type = _append_if_alternating(signals, buy, last_type)
    last_type = _append_if_alternating(signals, buy, last_type)
    assert len(signals) == 1
    assert signals[0]["signal"] == "BUY"

    last_type = _append_if_alternating(signals, sell, last_type)
    last_type = _append_if_alternating(signals, sell, last_type)
    assert len(signals) == 2
    assert signals[1]["signal"] == "SELL"

    last_type = _append_if_alternating(signals, buy, last_type)
    assert len(signals) == 3
    assert signals[2]["signal"] == "BUY"

    for i in range(1, len(signals)):
        assert signals[i]["signal"] != signals[i - 1]["signal"]
