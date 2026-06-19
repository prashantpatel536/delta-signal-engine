"""Market data fetching and in-memory cache for Delta Exchange candles."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

import pandas as pd
import requests

from app.config import MARK_CANDLE_PREFIX, RESOLUTION_SECONDS, settings
from app.candle_utils import (
    enrich_flat_candles_with_mark,
    first_last_candles,
    normalize_candles,
    validate_candle_series,
)

logger = logging.getLogger(__name__)


@dataclass
class SymbolTimeframeData:
    candles: pd.DataFrame = field(default_factory=pd.DataFrame)
    display_candles: pd.DataFrame = field(default_factory=pd.DataFrame)
    sma84: pd.Series = field(default_factory=pd.Series)
    hh50: pd.Series = field(default_factory=pd.Series)
    ll50: pd.Series = field(default_factory=pd.Series)
    latest_signal: dict[str, Any] | None = None


class MarketDataStore:
    """Thread-safe in-memory store for candles, indicators, and signals."""

    def __init__(self, max_signal_history: int = 100) -> None:
        self._lock = Lock()
        self._data: dict[str, dict[str, SymbolTimeframeData]] = {}
        self._signal_history: list[dict[str, Any]] = []
        self._max_signal_history = max_signal_history
        self.last_refresh: str | None = None
        self.last_live_price_refresh: str | None = None
        self.last_error: str | None = None
        self._live_prices: dict[str, float] = {}

    def ensure_symbol(self, symbol: str) -> None:
        with self._lock:
            if symbol not in self._data:
                self._data[symbol] = {
                    timeframe: SymbolTimeframeData()
                    for timeframe in settings.timeframes
                }

    def update(
        self,
        symbol: str,
        timeframe: str,
        candles: pd.DataFrame,
        sma84: pd.Series,
        hh50: pd.Series,
        ll50: pd.Series,
        signal: dict[str, Any] | None,
        display_candles: pd.DataFrame | None = None,
    ) -> None:
        with self._lock:
            self.ensure_symbol_unlocked(symbol)
            entry = self._data[symbol][timeframe]
            entry.candles = candles
            entry.display_candles = (
                display_candles if display_candles is not None else candles
            )
            entry.sma84 = sma84
            entry.hh50 = hh50
            entry.ll50 = ll50
            entry.latest_signal = signal
            if signal is not None:
                self._append_signal_unlocked(signal)

    def _append_signal_unlocked(self, signal: dict[str, Any]) -> None:
        key = (
            signal.get("symbol"),
            signal.get("timeframe"),
            signal.get("timestamp"),
            signal.get("signal"),
        )
        existing_keys = {
            (s.get("symbol"), s.get("timeframe"), s.get("timestamp"), s.get("signal"))
            for s in self._signal_history
        }
        if key not in existing_keys:
            self._signal_history.insert(0, signal)
            self._signal_history = self._signal_history[: self._max_signal_history]

    def ensure_symbol_unlocked(self, symbol: str) -> None:
        if symbol not in self._data:
            self._data[symbol] = {
                timeframe: SymbolTimeframeData()
                for timeframe in settings.timeframes
            }

    def get_chart_data(
        self, symbol: str, timeframe: str | None = None
    ) -> dict[str, SymbolTimeframeData]:
        with self._lock:
            self.ensure_symbol_unlocked(symbol)
            if timeframe:
                return {timeframe: self._data[symbol][timeframe]}
            return dict(self._data[symbol])

    def get_latest_signals(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._signal_history)

    def get_latest_prices(self) -> dict[str, float]:
        """Latest price per symbol — live ticker when available, else last candle close."""
        preferred = ("5m", "15m", "1m")
        with self._lock:
            prices: dict[str, float] = {}
            for symbol in self._data:
                if symbol in self._live_prices:
                    prices[symbol] = self._live_prices[symbol]
                    continue
                for timeframe in preferred:
                    tf_data = self._data[symbol].get(timeframe)
                    if tf_data is None:
                        continue
                    candles = tf_data.candles
                    if candles is not None and not candles.empty:
                        prices[symbol] = float(candles["close"].iloc[-1])
                        break
            return prices

    def get_live_price(self, symbol: str) -> float | None:
        with self._lock:
            if symbol in self._live_prices:
                return self._live_prices[symbol]
            tf_data = self._data.get(symbol, {}).get("5m")
            if tf_data and not tf_data.candles.empty:
                return float(tf_data.candles["close"].iloc[-1])
        return None

    def apply_live_prices(self, prices: dict[str, float]) -> None:
        """Patch in-memory candles with latest ticker/mark price."""
        from app.models import utc_now_iso

        with self._lock:
            for symbol, price in prices.items():
                self._live_prices[symbol] = float(price)
                symbol_data = self._data.get(symbol)
                if not symbol_data:
                    continue
                for tf_data in symbol_data.values():
                    self._patch_last_candle(tf_data.candles, price)
                    self._patch_last_candle(tf_data.display_candles, price)
            self.last_live_price_refresh = utc_now_iso()

    @staticmethod
    def _patch_last_candle(df: pd.DataFrame, price: float) -> None:
        if df is None or df.empty:
            return
        idx = df.index[-1]
        df.at[idx, "close"] = price
        df.at[idx, "high"] = max(float(df.at[idx, "high"]), price)
        df.at[idx, "low"] = min(float(df.at[idx, "low"]), price)

    def set_last_refresh(self, timestamp: str) -> None:
        with self._lock:
            self.last_refresh = timestamp

    def set_last_error(self, message: str | None) -> None:
        with self._lock:
            self.last_error = message

    def cache_pair_counts(self) -> tuple[int, int]:
        """Return (pairs_with_candles, total_pairs)."""
        total = len(settings.symbol_map) * len(settings.timeframes)
        ready = 0
        with self._lock:
            for symbol_data in self._data.values():
                for tf_data in symbol_data.values():
                    if not tf_data.candles.empty:
                        ready += 1
        return ready, total


class DeltaExchangeClient:
    """Client for Delta Exchange candle API (public; optional API key auth)."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
        api_key: str | None = None,
        api_secret: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.api_base_url).rstrip("/")
        self.timeout = timeout
        self.api_key = api_key if api_key is not None else settings.api_key
        self.api_secret = api_secret if api_secret is not None else settings.api_secret
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})
        self._request_lock = Lock()

    def _auth_headers(self, method: str, path: str, query: str = "") -> dict[str, str]:
        if not self.api_key or not self.api_secret:
            return {}
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            f"{method}{timestamp}{path}{query}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
        }

    def _get_json(self, path: str, params: dict) -> dict:
        query = "?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        headers = self._auth_headers("GET", path, query)
        with self._request_lock:
            response = self.session.get(
                f"{self.base_url}{path}",
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

    def _request_candle_rows(
        self,
        symbol: str,
        resolution: str,
        limit: int,
    ) -> tuple[list, dict]:
        """Fetch raw candle rows from Delta API."""
        interval_seconds = RESOLUTION_SECONDS[resolution]
        end_time = int(time.time())
        start_time = end_time - (limit + 10) * interval_seconds

        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": start_time,
            "end": end_time,
        }

        payload = self._get_json("/history/candles", params)

        if not payload.get("success", False):
            message = payload.get("error", payload)
            raise RuntimeError(f"Delta API error: {message}")

        rows = payload.get("result") or []
        return rows, {
            "api_url": f"{self.base_url}/history/candles",
            "symbol_requested": symbol,
            "start_time": start_time,
            "end_time": end_time,
            "requested_limit": limit,
        }

    def _fetch_normalized_candles(
        self,
        symbol: str,
        resolution: str,
        limit: int,
        stats: dict | None = None,
    ) -> pd.DataFrame:
        rows, _ = self._request_candle_rows(symbol, resolution, limit)
        if not rows:
            return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        df = pd.DataFrame(rows)
        return normalize_candles(df, resolution, stats=stats)

    def fetch_candles_with_audit(
        self,
        symbol: str,
        resolution: str,
        limit: int | None = None,
    ) -> tuple[pd.DataFrame, dict]:
        """
        Fetch candles and return pipeline audit showing where rows are removed.

        Stages tracked: raw_api -> normalize (dropna/dedupe) -> fetch tail -> output.
        """
        limit = limit or settings.candle_limit
        audit: dict = {
            "symbol": symbol,
            "resolution": resolution,
            "fetch_tail_limit": limit,
            "volume_filter_removed": 0,
            "indicator_rows_removed": 0,
            "mark_enrichment_enabled": settings.enrich_flat_candles_with_mark,
        }

        try:
            rows, request_meta = self._request_candle_rows(symbol, resolution, limit)
        except requests.RequestException as exc:
            logger.error(
                "Failed to fetch candles for %s %s: %s",
                symbol,
                resolution,
                exc,
            )
            raise

        audit.update(request_meta)
        audit["raw_api_count"] = len(rows)

        if not rows:
            logger.warning("No candle data returned for %s %s", symbol, resolution)
            audit.update(
                {
                    "after_normalize_count": 0,
                    "after_fetch_tail_count": 0,
                    "dropna_removed": 0,
                    "duplicate_removed": 0,
                    "flat_before": 0,
                    "enriched_from_mark": 0,
                    "flat_after": 0,
                    "first_candle": None,
                    "last_candle": None,
                }
            )
            return pd.DataFrame(
                columns=["time", "open", "high", "low", "close", "volume"]
            ), audit

        norm_stats: dict = {}
        df = pd.DataFrame(rows)
        df = normalize_candles(df, resolution, stats=norm_stats)
        audit.update(norm_stats)
        audit["dropna_removed"] = norm_stats.get("dropna_removed", 0)
        audit["duplicate_removed"] = norm_stats.get("duplicate_removed", 0)
        audit["flat_before"] = int(validate_candle_series(df, resolution)["flat_count"])

        before_tail = len(df)
        df = df.tail(limit).reset_index(drop=True)
        audit["after_fetch_tail_count"] = len(df)
        audit["fetch_tail_removed"] = before_tail - len(df)

        first, last = first_last_candles(df)
        audit["first_candle"] = first
        audit["last_candle"] = last

        series_audit = validate_candle_series(df, resolution)
        audit["gap_count"] = series_audit["gap_count"]
        audit["flat_after"] = series_audit["flat_count"]
        audit["flat_before"] = series_audit["flat_count"]

        logger.info(
            "Candle pipeline %s %s: raw_api=%d normalize=%d (dropna=%d dup=%d) "
            "flat=%d after_tail=%d",
            symbol,
            resolution,
            audit["raw_api_count"],
            audit.get("after_normalize_count", len(df)),
            audit["dropna_removed"],
            audit["duplicate_removed"],
            audit["flat_after"],
            audit["after_fetch_tail_count"],
        )
        return df, audit

    def build_display_candles(
        self,
        trade_df: pd.DataFrame,
        symbol: str,
        resolution: str,
        limit: int | None = None,
    ) -> tuple[pd.DataFrame, dict]:
        """Build chart candles by enriching flat trade bars with mark-price OHLC."""
        limit = limit or settings.candle_limit
        stats: dict = {
            "mark_enrichment_enabled": settings.enrich_flat_candles_with_mark,
            "flat_before": int(validate_candle_series(trade_df, resolution)["flat_count"])
            if not trade_df.empty
            else 0,
        }

        if trade_df.empty or not settings.enrich_flat_candles_with_mark:
            stats.update({"enriched_from_mark": 0, "flat_after": stats["flat_before"]})
            return trade_df.copy(), stats

        mark_symbol = f"{MARK_CANDLE_PREFIX}{symbol}"
        try:
            mark_df = self._fetch_normalized_candles(mark_symbol, resolution, limit)
            display_df = enrich_flat_candles_with_mark(trade_df, mark_df, stats=stats)
            stats["mark_symbol"] = mark_symbol
            stats["mark_candle_count"] = len(mark_df)
            return display_df, stats
        except Exception as exc:
            logger.warning(
                "Mark-price enrichment failed for %s %s: %s",
                symbol,
                resolution,
                exc,
            )
            stats["mark_enrichment_error"] = str(exc)
            stats["enriched_from_mark"] = 0
            stats["flat_after"] = stats["flat_before"]
            return trade_df.copy(), stats

    def fetch_candles(
        self,
        symbol: str,
        resolution: str,
        limit: int | None = None,
    ) -> pd.DataFrame:
        df, audit = self.fetch_candles_with_audit(symbol, resolution, limit)

        if df.empty:
            return df

        if not validate_candle_series(df, resolution)["strictly_increasing"]:
            logger.error(
                "Candle series failed validation for %s %s",
                symbol,
                resolution,
            )
        elif audit.get("gap_count"):
            logger.warning(
                "Candle series has %d gap(s) for %s %s",
                audit["gap_count"],
                symbol,
                resolution,
            )

        return df

    def fetch_ticker_price(self, symbol: str) -> float:
        """Fetch live mark/spot price for a symbol from Delta tickers API."""
        payload = self._get_json(f"/tickers/{symbol}", {})
        if not payload.get("success", False):
            message = payload.get("error", payload)
            raise RuntimeError(f"Delta ticker error: {message}")

        result = payload.get("result")
        if isinstance(result, list):
            row = result[0] if result else {}
        elif isinstance(result, dict):
            row = result
        else:
            row = {}

        for key in ("mark_price", "spot_price", "close", "last_price"):
            raw = row.get(key)
            if raw is not None and str(raw).strip():
                return float(raw)

        raise RuntimeError(f"No price field in ticker response for {symbol}")


store = MarketDataStore()
delta_client = DeltaExchangeClient()
