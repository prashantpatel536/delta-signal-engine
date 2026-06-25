"""Configurable overall score for BTC strategy optimization results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OptimizerScoreWeights:
    """Tune ranking without changing backtest logic."""

    profit_factor_multiplier: float = 100.0
    return_pct_multiplier: float = 1.0
    drawdown_pct_penalty: float = 5.0


DEFAULT_SCORE_WEIGHTS = OptimizerScoreWeights()


def overall_score(
    metrics: dict[str, Any],
    weights: OptimizerScoreWeights | None = None,
) -> float:
    """
    Default: Score = (ProfitFactor × 100) + Return% − (MaxDrawdown% × 5)
    """
    w = weights or DEFAULT_SCORE_WEIGHTS
    pf = float(metrics.get("profit_factor") or 0.0)
    ret = float(metrics.get("return_pct") or 0.0)
    dd = abs(float(metrics.get("max_drawdown_pct") or 0.0))
    return round(
        pf * w.profit_factor_multiplier
        + ret * w.return_pct_multiplier
        - dd * w.drawdown_pct_penalty,
        4,
    )
