"""BTC Trend backtest adapter — uses signals.py + trade_planner (read-only)."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.backtest.candle_store import get_candles
from app.backtest.metrics import (
    aggregate_statistics,
    build_drawdown_series,
    build_equity_curve,
    build_monthly_report,
    build_performance_insights,
)
from app.indicators import calculate_indicators
from app.market_data import delta_client
from app.paper_trader import calculate_pnl
from app.services.runtime_settings import get_signal_timeframe
from app.signals import _signal_at_index
from app.trade_planner import build_trade_plan
from app.strategies.sol_reversal.simulation import size_position

SYMBOL = "BTCUSDT"


def _apply_slippage(price: float, side: str, is_entry: bool, slippage_pct: float) -> float:
    slip = slippage_pct / 100.0
    if side == "BUY":
        return price * (1 + slip) if is_entry else price * (1 - slip)
    return price * (1 - slip) if is_entry else price * (1 + slip)


def run_btc_backtest(config: dict[str, Any]) -> dict[str, Any]:
    symbol = config.get("symbol", SYMBOL)
    timeframe = config.get("timeframe", config.get("signal_timeframe", "5m"))
    start_date = config["start_date"]
    end_date = config["end_date"]
    initial_capital = float(config.get("initial_capital", 1000))
    commission_pct = float(config.get("commission_pct", 0.05))
    slippage_pct = float(config.get("slippage_pct", 0.02))
    leverage = float(config.get("leverage", 25))
    position_size_pct = float(config.get("position_size_pct", 50))

    settings = {
        "leverage": leverage,
        "position_size_pct": position_size_pct,
        "take_profit_pct": config.get("take_profit_pct"),
        "stop_loss_pct": config.get("stop_loss_pct"),
    }

    ohlc = get_candles(symbol, timeframe, start_date, end_date)
    if ohlc.empty:
        raise ValueError("No candle data for the selected range")

    display_df, _ = delta_client.resolve_ohlc_candles(ohlc, symbol, timeframe)
    sma84, hh50, ll50 = calculate_indicators(display_df)

    equity = initial_capital
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    trade_num = 0
    last_side: str | None = None

    sizing_settings = {"leverage": leverage, "position_size_pct": position_size_pct}

    for idx in range(1, len(display_df)):
        row = display_df.iloc[idx]
        bar_time = int(row["time"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if position:
            side = position["side"]
            entry = float(position["entry"])
            if side == "BUY":
                position["mfe_pct"] = max(position.get("mfe_pct", 0), (high - entry) / entry * 100)
                position["mae_pct"] = min(position.get("mae_pct", 0), (low - entry) / entry * 100)
            else:
                position["mfe_pct"] = max(position.get("mfe_pct", 0), (entry - low) / entry * 100)
                position["mae_pct"] = min(position.get("mae_pct", 0), (entry - high) / entry * 100)
            position["bars_held"] = int(position.get("bars_held", 0)) + 1

            sl = float(position["stop_loss"])
            tp = float(position["take_profit"])
            exit_price = None
            reason = None
            if side == "BUY":
                if low <= sl:
                    exit_price, reason = sl, "SL"
                elif high >= tp:
                    exit_price, reason = tp, "TP"
            else:
                if high >= sl:
                    exit_price, reason = sl, "SL"
                elif low <= tp:
                    exit_price, reason = tp, "TP"

            if exit_price is not None:
                exit_px = _apply_slippage(exit_price, side, False, slippage_pct)
                pnl = calculate_pnl(side, float(position["entry"]), exit_px, float(position["quantity"]))
                comm = float(position["quantity"]) * exit_px * commission_pct / 100
                pnl -= comm
                equity += pnl
                trade_num += 1
                entry = float(position["entry"])
                move = (exit_px - entry) / entry * 100 if side == "BUY" else (entry - exit_px) / entry * 100
                trades.append({
                    "trade_num": trade_num,
                    "side": side,
                    "entry_time": position["entry_time"],
                    "exit_time": bar_time,
                    "entry_price": entry,
                    "exit_price": round(exit_px, 4),
                    "price_move_pct": round(move, 4),
                    "pnl_usd": round(pnl, 4),
                    "bars_held": position.get("bars_held", 0),
                    "exit_reason": reason,
                    "mfe_pct": position.get("mfe_pct", 0),
                    "mae_pct": position.get("mae_pct", 0),
                    "stop_loss": sl,
                    "take_profit": tp,
                })
                position = None

        if position is None:
            sig = _signal_at_index(display_df, sma84, hh50, ll50, idx)
            if sig and sig != last_side:
                if pd.isna(hh50.iloc[idx]) or pd.isna(ll50.iloc[idx]):
                    continue
                hh_val = float(hh50.iloc[idx])
                ll_val = float(ll50.iloc[idx])
                entry_raw = close
                entry = _apply_slippage(entry_raw, sig, True, slippage_pct)
                plan = build_trade_plan(sig, entry, hh_val, ll_val)
                sized = size_position(equity, entry, sizing_settings, symbol)
                if not sized:
                    continue
                comm = float(sized["quantity"]) * entry * commission_pct / 100
                equity -= comm
                position = {
                    "side": sig,
                    "entry": entry,
                    "entry_time": bar_time,
                    "stop_loss": plan["stop_loss"],
                    "take_profit": plan["take_profit"],
                    "quantity": sized["quantity"],
                    "bars_held": 0,
                    "mfe_pct": 0.0,
                    "mae_pct": 0.0,
                }
                last_side = sig

    equity_curve = build_equity_curve(initial_capital, trades)
    stats = aggregate_statistics(initial_capital, equity, trades, equity_curve)

    return {
        "strategy_id": "btc_trend",
        "symbol": symbol,
        "timeframe": timeframe,
        "start_date": start_date,
        "end_date": end_date,
        "settings": settings,
        "config": config,
        "statistics": stats,
        "trades": trades,
        "equity_curve": equity_curve,
        "drawdown_series": build_drawdown_series(equity_curve),
        "monthly_report": build_monthly_report(trades),
        "performance": build_performance_insights(initial_capital, trades, equity_curve),
        "bar_count": len(display_df),
    }


class BtcTrendBacktestAdapter:
    strategy_id = "btc_trend"
    display_name = "BTC Trend Engine"
    default_symbol = SYMBOL
    default_timeframe = "5m"

    def get_settings(self) -> dict[str, Any]:
        return {
            "signal_timeframe": get_signal_timeframe(),
            "leverage": 25,
            "position_size_pct": 50,
        }

    def run_backtest(self, config: dict[str, Any]) -> dict[str, Any]:
        return run_btc_backtest(config)


btc_backtester = BtcTrendBacktestAdapter()
