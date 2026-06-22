"""Trading signal generation from indicators."""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


def _signal_at_index(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
    idx: int,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    if idx < 1:
        return None

    prev_idx = idx - 1
    curr_close = candles["close"].iloc[idx]
    prev_close = candles["close"].iloc[prev_idx]
    curr_sma = sma84.iloc[idx]
    curr_hh50 = hh50.iloc[idx]
    prev_hh50 = hh50.iloc[prev_idx]
    curr_ll50 = ll50.iloc[idx]
    prev_ll50 = ll50.iloc[prev_idx]

    if any(
        pd.isna(value)
        for value in (curr_close, prev_close, curr_sma, curr_hh50, prev_hh50, curr_ll50, prev_ll50)
    ):
        return None

    candle_time = int(candles["time"].iloc[idx])
    timestamp = pd.to_datetime(candle_time, unit="s", utc=True).isoformat()

    buy_cross = prev_close <= prev_hh50 and curr_close > curr_hh50
    sell_cross = prev_close >= prev_ll50 and curr_close < curr_ll50

    if buy_cross and curr_close > curr_sma:
        return {
            "symbol": symbol,
            "signal": "BUY",
            "price": round(float(curr_close), 2),
            "timeframe": timeframe,
            "timestamp": timestamp,
            "candle_time": candle_time,
        }

    if sell_cross and curr_close < curr_sma:
        return {
            "symbol": symbol,
            "signal": "SELL",
            "price": round(float(curr_close), 2),
            "timeframe": timeframe,
            "timestamp": timestamp,
            "candle_time": candle_time,
        }

    return None


def _append_if_alternating(
    signals: list[dict[str, Any]],
    candidate: dict[str, Any] | None,
    last_type: str | None,
) -> str | None:
    """Keep only alternating BUY/SELL — no repeat until opposite fires."""
    if candidate is None:
        return last_type
    if candidate["signal"] == last_type:
        return last_type
    signals.append(candidate)
    return candidate["signal"]


def detect_all_signals(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
    symbol: str,
    timeframe: str,
) -> list[dict[str, Any]]:
    """Find alternating BUY/SELL crossovers across candle history (for chart markers)."""
    signals: list[dict[str, Any]] = []
    last_type: str | None = None
    for idx in range(1, len(candles)):
        signal = _signal_at_index(
            candles, sma84, hh50, ll50, idx, symbol, timeframe
        )
        last_type = _append_if_alternating(signals, signal, last_type)
    return signals


def _closed_bar_slice(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
) -> tuple[pd.DataFrame, pd.Series, pd.Series, pd.Series]:
    """Exclude the in-progress (forming) bar from signal evaluation."""
    if len(candles) <= 1:
        return candles.iloc[0:0], sma84.iloc[0:0], hh50.iloc[0:0], ll50.iloc[0:0]
    return (
        candles.iloc[:-1].reset_index(drop=True),
        sma84.iloc[:-1].reset_index(drop=True),
        hh50.iloc[:-1].reset_index(drop=True),
        ll50.iloc[:-1].reset_index(drop=True),
    )


def detect_signal(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Detect BUY/SELL on the latest closed candle only (matches TradingView)."""
    closed_candles, closed_sma, closed_hh, closed_ll = _closed_bar_slice(
        candles, sma84, hh50, ll50
    )
    if len(closed_candles) < 2:
        return None

    all_signals = detect_all_signals(
        closed_candles, closed_sma, closed_hh, closed_ll, symbol, timeframe
    )
    if not all_signals:
        return None

    latest = all_signals[-1]
    last_closed_time = int(closed_candles["time"].iloc[-1])
    if latest.get("candle_time") != last_closed_time:
        return None

    logger.info("%s signal generated: %s", latest["signal"], latest)
    return latest


def signal_reasons(side: str) -> list[str]:
    if side == "BUY":
        return ["Close > HH50", "Close > SMA84"]
    return ["Close < LL50", "Close < SMA84"]


def build_signal_quality(
    signal: dict[str, Any],
    hh50: float,
    ll50: float,
    timeframe: str,
) -> dict[str, Any]:
    from app.trade_planner import build_trade_plan

    plan = build_trade_plan(signal["signal"], float(signal["price"]), hh50, ll50)
    return {
        "timeframe": timeframe,
        "side": plan.side,
        "entry": plan.entry,
        "stop_loss": plan.stop_loss,
        "take_profit": plan.take_profit,
        "risk_reward": plan.risk_reward,
        "reasons": signal_reasons(plan.side),
        "timestamp": signal.get("timestamp"),
        "candle_time": signal.get("candle_time"),
    }


def generate_signals_for_pair(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
    symbol: str,
    timeframe: str,
) -> dict[str, Any] | None:
    """Wrapper for latest-bar signal detection."""
    return detect_signal(candles, sma84, hh50, ll50, symbol, timeframe)
