"""Candle normalization, validation, and gap filling."""

from __future__ import annotations

import logging

import pandas as pd

from app.config import RESOLUTION_SECONDS

logger = logging.getLogger(__name__)


def normalize_candles(
    df: pd.DataFrame,
    resolution: str,
    *,
    stats: dict | None = None,
) -> pd.DataFrame:
    """
    Sort ascending, dedupe timestamps, validate OHLC, and log gaps.

    Delta Exchange returns candles newest-first; this ensures a clean
    strictly-increasing series for chart libraries.
    """
    expected_interval = RESOLUTION_SECONDS[resolution]
    columns = ["time", "open", "high", "low", "close", "volume"]

    if df.empty:
        logger.warning("Empty candle dataframe for resolution=%s", resolution)
        return pd.DataFrame(columns=columns)

    normalized = df.copy()
    normalized["time"] = pd.to_numeric(normalized["time"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        normalized[column] = pd.to_numeric(normalized.get(column), errors="coerce")

    before = len(normalized)
    after_dropna = normalized.dropna(subset=["time", "open", "high", "low", "close"])
    dropna_removed = before - len(after_dropna)
    normalized = after_dropna
    normalized["time"] = normalized["time"].astype(int)
    normalized = normalized.sort_values("time", ascending=True)
    before_dedupe = len(normalized)
    normalized = normalized.drop_duplicates(subset=["time"], keep="last")
    duplicate_removed = before_dedupe - len(normalized)

    dropped = dropna_removed + duplicate_removed
    if stats is not None:
        stats.update(
            {
                "dropna_removed": dropna_removed,
                "duplicate_removed": duplicate_removed,
                "volume_nan_count": int(normalized["volume"].isna().sum()) if len(normalized) else 0,
                "after_normalize_count": len(normalized),
            }
        )
    if dropped:
        logger.warning(
            "Dropped %d invalid/duplicate candle row(s) for %s",
            dropped,
            resolution,
        )

    normalized["high"] = normalized[["high", "open", "close"]].max(axis=1)
    normalized["low"] = normalized[["low", "open", "close"]].min(axis=1)
    normalized = normalized.reset_index(drop=True)

    if len(normalized) > 1:
        times = normalized["time"].tolist()
        gap_indices = [
            i
            for i in range(1, len(times))
            if times[i] - times[i - 1] != expected_interval
        ]
        for i in gap_indices[:5]:
            logger.warning(
                "Missing candle gap (%s): %d -> %d (expected +%ds, got +%ds)",
                resolution,
                times[i - 1],
                times[i],
                expected_interval,
                times[i] - times[i - 1],
            )
        if len(gap_indices) > 5:
            logger.warning(
                "%d total gap(s) in %s candles (expected %ds interval)",
                len(gap_indices),
                resolution,
                expected_interval,
            )

        if not all(times[i] < times[i + 1] for i in range(len(times) - 1)):
            logger.error("Candle timestamps are not strictly increasing after normalize")

    logger.debug(
        "Normalized %d candles (%s): min_time=%d max_time=%d interval=%ds",
        len(normalized),
        resolution,
        int(normalized["time"].iloc[0]),
        int(normalized["time"].iloc[-1]),
        expected_interval,
    )
    return normalized[columns]


def candle_record(row) -> dict:
    """Single candle row as JSON-friendly dict (Series or named tuple)."""
    if hasattr(row, "index"):
        volume = row["volume"]
        return {
            "time": int(row["time"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(volume) if pd.notna(volume) else 0.0,
        }
    volume = row.volume
    return {
        "time": int(row.time),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "volume": float(volume) if pd.notna(volume) else 0.0,
    }


def is_flat_candle(row) -> bool:
    """True when open/high/low/close are equal (no visible body on chart)."""
    o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
    return h <= l or (o == h == l == c)


def merge_mark_ohlc_with_trade_volume(
    trade_df: pd.DataFrame,
    mark_df: pd.DataFrame,
    *,
    stats: dict | None = None,
) -> pd.DataFrame:
    """
    Build chart/signal candles from mark-price OHLC (TradingView-aligned).

    Mark candles carry real bodies and wicks; trade volume is merged by timestamp.
    Falls back to trade candles with flat-bar enrichment when mark data is missing.
    """
    if mark_df.empty:
        if stats is not None:
            stats.update(
                {
                    "ohlc_source": "trade_only",
                    "mark_candle_count": 0,
                    "flat_before": int(validate_candle_series(trade_df, "5m")["flat_count"])
                    if not trade_df.empty
                    else 0,
                }
            )
        return enrich_flat_candles_with_mark(trade_df, mark_df, stats=stats)

    if trade_df.empty:
        if stats is not None:
            stats.update({"ohlc_source": "mark_only", "mark_candle_count": len(mark_df)})
        return mark_df.copy()

    trade_by_time = trade_df.set_index("time")
    merged = mark_df.copy()
    volumes: list[float] = []
    for t in merged["time"].astype(int):
        if int(t) in trade_by_time.index:
            vol = trade_by_time.loc[int(t), "volume"]
            volumes.append(float(vol) if pd.notna(vol) else 0.0)
        else:
            volumes.append(0.0)
    merged["volume"] = volumes

    flat_before = int(merged.apply(is_flat_candle, axis=1).sum())
    if flat_before and not trade_df.empty:
        merged = enrich_flat_candles_with_mark(merged, mark_df, stats=stats)
    elif stats is not None:
        stats.update(
            {
                "ohlc_source": "mark_primary",
                "mark_candle_count": len(mark_df),
                "flat_before": flat_before,
                "enriched_from_mark": 0,
                "flat_after": int(merged.apply(is_flat_candle, axis=1).sum()),
            }
        )

    if stats is not None and "ohlc_source" not in stats:
        stats["ohlc_source"] = "mark_primary"
        stats["mark_candle_count"] = len(mark_df)

    return merged.reset_index(drop=True)


def enrich_flat_candles_with_mark(
    trade_df: pd.DataFrame,
    mark_df: pd.DataFrame,
    *,
    stats: dict | None = None,
) -> pd.DataFrame:
    """
    Replace flat trade OHLC with mark-price OHLC for chart readability.

    Trade close is preserved so signals/indicators stay aligned with executed prices.
    Volume always comes from the trade candle.
    """
    if trade_df.empty or mark_df.empty:
        if stats is not None:
            stats.update({"flat_before": 0, "enriched_from_mark": 0, "flat_after": 0})
        return trade_df

    enriched = trade_df.copy()
    mark_by_time = mark_df.set_index("time")
    flat_before = 0
    enriched_count = 0

    for idx, row in enriched.iterrows():
        if not is_flat_candle(row):
            continue
        flat_before += 1
        t = int(row["time"])
        if t not in mark_by_time.index:
            continue

        mark = mark_by_time.loc[t]
        if is_flat_candle(mark):
            continue

        trade_close = float(row["close"])
        trade_open = float(row["open"])
        mark_open = float(mark["open"])
        mark_high = float(mark["high"])
        mark_low = float(mark["low"])

        enriched.at[idx, "open"] = mark_open
        enriched.at[idx, "high"] = max(mark_high, trade_open, trade_close)
        enriched.at[idx, "low"] = min(mark_low, trade_open, trade_close)
        enriched.at[idx, "close"] = trade_close
        enriched_count += 1

    flat_after = int(enriched.apply(is_flat_candle, axis=1).sum())
    if stats is not None:
        stats.update(
            {
                "flat_before": flat_before,
                "enriched_from_mark": enriched_count,
                "flat_after": flat_after,
            }
        )

    if enriched_count:
        logger.info(
            "Mark-price enrichment: flat_before=%d enriched=%d flat_after=%d",
            flat_before,
            enriched_count,
            flat_after,
        )

    return enriched


def first_last_candles(df: pd.DataFrame) -> tuple[dict | None, dict | None]:
    if df.empty:
        return None, None
    first = candle_record(df.iloc[0])
    last = candle_record(df.iloc[-1])
    return first, last


def validate_candle_series(df: pd.DataFrame, resolution: str) -> dict:
    """Return audit metadata for API responses and debugging."""
    expected_interval = RESOLUTION_SECONDS[resolution]
    if df.empty:
        return {
            "count": 0,
            "min_time": None,
            "max_time": None,
            "expected_interval_seconds": expected_interval,
            "gap_count": 0,
            "duplicate_count": 0,
            "strictly_increasing": True,
            "flat_count": 0,
        }

    times = df["time"].astype(int).tolist()
    duplicate_count = len(times) - len(set(times))
    strictly_increasing = all(times[i] < times[i + 1] for i in range(len(times) - 1))
    gap_count = 0
    if len(times) > 1:
        gap_count = sum(
            1 for i in range(1, len(times)) if times[i] - times[i - 1] != expected_interval
        )

    flat_count = int(
        ((df["open"] == df["high"]) & (df["high"] == df["low"]) & (df["low"] == df["close"])).sum()
    )

    return {
        "count": len(times),
        "min_time": times[0],
        "max_time": times[-1],
        "expected_interval_seconds": expected_interval,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "strictly_increasing": strictly_increasing,
        "flat_count": flat_count,
    }


def fill_candle_gaps(df: pd.DataFrame, resolution: str) -> pd.DataFrame:
    """
    Insert synthetic flat candles for missing intervals so timestamps are continuous.

    Uses previous close for OHLC on filled bars. Intended for chart display continuity.
    """
    expected = RESOLUTION_SECONDS[resolution]
    columns = ["time", "open", "high", "low", "close", "volume"]

    if df.empty or len(df) < 2:
        return df

    filled: list[dict] = []
    records = df.to_dict("records")
    filled.append(records[0])
    inserted = 0

    for i in range(1, len(records)):
        prev = filled[-1]
        curr = records[i]
        expected_time = int(prev["time"]) + expected

        while expected_time < int(curr["time"]):
            price = float(prev["close"])
            filled.append(
                {
                    "time": expected_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": 0.0,
                }
            )
            inserted += 1
            prev = filled[-1]
            expected_time += expected

        filled.append(curr)

    if inserted:
        logger.info(
            "Filled %d missing candle(s) for %s interval=%ds",
            inserted,
            resolution,
            expected,
        )

    return pd.DataFrame(filled, columns=columns)
