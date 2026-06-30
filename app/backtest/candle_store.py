"""Persistent SQLite candle cache with incremental Delta download."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.backtest.db import get_backtest_connection
from app.candle_utils import normalize_candles
from app.config import RESOLUTION_SECONDS, settings
from app.market_data import delta_client

logger = logging.getLogger(__name__)

CHUNK_BARS = 450
SUPPORTED_RESOLUTIONS = ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d")


def _parse_date_start(date_str: str) -> int:
    from datetime import datetime, timezone

    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_date_end(date_str: str) -> int:
    from datetime import datetime, timezone

    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return int(dt.timestamp())


def _load_cached(symbol: str, resolution: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    with get_backtest_connection() as conn:
        rows = conn.execute(
            """
            SELECT time, open, high, low, close, volume
            FROM candle_bars
            WHERE symbol = ? AND resolution = ? AND time >= ? AND time <= ?
            ORDER BY time
            """,
            (symbol, resolution, start_ts, end_ts),
        ).fetchall()
    if not rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    return pd.DataFrame([dict(r) for r in rows])


def _save_bars(symbol: str, resolution: str, df: pd.DataFrame) -> None:
    if df.empty:
        return
    with get_backtest_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO candle_bars
            (symbol, resolution, time, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    symbol,
                    resolution,
                    int(r.time),
                    float(r.open),
                    float(r.high),
                    float(r.low),
                    float(r.close),
                    float(r.volume),
                )
                for r in df.itertuples(index=False)
            ],
        )
        conn.commit()


def _missing_ranges(
    cached_times: set[int], start_ts: int, end_ts: int, interval: int
) -> list[tuple[int, int]]:
    """Return contiguous unix ranges not present in cache (aligned to interval)."""
    if start_ts > end_ts:
        return []
    aligned_start = (start_ts // interval) * interval
    aligned_end = (end_ts // interval) * interval
    missing: list[tuple[int, int]] = []
    range_start: int | None = None
    t = aligned_start
    while t <= aligned_end:
        if t not in cached_times:
            if range_start is None:
                range_start = t
        elif range_start is not None:
            missing.append((range_start, t - interval))
            range_start = None
        t += interval
    if range_start is not None:
        missing.append((range_start, aligned_end))
    return missing


def _fetch_range(symbol: str, resolution: str, start_ts: int, end_ts: int) -> pd.DataFrame:
    interval = RESOLUTION_SECONDS[resolution]
    chunk_seconds = CHUNK_BARS * interval
    all_rows: list[dict[str, Any]] = []
    cursor_end = end_ts
    while cursor_end > start_ts:
        cursor_start = max(start_ts, cursor_end - chunk_seconds)
        payload = delta_client._get_json(
            "/history/candles",
            {"symbol": symbol, "resolution": resolution, "start": cursor_start, "end": cursor_end},
        )
        if not payload.get("success", False):
            raise RuntimeError(f"Delta API error: {payload.get('error', payload)}")
        rows = payload.get("result") or []
        all_rows.extend(rows)
        cursor_end = cursor_start - interval
        if not rows:
            break
    if not all_rows:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    df = pd.DataFrame(all_rows)
    return normalize_candles(df, resolution)


def get_candles(
    symbol: str,
    resolution: str,
    start_date: str,
    end_date: str,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    symbol = symbol.upper().strip()
    if resolution not in RESOLUTION_SECONDS:
        raise ValueError(f"Unsupported resolution '{resolution}'")
    allowed = set(settings.symbol_map.values())
    if symbol not in allowed:
        raise ValueError(f"Unsupported symbol '{symbol}'")

    start_ts = _parse_date_start(start_date)
    end_ts = _parse_date_end(end_date)
    interval = RESOLUTION_SECONDS[resolution]

    if force_refresh:
        df = _fetch_range(symbol, resolution, start_ts, end_ts)
        df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].copy()
        _save_bars(symbol, resolution, df)
        return df.reset_index(drop=True)

    cached = _load_cached(symbol, resolution, start_ts, end_ts)
    cached_times = set(int(t) for t in cached["time"]) if not cached.empty else set()

    for miss_start, miss_end in _missing_ranges(cached_times, start_ts, end_ts, interval):
        logger.info("Downloading %s %s %s → %s", symbol, resolution, miss_start, miss_end)
        fetched = _fetch_range(symbol, resolution, miss_start, miss_end)
        if not fetched.empty:
            _save_bars(symbol, resolution, fetched)

    result = _load_cached(symbol, resolution, start_ts, end_ts)
    logger.info("Candle store %s %s: %d bars (%s → %s)", symbol, resolution, len(result), start_date, end_date)
    return result
