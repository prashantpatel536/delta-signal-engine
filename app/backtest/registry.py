"""Strategy registry for generic backtesting."""

from __future__ import annotations

from typing import Any, Callable, Protocol

import pandas as pd


class StrategyBacktester(Protocol):
    strategy_id: str
    display_name: str
    default_symbol: str
    default_timeframe: str

    def get_settings(self) -> dict[str, Any]: ...

    def run_backtest(self, config: dict[str, Any]) -> dict[str, Any]: ...


_REGISTRY: dict[str, StrategyBacktester] = {}


def register(strategy: StrategyBacktester) -> None:
    _REGISTRY[strategy.strategy_id] = strategy


def get(strategy_id: str) -> StrategyBacktester:
    if strategy_id not in _REGISTRY:
        raise KeyError(f"Unknown strategy '{strategy_id}'")
    return _REGISTRY[strategy_id]


def list_strategies() -> list[dict[str, str]]:
    return [
        {
            "id": s.strategy_id,
            "name": s.display_name,
            "default_symbol": s.default_symbol,
            "default_timeframe": s.default_timeframe,
        }
        for s in _REGISTRY.values()
    ]


def _load_adapters() -> None:
    from app.strategies.sol_reversal.backtest_adapter import sol_backtester
    from app.backtest.adapters.btc_trend import btc_backtester

    register(sol_backtester)
    register(btc_backtester)


def ensure_registry() -> None:
    if not _REGISTRY:
        _load_adapters()
