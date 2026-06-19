"""Tests for indicator calculations."""

import pandas as pd

from app.indicators import calculate_hh50, calculate_ll50, calculate_sma84


def _make_candles(count: int) -> pd.DataFrame:
    rows = []
    for i in range(count):
        price = 100 + i
        rows.append(
            {
                "time": 1_700_000_000 + i * 300,
                "open": price,
                "high": price + 2,
                "low": price - 2,
                "close": price + 1,
                "volume": 1000,
            }
        )
    return pd.DataFrame(rows)


def test_hh50_uses_previous_fifty_completed_candles_only():
    candles = _make_candles(60)
    candles.loc[59, "high"] = 9999

    hh50 = calculate_hh50(candles["high"])
    expected = candles["high"].iloc[9:59].max()
    assert hh50.iloc[59] == expected
    assert hh50.iloc[59] != 9999


def test_ll50_uses_previous_fifty_completed_candles_only():
    candles = _make_candles(60)
    candles.loc[59, "low"] = 1

    ll50 = calculate_ll50(candles["low"])
    expected = candles["low"].iloc[9:59].min()
    assert ll50.iloc[59] == expected
    assert ll50.iloc[59] != 1


def test_sma84_requires_eighty_four_closes():
    candles = _make_candles(100)
    sma84 = calculate_sma84(candles["close"])

    assert pd.isna(sma84.iloc[82])
    assert pd.notna(sma84.iloc[83])
    assert sma84.iloc[83] == candles["close"].iloc[:84].mean()
