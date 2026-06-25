"""Fetch historical BTC candles for research backtests (read-only)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from app.candle_utils import normalize_candles
from app.config import RESOLUTION_SECONDS, settings
from app.market_data import delta_client

logger = logging.getLogger(__name__)

BTC_SYMBOL = "BTCUSDT"
CHUNK_BARS = 450


def _parse_date(date_str: str) -> int:
    """Parse YYYY-MM-DD to unix seconds (UTC start of day)."""
    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def _parse_date_end(date_str: str) -> int:
    """End of calendar day UTC."""
    dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d").replace(
        hour=23, minute=59, second=59, tzinfo=timezone.utc
    )
    return int(dt.timestamp())


def fetch_btc_candles_range(
    start_date: str,
    end_date: str,
    *,
    resolution: str = "5m",
) -> pd.DataFrame:
    """
    Paginated Delta history/candles fetch for BTCUSDT only.
    Does not touch live cache or paper trading state.
    """
    if resolution not in settings.timeframes:
        raise ValueError(f"Unsupported resolution '{resolution}'")

    start_ts = _parse_date(start_date)
    end_ts = _parse_date_end(end_date)
    if end_ts <= start_ts:
        raise ValueError("end_date must be after start_date")

    interval = RESOLUTION_SECONDS[resolution]
    chunk_seconds = CHUNK_BARS * interval
    all_rows: list[dict] = []
    cursor_end = end_ts

    while cursor_end > start_ts:
        cursor_start = max(start_ts, cursor_end - chunk_seconds)
        params = {
            "symbol": BTC_SYMBOL,
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
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(all_rows)
    df = normalize_candles(df, resolution)
    df = df[(df["time"] >= start_ts) & (df["time"] <= end_ts)].copy()
    df = df.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    logger.info(
        "Research candles %s %s: %d bars (%s → %s)",
        BTC_SYMBOL,
        resolution,
        len(df),
        start_date,
        end_date,
    )
    return df
