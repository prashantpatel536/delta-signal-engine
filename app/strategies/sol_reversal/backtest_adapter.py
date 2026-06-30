"""SOL Reversal backtest — Heikin Ashi candles (matches TV HA chart + dashboard)."""

from __future__ import annotations

from typing import Any

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
from app.strategies.sol_reversal.strategy import detect_signal_at_index, scan_signals

SYMBOL = "SOLUSDT"


def _apply_slippage(price: float, is_entry: bool, slippage_pct: float) -> float:
    slip = slippage_pct / 100.0
    if is_entry:
        return price * (1 + slip)
    return price * (1 - slip)


def _commission_cost(notional: float, commission_pct: float) -> float:
    return notional * commission_pct / 100.0


def _close_trade(
    closed: dict[str, Any],
    *,
    slippage_pct: float,
    commission_pct: float,
    equity: float,
) -> tuple[dict[str, Any], float]:
    exit_px = _apply_slippage(closed["exit_price"], False, slippage_pct)
    qty = float(closed["quantity"])
    closed = {**closed, "exit_price": round(exit_px, 4)}
    pnl_usd, move_pct = pnl_at_price(
        {"side": "BUY", "entry": closed["entry_price"], "quantity": qty},
        exit_px,
    )
    pnl_usd -= _commission_cost(qty * exit_px, commission_pct)
    equity += pnl_usd
    return {
        **closed,
        "pnl_usd": round(pnl_usd, 4),
        "price_move_pct": move_pct,
    }, equity


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
    all_signals = scan_signals(ha, settings, atr=atr)

    equity = initial_capital
    position: dict[str, Any] | None = None
    trades: list[dict[str, Any]] = []
    trade_num = 0

    for idx in range(1, len(ha)):
        bar_time = int(ha.iloc[idx]["time"])
        row = ha.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

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
                closed, equity = _close_trade(
                    closed, slippage_pct=slippage_pct, commission_pct=commission_pct, equity=equity
                )
                trade_num += 1
                trades.append({**closed, "trade_num": trade_num})

        if position is None:
            signal = detect_signal_at_index(ha, settings, idx, atr=atr)
            if signal:
                entry = _apply_slippage(close, True, slippage_pct)
                position = open_position("BUY", entry, bar_time, settings, equity, symbol=symbol)
                if position:
                    equity -= _commission_cost(float(position["quantity"]) * entry, commission_pct)
                    position, closed = process_bar(
                        position,
                        bar_time=bar_time,
                        high=high,
                        low=low,
                        close=close,
                        settings=settings,
                    )
                    if closed:
                        closed, equity = _close_trade(
                            closed, slippage_pct=slippage_pct, commission_pct=commission_pct, equity=equity
                        )
                        trade_num += 1
                        trades.append({**closed, "trade_num": trade_num})

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
        "diagnostics": {
            "candle_mode": "heikin_ashi",
            "note": "Matches Pine on TradingView when chart type is Heikin Ashi",
            "bars_in_range": len(ha),
            "pine_signals_unfiltered": len(all_signals),
            "trades_executed": len(trades),
            "signal_times": [s["time"] for s in all_signals],
        },
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
