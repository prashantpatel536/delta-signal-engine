"""Technical indicator calculations."""

from __future__ import annotations

import logging

import pandas as pd

logger = logging.getLogger(__name__)

SMA_PERIOD = 84
HHLL_PERIOD = 50


def calculate_sma84(closes: pd.Series) -> pd.Series:
    """Simple moving average of close prices over 84 periods."""
    sma = closes.rolling(window=SMA_PERIOD, min_periods=SMA_PERIOD).mean()
    logger.debug("Calculated SMA84 for %d candles", len(closes))
    return sma


def calculate_hh50(highs: pd.Series) -> pd.Series:
    """
    Highest high of the previous 50 completed candles.

    For index i, uses highs[i-50:i] (never includes the current candle).
    Equivalent to candles[-51:-1] for the latest bar.
    """
    # Shift by 1 so rolling window excludes the current candle.
    shifted = highs.shift(1)
    hh50 = shifted.rolling(window=HHLL_PERIOD, min_periods=HHLL_PERIOD).max()
    logger.debug("Calculated HH50 for %d candles", len(highs))
    return hh50


def calculate_ll50(lows: pd.Series) -> pd.Series:
    """
    Lowest low of the previous 50 completed candles.

    For index i, uses lows[i-50:i] (never includes the current candle).
    """
    shifted = lows.shift(1)
    ll50 = shifted.rolling(window=HHLL_PERIOD, min_periods=HHLL_PERIOD).min()
    logger.debug("Calculated LL50 for %d candles", len(lows))
    return ll50


def calculate_indicators(candles: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Calculate SMA84, HH50, and LL50 for a candle DataFrame."""
    if candles.empty:
        empty = pd.Series(dtype=float)
        return empty, empty, empty

    sma84 = calculate_sma84(candles["close"])
    hh50 = calculate_hh50(candles["high"])
    ll50 = calculate_ll50(candles["low"])

    logger.info(
        "Indicator calculation complete: %d candles, SMA84 valid=%d, HH50 valid=%d, LL50 valid=%d",
        len(candles),
        sma84.notna().sum(),
        hh50.notna().sum(),
        ll50.notna().sum(),
    )
    return sma84, hh50, ll50


def series_to_list(series: pd.Series) -> list[float | None]:
    """Convert a pandas Series to a JSON-friendly list with None for NaN."""
    return [None if pd.isna(value) else float(value) for value in series.tolist()]


def candles_to_records(candles: pd.DataFrame) -> list[dict]:
    """Convert candle DataFrame rows to dict records."""
    records: list[dict] = []
    for row in candles.itertuples(index=False):
        records.append(
            {
                "time": int(row.time),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(row.volume),
            }
        )
    return records
