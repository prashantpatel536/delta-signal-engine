"""SOL Reversal backtest — reuses strategy.py + simulation.py (same as paper)."""

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
from app.market_data import delta_client
from app.strategies.sol_reversal.ha import to_heikin_ashi
from app.strategies.sol_reversal.indicators import compute_atr
from app.strategies.sol_reversal.repositories import SolSettingsRepository
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.simulation import open_position, pnl_at_price, process_bar
from app.strategies.sol_reversal.strategy import detect_signal_at_index

SYMBOL = "SOLUSDT"


def _apply_slippage(price: float, side: str, is_entry: bool, slippage_pct: float) -> float:
    slip = slippage_pct / 100.0
    if side == "BUY":
        return price * (1 + slip) if is_entry else price * (1 - slip)
    return price * (1 - slip) if is_entry else price * (1 + slip)


def _commission_cost(notional: float, commission_pct: float) -> float:
    return notional * commission_pct / 100.0


def run_sol_backtest(config: dict[str, Any]) -> dict[str, Any]:
    symbol = config.get("symbol", SYMBOL)
    timeframe = config.get("timeframe", "5m")
    start_date = config["start_date"]
    end_date = config["end_date"]
    initial_capital = float(config.get("initial_capital", 1000))
    commission_pct = float(config.get("commission_pct", 0.05))
    slippage_pct = float(config.get("slippage_pct", 0.02))

    settings = {**DEFAULT_SETTINGS, **config.get("settings", {})}
    if config.get("use_current_settings", True):
        settings = {**settings, **SolSettingsRepository().get_all()}

    ohlc = get_candles(symbol, timeframe, start_date, end_date)
    if ohlc.empty:
        raise ValueError("No candle data for the selected range")

    display_df, _ = delta_client.resolve_ohlc_candles(ohlc, symbol, timeframe)
    ha = to_heikin_ashi(display_df)
    atr = compute_atr(ha, int(settings.get("atr_period", 14)))

    equity = initial_capital
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    trade_num = 0

    # Bar-by-bar replay — only closed bars, no look-ahead
    for idx in range(1, len(ha)):
        bar_time = int(ha.iloc[idx]["time"])
        ohlc_row = display_df.iloc[idx]
        high = float(ohlc_row["high"])
        low = float(ohlc_row["low"])
        close = float(ohlc_row["close"])

        if position:
            position, closed = process_bar(
                position,
                bar_time=bar_time,
                high=high,
                low=low,
                close=close,
                settings=settings,
            )
            if closed:
                exit_px = _apply_slippage(closed["exit_price"], closed["side"], False, slippage_pct)
                qty = float(closed["quantity"])
                closed["exit_price"] = round(exit_px, 4)
                pnl_usd, move_pct = pnl_at_price(
                    {"side": closed["side"], "entry": closed["entry_price"], "quantity": closed["quantity"]},
                    exit_px,
                )
                comm = _commission_cost(qty * exit_px, commission_pct)
                pnl_usd -= comm
                equity += pnl_usd
                trade_num += 1
                trades.append({
                    **closed,
                    "trade_num": trade_num,
                    "pnl_usd": round(pnl_usd, 4),
                    "price_move_pct": move_pct,
                })

        if position is None and idx >= 1:
            signal = detect_signal_at_index(ha, settings, idx, atr=atr)
            if signal:
                raw_entry = float(ha.iloc[idx]["close"])
                entry = _apply_slippage(raw_entry, signal, True, slippage_pct)
                position = open_position(
                    signal, entry, bar_time, settings, equity, symbol=symbol
                )
                if position:
                    comm = _commission_cost(
                        float(position["quantity"]) * entry, commission_pct
                    )
                    equity -= comm

    equity_curve = build_equity_curve(initial_capital, trades)
    stats = aggregate_statistics(initial_capital, equity, trades, equity_curve)

    return {
        "strategy_id": "sol_reversal",
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
        "bar_count": len(ha),
    }


class SolBacktestAdapter:
    strategy_id = "sol_reversal"
    display_name = "SOL Reversal Engine"
    default_symbol = SYMBOL
    default_timeframe = "5m"

    def get_settings(self) -> dict[str, Any]:
        return SolSettingsRepository().get_all()

    def run_backtest(self, config: dict[str, Any]) -> dict[str, Any]:
        return run_sol_backtest(config)


sol_backtester = SolBacktestAdapter()
