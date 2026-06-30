"""Candle helpers — Pine uses chart open/close (regular OHLC unless TV chart is HA)."""

from __future__ import annotations

import pandas as pd


def attach_candle_colors(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Pine: isRed = close < open, isGreen = close > open."""
    if ohlc.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "color"])
    out = ohlc.copy()
    out["color"] = out.apply(
        lambda r: "green" if float(r["close"]) > float(r["open"])
        else ("red" if float(r["close"]) < float(r["open"]) else "doji"),
        axis=1,
    )
    return out


def to_heikin_ashi(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Convert standard OHLC DataFrame to Heikin Ashi."""
    if ohlc.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume", "color"])

    df = ohlc.copy()
    ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
    ha_open = ha_close.copy()
    ha_open.iloc[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
    for i in range(1, len(df)):
        ha_open.iloc[i] = (ha_open.iloc[i - 1] + ha_close.iloc[i - 1]) / 2.0

    ha_high = pd.concat([df["high"], ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([df["low"], ha_open, ha_close], axis=1).min(axis=1)

    out = pd.DataFrame({
        "time": df["time"].values,
        "open": ha_open.astype(float),
        "high": ha_high.astype(float),
        "low": ha_low.astype(float),
        "close": ha_close.astype(float),
        "volume": df["volume"].astype(float) if "volume" in df.columns else 0.0,
    })
    out["color"] = out.apply(
        lambda r: "green" if r["close"] > r["open"] else ("red" if r["close"] < r["open"] else "doji"),
        axis=1,
    )
    return out
