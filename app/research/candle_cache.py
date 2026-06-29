"""Cached historical candle fetch for research tools (read-only)."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from app.candle_utils import normalize_candles
from app.config import RESOLUTION_SECONDS, settings
from app.market_data import delta_client

logger = logging.getLogger(__name__)

CHUNK_BARS = 450
_CACHE_TTL_SECONDS = 3600
_cache: dict[str, tuple[float, pd.DataFrame]] = {}
_cache_lock = threading.Lock()


def _cache_key(symbol: str, resolution: str, start_ts: int, end_ts: int) -> str:
    return f"{symbol}|{resolution}|{start_ts}|{end_ts}"


def _parse_date_start(date_str: str) -> int:
    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_date_end(date_str: str) -> int:
    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return int(dt.timestamp())


def months_back_range(months_back: int) -> tuple[str, str]:
    """UTC date strings for research window."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=max(1, months_back) * 30)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def fetch_candles_range(
    symbol: str,
    start_date: str,
    end_date: str,
    *,
    resolution: str = "5m",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    Paginated Delta history/candles fetch for any supported symbol.
    Does not touch live cache or paper trading state.
    """
    symbol = symbol.upper().strip()
    allowed = set(settings.symbol_map.values())
    if symbol not in allowed:
        raise ValueError(f"Unsupported symbol '{symbol}'. Allowed: {sorted(allowed)}")

    if resolution not in settings.timeframes:
        raise ValueError(f"Unsupported resolution '{resolution}'")

    start_ts = _parse_date_start(start_date)
    end_ts = _parse_date_end(end_date)
    if end_ts <= start_ts:
        raise ValueError("end_date must be after start_date")

    key = _cache_key(symbol, resolution, start_ts, end_ts)
    if use_cache:
        with _cache_lock:
            entry = _cache.get(key)
            if entry and (time.time() - entry[0]) < _CACHE_TTL_SECONDS:
                logger.debug("Candle cache hit %s", key)
                return entry[1].copy()

    interval = RESOLUTION_SECONDS[resolution]
    chunk_seconds = CHUNK_BARS * interval
    all_rows: list[dict[str, Any]] = []
    cursor_end = end_ts

    while cursor_end > start_ts:
        cursor_start = max(start_ts, cursor_end - chunk_seconds)
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": cursor_start,
            "end": cursor_end,
        }
        payload = delta_client._get_json("/history/candles", params)
        if not payload.get("success", False):
            raise RuntimeError(f"Delta API error: {payload.get('error', payload)}")
        rows = payload.get("result") or []
        all_rows.extend(rows)
        cursor_end = cursor_start - interval
        if not rows:
            break

    if not all_rows:
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
    else:
        df = pd.DataFrame(all_rows)
        df = normalize_candles(df, resolution)
        df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].copy()
        df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)

    if use_cache:
        with _cache_lock:
            _cache[key] = (time.time(), df.copy())

    logger.info(
        "Research candles %s %s: %d bars (%s → %s)",
        symbol,
        resolution,
        len(df),
        start_date,
        end_date,
    )
    return df


def clear_candle_cache() -> None:
    with _cache_lock:
        _cache.clear()
