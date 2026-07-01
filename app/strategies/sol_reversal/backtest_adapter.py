"""SOL Reversal backtest — uses StrategyEngine (same as paper simulation + optimizer)."""

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
from app.strategies.sol_reversal.repositories import SolSettingsRepository
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.strategy_engine import ExecutionConfig, StrategyEngine

SYMBOL = "SOLUSDT"


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
    settings["initial_capital"] = initial_capital

    ohlc = get_candles(symbol, timeframe, start_date, end_date)
    if ohlc.empty:
        raise ValueError("No candle data for the selected range")

    execution = ExecutionConfig(
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        symbol=symbol,
        timeframe=timeframe,
    )
    engine = StrategyEngine(settings, execution=execution, raw_ohlc=ohlc)
    engine.use_standard_execution()
    replay = engine.run()

    trades: list[dict[str, Any]] = []
    for i, tr in enumerate(replay["trades"], start=1):
        trades.append({**tr, "trade_num": i})

    equity = float(replay["final_equity"])
    equity_curve = build_equity_curve(initial_capital, trades)
    stats = aggregate_statistics(initial_capital, equity, trades, equity_curve)
    ha = engine.ha_candles

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
        "bar_count": len(ha) if ha is not None else 0,
        "diagnostics": {
            "candle_mode": "heikin_ashi",
            "note": "Matches Pine on TradingView when chart type is Heikin Ashi",
            "bars_in_range": len(ha) if ha is not None else 0,
            "buy_conditions_unfiltered": len(replay["raw_conditions"]),
            "trades_executed": len(trades),
            "condition_times": [s["time"] for s in replay["raw_conditions"]],
            "pine_signals_unfiltered": len(replay["raw_conditions"]),
            "signal_times": [s["time"] for s in replay["raw_conditions"]],
            "engine": replay.get("execution"),
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
