"""Validation mode — compare direct StrategyEngine vs optimizer worker path."""

from __future__ import annotations

from typing import Any

from app.backtest.candle_store import get_candles
from app.backtest.metrics import aggregate_statistics, build_equity_curve
from app.strategies.sol_reversal.optimizer_worker import (
    arrays_to_ohlc,
    ohlc_to_arrays,
    run_strategy_engine_iteration,
)
from app.strategies.sol_reversal.repositories import SolSettingsRepository
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS
from app.strategies.sol_reversal.strategy_engine import ExecutionConfig, StrategyEngine


def _trade_signature(tr: dict[str, Any]) -> dict[str, Any]:
    return {
        "entry_time": int(tr.get("entry_time") or 0),
        "exit_time": int(tr.get("exit_time") or 0),
        "exit_reason": tr.get("exit_reason"),
        "pnl_usd": round(float(tr.get("pnl_usd") or 0), 4),
        "entry_price": round(float(tr.get("entry_price") or 0), 4),
        "exit_price": round(float(tr.get("exit_price") or 0), 4),
    }


def run_paper_engine_path(config: dict[str, Any]) -> dict[str, Any]:
    """Direct StrategyEngine run (paper / backtest path)."""
    symbol = config.get("symbol", "SOLUSDT")
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
        raise ValueError("No candle data for validation range")

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
    trades = list(replay["trades"])
    equity_curve = build_equity_curve(initial_capital, trades)
    stats = aggregate_statistics(initial_capital, float(replay["final_equity"]), trades, equity_curve)

    return {
        "engine_path": "paper_strategy_engine",
        "trade_count": len(trades),
        "final_equity": round(float(replay["final_equity"]), 4),
        "statistics": stats,
        "trades": trades,
        "execution": replay.get("execution"),
    }


def run_optimizer_engine_path(config: dict[str, Any]) -> dict[str, Any]:
    """Optimizer worker path — must delegate to the same StrategyEngine."""
    symbol = config.get("symbol", "SOLUSDT")
    timeframe = config.get("timeframe", "5m")
    start_date = config["start_date"]
    end_date = config["end_date"]

    settings = {**DEFAULT_SETTINGS, **config.get("settings", {})}
    if config.get("use_current_settings", True):
        settings = {**settings, **SolSettingsRepository().get_all()}

    ohlc = get_candles(symbol, timeframe, start_date, end_date)
    if ohlc.empty:
        raise ValueError("No candle data for validation range")

    # Only pass optimizable overrides, not full settings blob
    param_overrides = {
        k: settings[k]
        for k in settings
        if k not in ("debug_mode", "debug_log_bar_evals", "show_raw_ha_conditions")
    }

    payload = {
        "ohlc": ohlc_to_arrays(ohlc),
        "base_settings": DEFAULT_SETTINGS,
        "param_overrides": param_overrides,
        "initial_capital": float(config.get("initial_capital", 1000)),
        "commission_pct": float(config.get("commission_pct", 0.05)),
        "slippage_pct": float(config.get("slippage_pct", 0.02)),
        "symbol": symbol,
        "timeframe": timeframe,
    }
    return run_strategy_engine_iteration(payload)


def compare_engine_results(
    paper: dict[str, Any],
    optimizer: dict[str, Any],
) -> dict[str, Any]:
    """Build detailed mismatch report."""
    mismatches: list[dict[str, Any]] = []

    if paper["trade_count"] != optimizer["trade_count"]:
        mismatches.append({
            "field": "trade_count",
            "paper": paper["trade_count"],
            "optimizer": optimizer["trade_count"],
        })

    if abs(paper["final_equity"] - optimizer["final_equity"]) > 0.01:
        mismatches.append({
            "field": "final_equity",
            "paper": paper["final_equity"],
            "optimizer": optimizer["final_equity"],
            "delta": round(paper["final_equity"] - optimizer["final_equity"], 4),
        })

    paper_trades = [_trade_signature(t) for t in paper.get("trades", [])]
    opt_trades = [_trade_signature(t) for t in optimizer.get("trades", [])]
    max_len = max(len(paper_trades), len(opt_trades))
    for i in range(max_len):
        pt = paper_trades[i] if i < len(paper_trades) else None
        ot = opt_trades[i] if i < len(opt_trades) else None
        if pt is None:
            mismatches.append({"field": f"trade_{i + 1}", "paper": None, "optimizer": ot})
            continue
        if ot is None:
            mismatches.append({"field": f"trade_{i + 1}", "paper": pt, "optimizer": None})
            continue
        for key in ("entry_time", "exit_time", "exit_reason", "pnl_usd"):
            if pt.get(key) != ot.get(key):
                mismatches.append({
                    "field": f"trade_{i + 1}.{key}",
                    "paper": pt.get(key),
                    "optimizer": ot.get(key),
                })

    paper_stats = paper.get("statistics") or {}
    opt_stats = optimizer.get("statistics") or {}
    for key in ("net_profit", "total_return_pct", "profit_factor", "win_rate"):
        pv = paper_stats.get(key)
        ov = opt_stats.get(key)
        if pv is None or ov is None:
            continue
        if pv != ov:
            mismatches.append({
                "field": f"statistics.{key}",
                "paper": pv,
                "optimizer": ov,
            })

    ok = len(mismatches) == 0
    report_lines = []
    if ok:
        report_lines.append("VALIDATION PASSED — Paper Strategy Engine and Optimizer Engine are identical.")
        report_lines.append(
            f"Trades: {paper['trade_count']} | Equity: ${paper['final_equity']}"
        )
    else:
        report_lines.append("VALIDATION FAILED — mismatch between Paper Strategy Engine and Optimizer Engine:")
        for m in mismatches:
            report_lines.append(
                f"  • {m['field']}: paper={m.get('paper')!r} optimizer={m.get('optimizer')!r}"
                + (f" (delta={m['delta']})" if "delta" in m else "")
            )

    return {
        "ok": ok,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "report": "\n".join(report_lines),
        "paper": {
            "engine_path": paper.get("engine_path"),
            "trade_count": paper["trade_count"],
            "final_equity": paper["final_equity"],
        },
        "optimizer": {
            "engine_path": optimizer.get("engine_path"),
            "trade_count": optimizer["trade_count"],
            "final_equity": optimizer["final_equity"],
        },
    }


def validate_engine_parity(config: dict[str, Any]) -> dict[str, Any]:
    """Run one parameter set through both engine paths and compare."""
    paper = run_paper_engine_path(config)
    optimizer = run_optimizer_engine_path(config)
    comparison = compare_engine_results(paper, optimizer)
    return {
        **comparison,
        "config": config,
        "paper_trades": paper.get("trades"),
        "optimizer_trades": optimizer.get("trades"),
    }
