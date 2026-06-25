"""Configurable scoring and ranking filters for BTC strategy optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RANK_DISQUALIFIED_SCORE = -999_999.0

MIN_TRADES_FOR_SCORE = 20
MIN_PROFIT_FACTOR = 1.0
MIN_RETURN_PCT = 0.0  # must be strictly greater
MIN_WIN_RATE = 30.0


@dataclass(frozen=True)
class OptimizerScoreWeights:
    """Tune ranking without changing backtest logic."""

    profit_factor_multiplier: float = 100.0
    return_pct_multiplier: float = 2.0
    win_rate_multiplier: float = 1.0
    drawdown_divisor_multiplier: float = 5.0
    min_drawdown_pct: float = 0.01


DEFAULT_SCORE_WEIGHTS = OptimizerScoreWeights()


def is_rankable(metrics: dict[str, Any]) -> bool:
    """Only strategies passing quality gates can be ranked as Best / Top 20."""
    trades = int(metrics.get("trade_count") or 0)
    pf = float(metrics.get("profit_factor") or 0.0)
    ret = float(metrics.get("return_pct") or 0.0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    if trades < MIN_TRADES_FOR_SCORE:
        return False
    if pf < MIN_PROFIT_FACTOR:
        return False
    if ret <= MIN_RETURN_PCT:
        return False
    if win_rate < MIN_WIN_RATE:
        return False
    return True


def rank_disqualify_reason(metrics: dict[str, Any]) -> str | None:
    trades = int(metrics.get("trade_count") or 0)
    pf = float(metrics.get("profit_factor") or 0.0)
    ret = float(metrics.get("return_pct") or 0.0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    if trades < MIN_TRADES_FOR_SCORE:
        return f"Trades < {MIN_TRADES_FOR_SCORE}"
    if pf < MIN_PROFIT_FACTOR:
        return f"Profit Factor < {MIN_PROFIT_FACTOR}"
    if ret <= MIN_RETURN_PCT:
        return "Return <= 0%"
    if win_rate < MIN_WIN_RATE:
        return f"Win Rate < {MIN_WIN_RATE}%"
    return None


def overall_score(
    metrics: dict[str, Any],
    weights: OptimizerScoreWeights | None = None,
) -> float:
    """
    if trades < 20: score = -999999
    else: score = (PF×100 + Return%×2 + WinRate) / (MaxDrawdown% × 5)
    """
    trades = int(metrics.get("trade_count") or 0)
    if trades < MIN_TRADES_FOR_SCORE:
        return RANK_DISQUALIFIED_SCORE

    w = weights or DEFAULT_SCORE_WEIGHTS
    pf = float(metrics.get("profit_factor") or 0.0)
    ret = float(metrics.get("return_pct") or 0.0)
    win_rate = float(metrics.get("win_rate") or 0.0)
    dd = abs(float(metrics.get("max_drawdown_pct") or 0.0))
    dd = max(dd, w.min_drawdown_pct)

    numerator = (
        pf * w.profit_factor_multiplier
        + ret * w.return_pct_multiplier
        + win_rate * w.win_rate_multiplier
    )
    denominator = dd * w.drawdown_divisor_multiplier
    return round(numerator / denominator, 4) if denominator > 0 else RANK_DISQUALIFIED_SCORE
