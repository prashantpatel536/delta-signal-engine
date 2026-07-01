"""Unified SOL Reversal strategy engine — single source for paper, backtest, optimizer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.market_data import delta_client
from app.strategies.sol_reversal.ha import to_heikin_ashi
from app.strategies.sol_reversal.indicators import compute_atr
from app.strategies.sol_reversal.simulation import (
    _append_exit,
    open_position,
    pnl_at_price,
    process_bar,
)
from app.strategies.sol_reversal import strategy as strategy_mod


@dataclass
class ExecutionConfig:
    initial_capital: float = 1000.0
    commission_pct: float = 0.05
    slippage_pct: float = 0.02
    symbol: str = "SOLUSDT"
    timeframe: str = "5m"


def apply_slippage(price: float, is_entry: bool, slippage_pct: float) -> float:
    slip = slippage_pct / 100.0
    if is_entry:
        return price * (1 + slip)
    return price * (1 - slip)


def commission_cost(notional: float, commission_pct: float) -> float:
    return notional * commission_pct / 100.0


class StrategyEngine:
    """
    Bar-by-bar SOL reversal simulation (HA candles, next-bar open fills by default).

    Paper trading, backtest, and optimizer must all use this class.
    Call ``reset()`` (or create a new instance) before each parameter combination.
    """

    def __init__(
        self,
        settings: dict[str, Any],
        *,
        execution: ExecutionConfig | None = None,
        raw_ohlc: pd.DataFrame | None = None,
        ha_candles: pd.DataFrame | None = None,
        symbol: str = "SOLUSDT",
        timeframe: str = "5m",
    ) -> None:
        self.settings = dict(settings)
        self.execution = execution or ExecutionConfig(
            initial_capital=float(settings.get("initial_capital", 1000)),
            symbol=symbol,
            timeframe=timeframe,
        )
        self._raw_ohlc = raw_ohlc.copy() if raw_ohlc is not None else None
        self._ha: pd.DataFrame | None = ha_candles.copy() if ha_candles is not None else None
        self._atr: pd.Series | None = None
        self._raw_conditions: list[dict[str, Any]] = []
        self._entry_price_at: Callable[[int, float], float] | None = None
        self._on_entry: Callable[[dict[str, Any]], None] | None = None
        self._on_open: Callable[[dict[str, Any]], float | None] | None = None
        self._on_close: Callable[[dict[str, Any]], None] | None = None
        self.reset()

    def set_execution_hooks(
        self,
        *,
        entry_price_at: Callable[[int, float], float] | None = None,
        on_entry: Callable[[dict[str, Any]], None] | None = None,
        on_open: Callable[[dict[str, Any]], float | None] | None = None,
        on_close: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._entry_price_at = entry_price_at
        self._on_entry = on_entry
        self._on_open = on_open
        self._on_close = on_close

    def use_standard_execution(self) -> None:
        """Apply slippage + commission using ``ExecutionConfig`` (backtest / optimizer)."""
        slip = self.execution.slippage_pct
        comm = self.execution.commission_pct

        def entry_price_at(_idx: int, price: float) -> float:
            return apply_slippage(price, True, slip)

        def on_open(position: dict[str, Any]) -> float:
            cost = commission_cost(float(position["quantity"]) * float(position["entry"]), comm)
            self.equity -= cost
            return -cost

        def on_close(closed: dict[str, Any]) -> None:
            exit_px = apply_slippage(float(closed["exit_price"]), False, slip)
            qty = float(closed["quantity"])
            pnl_usd, move_pct = pnl_at_price(
                {"side": "BUY", "entry": closed["entry_price"], "quantity": qty},
                exit_px,
            )
            pnl_usd -= commission_cost(qty * exit_px, comm)
            self.equity += pnl_usd
            closed["exit_price"] = round(exit_px, 4)
            closed["pnl_usd"] = round(pnl_usd, 4)
            closed["price_move_pct"] = move_pct

        self.set_execution_hooks(
            entry_price_at=entry_price_at,
            on_open=on_open,
            on_close=on_close,
        )

    def reset(self, settings: dict[str, Any] | None = None) -> None:
        """Reset ALL mutable strategy state for a new parameter combination."""
        if settings is not None:
            self.settings = dict(settings)

        self.position: dict[str, Any] | None = None
        self.equity = float(self.execution.initial_capital)
        self.trades: list[dict[str, Any]] = []
        self.entries: list[dict[str, Any]] = []
        self.exits: list[dict[str, Any]] = []
        self.trade_num = 0
        self.pending_signal = False

        self._atr = None
        self._raw_conditions = []
        if self._raw_ohlc is not None:
            display_df, _ = delta_client.resolve_ohlc_candles(
                self._raw_ohlc,
                self.execution.symbol,
                self.execution.timeframe,
            )
            self._ha = to_heikin_ashi(display_df)
        self._rebuild_indicators()

    def _rebuild_indicators(self) -> None:
        if self._ha is None or self._ha.empty:
            self._atr = None
            self._raw_conditions = []
            return
        self._atr = compute_atr(self._ha, int(self.settings.get("atr_period", 14)))
        self._raw_conditions = strategy_mod.scan_buy_conditions(self._ha, self.settings, atr=self._atr)

    @property
    def ha_candles(self) -> pd.DataFrame | None:
        return self._ha

    @property
    def atr(self) -> pd.Series | None:
        return self._atr

    def _close_position(self, closed: dict[str, Any]) -> None:
        if self._on_close:
            self._on_close(closed)
        else:
            self.equity += float(closed["pnl_usd"])
        self.trade_num += 1
        _append_exit(self.exits, self.trades, closed, trade_num=self.trade_num)
        self.position = None

    def _open_at(
        self,
        idx: int,
        bar_time: int,
        entry_px: float,
        *,
        high: float,
        low: float,
        close: float,
        signal_bar: int,
    ) -> None:
        entry = entry_px if self._entry_price_at is None else self._entry_price_at(idx, entry_px)
        self.position = open_position(
            "BUY",
            entry,
            bar_time,
            self.settings,
            self.equity,
            self.execution.symbol,
        )
        if not self.position:
            self.pending_signal = False
            return
        if self._on_open:
            delta = self._on_open(self.position)
            if delta:
                self.equity += float(delta)
        entry_rec = {
            "candle_time": bar_time,
            "signal": "BUY",
            "status": "ENTRY",
            "entry_price": entry,
            "bar_index": idx,
            "signal_bar_index": signal_bar,
        }
        self.entries.append(entry_rec)
        if self._on_entry:
            self._on_entry(entry_rec)
        self.pending_signal = False
        self.position, closed = process_bar(
            self.position,
            bar_time=bar_time,
            high=high,
            low=low,
            close=close,
            settings=self.settings,
        )
        if closed:
            self._close_position(closed)

    def process_bar_index(self, idx: int) -> None:
        """Process one closed HA bar by index (used by batch run and live stepping)."""
        if self._ha is None or idx < 1 or idx >= len(self._ha):
            return
        row = self._ha.iloc[idx]
        bar_time = int(row["time"])
        open_px = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        on_close_entry = bool(self.settings.get("process_orders_on_close", False))

        filled_this_bar = False
        if self.position is None and self.pending_signal:
            self._open_at(
                idx,
                bar_time,
                open_px,
                high=high,
                low=low,
                close=close,
                signal_bar=idx - 1,
            )
            filled_this_bar = self.position is not None or not self.pending_signal

        if self.position and not filled_this_bar:
            self.position, closed = process_bar(
                self.position,
                bar_time=bar_time,
                high=high,
                low=low,
                close=close,
                settings=self.settings,
            )
            if closed:
                self._close_position(closed)

        if (
            self.position is None
            and not self.pending_signal
            and strategy_mod.detect_buy_condition_at_index(self._ha, self.settings, idx, atr=self._atr)
        ):
            if on_close_entry:
                self._open_at(
                    idx,
                    bar_time,
                    close,
                    high=high,
                    low=low,
                    close=close,
                    signal_bar=idx,
                )
            else:
                self.pending_signal = True

    def run(self, *, reset: bool = True) -> dict[str, Any]:
        """Run full HA replay. Resets state first unless ``reset=False``."""
        if reset:
            self.reset()
        if self._ha is None or len(self._ha) < 2:
            return self.result()
        for idx in range(1, len(self._ha)):
            self.process_bar_index(idx)
        return self.result()

    def result(self) -> dict[str, Any]:
        return {
            "entries": list(self.entries),
            "exits": list(self.exits),
            "raw_conditions": list(self._raw_conditions),
            "trades": list(self.trades),
            "final_equity": self.equity,
            "trade_count": len(self.trades),
            "candle_mode": "heikin_ashi",
            "execution": {
                "commission_pct": self.execution.commission_pct,
                "slippage_pct": self.execution.slippage_pct,
                "initial_capital": self.execution.initial_capital,
                "next_bar_open": not bool(self.settings.get("process_orders_on_close", False)),
            },
        }
