"""Tests for candle normalization."""

import pandas as pd

from app.candle_utils import (
    enrich_flat_candles_with_mark,
    merge_mark_ohlc_with_trade_volume,
    normalize_candles,
    validate_candle_series,
)


def test_normalize_sorts_ascending_and_dedupes():
    df = pd.DataFrame(
        [
            {"time": 300, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": 100, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": 200, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": 200, "open": 99, "high": 101, "low": 98, "close": 100, "volume": 2},
        ]
    )

    normalized = normalize_candles(df, "1m")
    times = normalized["time"].tolist()

    assert times == [100, 200, 300]
    assert normalized.iloc[1]["open"] == 99


def test_normalize_tracks_drop_stats():
    df = pd.DataFrame(
        [
            {"time": 100, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": None, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": 200, "open": 10, "high": 12, "low": 9, "close": 11, "volume": 1},
            {"time": 200, "open": 99, "high": 101, "low": 98, "close": 100, "volume": 2},
        ]
    )

    stats: dict = {}
    normalized = normalize_candles(df, "1m", stats=stats)

    assert len(normalized) == 2
    assert stats["dropna_removed"] == 1
    assert stats["duplicate_removed"] == 1
    assert stats["after_normalize_count"] == 2


def test_validate_candle_series_detects_gaps():
    df = pd.DataFrame(
        {
            "time": [0, 60, 180],
            "open": [1, 1, 1],
            "high": [2, 2, 2],
            "low": [0.5, 0.5, 0.5],
            "close": [1.5, 1.5, 1.5],
            "volume": [1, 1, 1],
        }
    )

    audit = validate_candle_series(df, "1m")
    assert audit["count"] == 3
    assert audit["gap_count"] == 1
    assert audit["strictly_increasing"] is True


def test_enrich_flat_candles_with_mark():
    trade = pd.DataFrame(
        {
            "time": [100, 200],
            "open": [10.0, 50.0],
            "high": [10.0, 55.0],
            "low": [10.0, 48.0],
            "close": [10.0, 52.0],
            "volume": [1.0, 2.0],
        }
    )
    mark = pd.DataFrame(
        {
            "time": [100, 200],
            "open": [9.5, 51.0],
            "high": [10.5, 56.0],
            "low": [9.0, 47.0],
            "close": [10.2, 53.0],
            "volume": [None, None],
        }
    )

    stats: dict = {}
    enriched = enrich_flat_candles_with_mark(trade, mark, stats=stats)

    assert stats["flat_before"] == 1
    assert stats["enriched_from_mark"] == 1
    assert stats["flat_after"] == 0
    assert enriched.iloc[0]["close"] == 10.0
    assert enriched.iloc[0]["high"] > enriched.iloc[0]["low"]
    assert enriched.iloc[1]["close"] == 52.0
    assert enriched.iloc[1]["high"] == 55.0


def test_merge_mark_ohlc_with_trade_volume():
    trade = pd.DataFrame(
        {
            "time": [100, 200],
            "open": [10.0, 10.0],
            "high": [10.0, 10.0],
            "low": [10.0, 10.0],
            "close": [10.0, 10.0],
            "volume": [5.0, 7.0],
        }
    )
    mark = pd.DataFrame(
        {
            "time": [100, 200],
            "open": [9.8, 10.2],
            "high": [10.5, 10.8],
            "low": [9.5, 9.9],
            "close": [10.1, 10.4],
            "volume": [0.0, 0.0],
        }
    )

    merged = merge_mark_ohlc_with_trade_volume(trade, mark)
    assert merged.iloc[0]["high"] == 10.5
    assert merged.iloc[0]["low"] == 9.5
    assert merged.iloc[0]["volume"] == 5.0
    assert merged.iloc[1]["close"] == 10.4
    assert merged.iloc[1]["volume"] == 7.0
