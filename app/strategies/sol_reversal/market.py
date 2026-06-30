"""Delta Exchange market data for SOL Reversal (REST + WebSocket)."""

from __future__ import annotations

import asyncio
import json
import logging
from threading import Lock
from typing import Any

import pandas as pd

from app.indicators import candles_to_records
from app.market_data import delta_client
from app.research.candle_cache import fetch_candles_range, months_back_range
from app.strategies.sol_reversal.ha import attach_candle_colors, to_heikin_ashi
from app.strategies.sol_reversal.indicators import compute_atr

logger = logging.getLogger(__name__)

SYMBOL = "SOLUSDT"
TIMEFRAME = "5m"
WS_URL = "wss://socket.delta.exchange"


class SolMarketStore:
    """Thread-safe SOL-only candle store (Delta data only)."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._ohlc = pd.DataFrame()
        self._signal_candles = pd.DataFrame()
        self._ha = pd.DataFrame()
        self._atr = pd.Series(dtype=float)
        self._last_price: float | None = None
        self._ws_connected = False

    def load_history(self, months_back: int = 6) -> None:
        start, end = months_back_range(months_back)
        df = fetch_candles_range(SYMBOL, start, end, resolution=TIMEFRAME, use_cache=True)
        with self._lock:
            self._apply_ohlc(df)

    def _apply_ohlc(self, df: pd.DataFrame) -> None:
        if df.empty:
            self._ohlc = df.copy()
            self._signal_candles = pd.DataFrame()
            self._ha = pd.DataFrame()
            self._atr = pd.Series(dtype=float)
            return
        display_df, stats = delta_client.resolve_ohlc_candles(df, SYMBOL, TIMEFRAME)
        logger.info(
            "SOL OHLC resolve: flat_before=%s flat_after=%s source=%s",
            stats.get("flat_before"),
            stats.get("flat_after"),
            stats.get("ohlc_source"),
        )
        self._ohlc = display_df.copy()
        self._signal_candles = attach_candle_colors(self._ohlc)
        self._ha = to_heikin_ashi(self._ohlc)
        period = 14
        self._atr = (
            compute_atr(self._signal_candles, period)
            if not self._signal_candles.empty
            else pd.Series(dtype=float)
        )
        if not self._ohlc.empty:
            self._last_price = float(self._ohlc["close"].iloc[-1])

    def update_ticker(self, price: float) -> None:
        with self._lock:
            self._last_price = float(price)
            if not self._ohlc.empty:
                idx = len(self._ohlc) - 1
                self._ohlc.at[idx, "close"] = price
                if price > self._ohlc.at[idx, "high"]:
                    self._ohlc.at[idx, "high"] = price
                if price < self._ohlc.at[idx, "low"]:
                    self._ohlc.at[idx, "low"] = price
                self._signal_candles = attach_candle_colors(self._ohlc)
                self._ha = to_heikin_ashi(self._ohlc)
                self._atr = compute_atr(self._signal_candles, 14)

    def append_or_update_candle(self, candle: dict[str, Any]) -> bool:
        """Returns True if a new closed candle was finalized."""
        with self._lock:
            if self._ohlc.empty:
                return False
            ts = int(candle["time"])
            row = {
                "time": ts,
                "open": float(candle["open"]),
                "high": float(candle["high"]),
                "low": float(candle["low"]),
                "close": float(candle["close"]),
                "volume": float(candle.get("volume", 0)),
            }
            last_ts = int(self._ohlc["time"].iloc[-1])
            if ts == last_ts:
                for k, v in row.items():
                    if k != "time":
                        self._ohlc.at[self._ohlc.index[-1], k] = v
                closed = False
            elif ts > last_ts:
                self._ohlc = pd.concat([self._ohlc, pd.DataFrame([row])], ignore_index=True)
                closed = True
            else:
                return False
            self._signal_candles = attach_candle_colors(self._ohlc)
            self._ha = to_heikin_ashi(self._ohlc)
            self._atr = compute_atr(self._signal_candles, 14)
            self._last_price = float(row["close"])
            return closed

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            ha_last = None
            if not self._ha.empty:
                r = self._ha.iloc[-1]
                ha_last = {
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "color": r["color"],
                    "time": int(r["time"]),
                }
            atr_val = float(self._atr.iloc[-1]) if len(self._atr) and not pd.isna(self._atr.iloc[-1]) else None
            return {
                "symbol": SYMBOL,
                "timeframe": TIMEFRAME,
                "last_price": self._last_price,
                "ha_candle": ha_last,
                "atr": atr_val,
                "candle_count": len(self._ohlc),
                "ws_connected": self._ws_connected,
                "last_candle_time": int(self._ohlc["time"].iloc[-1]) if not self._ohlc.empty else None,
            }

    def chart_payload(self, bars: int = 200) -> dict[str, Any]:
        """BTC-terminal compatible chart payload (HA candles, no SMA/HH/LL)."""
        from datetime import datetime

        with self._lock:
            ohlc = self._ohlc.tail(bars).copy()
            ha = self._ha.tail(bars).copy()
            last_price = self._last_price

        if ha.empty:
            return {
                "symbol": "SOL",
                "timeframe": TIMEFRAME,
                "candles": [],
                "sma84": [],
                "hh50": [],
                "ll50": [],
                "signals": [],
                "signal_context": {"live_price": last_price, "chart_timeframe": TIMEFRAME},
            }

        if not ohlc.empty and "volume" in ohlc.columns:
            ha = ha.copy()
            ha["volume"] = ohlc["volume"].astype(float).values

        candle_times = [int(t) for t in ha["time"].tolist()]
        candles = candles_to_records(ha)

        signals: list[dict[str, Any]] = []
        try:
            from app.strategies.sol_reversal.repositories import SolPositionRepository

            for tr in SolPositionRepository().list_closed(40):
                entry_iso = tr.get("opened_at") or tr.get("entry_time")
                if not entry_iso:
                    continue
                try:
                    entry_unix = int(datetime.fromisoformat(entry_iso.replace("Z", "+00:00")).timestamp())
                except (TypeError, ValueError):
                    continue
                snapped = min(candle_times, key=lambda t: abs(t - entry_unix))
                if abs(snapped - entry_unix) > 600:
                    continue
                signals.append({
                    "candle_time": snapped,
                    "signal": tr.get("side", "BUY"),
                    "timeframe": TIMEFRAME,
                    "status": "TP_HIT" if float(tr.get("pnl_usd") or 0) >= 0 else "SL_HIT",
                })
        except Exception:
            logger.exception("SOL chart trade markers failed")

        return {
            "symbol": "SOL",
            "timeframe": TIMEFRAME,
            "candles": candles,
            "sma84": [],
            "hh50": [],
            "ll50": [],
            "signals": signals,
            "signal_context": {
                "live_price": last_price,
                "chart_timeframe": TIMEFRAME,
                "signal_timeframe": TIMEFRAME,
                "candle_count": len(candles),
                "chart_display_source": "heikin_ashi_mark_ohlc",
            },
            "candle_counts": {"sent": len(candles)},
        }

    def closed_candle_index(self) -> int:
        with self._lock:
            return len(self._signal_candles) - 2 if len(self._signal_candles) >= 2 else -1

    def signal_bar_at(self, idx: int) -> tuple[float, float, float, float]:
        """Regular chart OHLC at index (Pine close/open series)."""
        with self._lock:
            r = self._signal_candles.iloc[idx]
            return float(r["high"]), float(r["low"]), float(r["close"]), float(r["open"])

    def get_signal_candles(self) -> pd.DataFrame:
        with self._lock:
            return self._signal_candles.copy()

    def ha_bar_at(self, idx: int) -> tuple[float, float, float, float]:
        """Deprecated alias — use signal_bar_at."""
        return self.signal_bar_at(idx)

    def get_ha(self) -> pd.DataFrame:
        with self._lock:
            return self._ha.copy()

    def get_atr(self) -> pd.Series:
        with self._lock:
            return self._atr.copy()

    def last_bar_ohlc(self) -> tuple[float, float, float, float]:
        with self._lock:
            r = self._ohlc.iloc[-1]
            return float(r["high"]), float(r["low"]), float(r["close"]), float(r["open"])

    def set_ws_connected(self, connected: bool) -> None:
        with self._lock:
            self._ws_connected = connected


sol_market = SolMarketStore()


async def poll_ticker_loop(interval: float = 5.0) -> None:
    while True:
        try:
            price = await asyncio.to_thread(delta_client.fetch_ticker_price, SYMBOL)
            sol_market.update_ticker(price)
        except Exception as exc:
            logger.warning("SOL ticker poll failed: %s", exc)
        await asyncio.sleep(interval)


async def refresh_candles_loop(interval: float = 60.0) -> None:
    while True:
        try:
            await asyncio.to_thread(sol_market.load_history, 6)
        except Exception as exc:
            logger.warning("SOL candle refresh failed: %s", exc)
        await asyncio.sleep(interval)


async def delta_websocket_loop() -> None:
    """Subscribe to Delta Exchange candlestick + ticker for SOLUSDT."""
    try:
        import websockets
    except ImportError:
        logger.warning("websockets package not installed — SOL WS disabled, using REST polling only")
        return

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20) as ws:
                sol_market.set_ws_connected(True)
                sub = {
                    "type": "subscribe",
                    "payload": {
                        "channels": [
                            {"name": "candlestick_5m", "symbols": [SYMBOL]},
                            {"name": "v2/ticker", "symbols": [SYMBOL]},
                        ]
                    },
                }
                await ws.send(json.dumps(sub))
                logger.info("SOL Reversal WS subscribed to %s", SYMBOL)
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    mtype = msg.get("type", "")
                    if mtype == "candlestick_5m" and msg.get("symbol") == SYMBOL:
                        payload = msg.get("candlestick") or msg.get("payload") or msg
                        if isinstance(payload, dict):
                            sol_market.append_or_update_candle({
                                "time": payload.get("start_time") or payload.get("time"),
                                "open": payload.get("open"),
                                "high": payload.get("high"),
                                "low": payload.get("low"),
                                "close": payload.get("close"),
                                "volume": payload.get("volume", 0),
                            })
                    elif "ticker" in mtype or mtype == "v2/ticker":
                        mark = msg.get("mark_price") or msg.get("close") or msg.get("price")
                        if mark:
                            sol_market.update_ticker(float(mark))
        except Exception as exc:
            sol_market.set_ws_connected(False)
            logger.warning("SOL WS disconnected: %s — retrying in 5s", exc)
            await asyncio.sleep(5)
