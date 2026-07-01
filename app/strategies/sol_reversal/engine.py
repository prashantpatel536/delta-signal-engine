"""24/7 SOL Reversal strategy engine loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.strategies.sol_reversal.debug import (
    _trade_count,
    explain_signal_at_index,
    log_debug_event,
)
from app.strategies.sol_reversal.market import sol_market
from app.strategies.sol_reversal.paper import SolPaperService
from app.strategies.sol_reversal.repositories import SolEngineRepository, SolSettingsRepository
from app.strategies.sol_reversal.simulation import lock_debug_payload, preview_open_position
from app.strategies.sol_reversal.strategy import detect_buy_condition_at_index, levels_for_side, target_price_pcts

logger = logging.getLogger(__name__)


class SolReversalEngine:
    def __init__(self) -> None:
        self.paper = SolPaperService()
        self.settings_repo = SolSettingsRepository()
        self.engine_repo = SolEngineRepository()
        self._last_processed_candle: int | None = None
        self._pending_entry: bool = False

    def settings(self) -> dict[str, Any]:
        return self.settings_repo.get_all()

    def _monitor_bar(
        self,
        open_pos: dict[str, Any],
        *,
        idx: int,
        candle_time: int,
        settings: dict[str, Any],
        debug_on: bool,
    ) -> dict[str, Any] | None:
        ha_high, ha_low, ha_close, _ = sol_market.ha_bar_at(idx)
        closed = self.paper.monitor(
            open_pos,
            high=ha_high,
            low=ha_low,
            close=ha_close,
            settings=settings,
            bar_time=candle_time,
        )
        if debug_on:
            still = self.paper.positions.get_open()
            if still:
                log_debug_event("LOCK_DEBUG", lock_debug_payload(
                    self.paper._to_sim(still),
                    high=ha_high,
                    close=ha_close,
                    settings=settings,
                ))
            elif closed:
                log_debug_event("LOCK_DEBUG", {
                    **lock_debug_payload(
                        self.paper._to_sim(open_pos),
                        high=ha_high,
                        close=ha_close,
                        settings=settings,
                    ),
                    "trade_closed": True,
                    "exit_reason": closed.get("exit_reason"),
                })
        if closed:
            self.engine_repo.log("INFO", f"Closed BUY {closed['exit_reason']} pnl={closed['pnl_usd']}")
            if debug_on:
                log_debug_event("TRADE_CLOSE", {
                    "trade_num": _trade_count() + 1,
                    "position_id": closed.get("id"),
                    "side": "BUY",
                    "entry": closed.get("entry"),
                    "exit_price": closed.get("exit_price"),
                    "exit_reason": closed.get("exit_reason"),
                    "pnl_usd": closed.get("pnl_usd"),
                    "pnl_pct": closed.get("pnl_pct"),
                    "bars_held": closed.get("bars_held"),
                    "candle_time": candle_time,
                    "ha_bar": {"high": ha_high, "low": ha_low, "close": ha_close},
                    "lock_active": bool(closed.get("lock_active")),
                    "lock_stop": closed.get("lock_stop"),
                    "highest_profit_pct": closed.get("highest_profit_pct"),
                    "mfe_pct": closed.get("mfe_pct"),
                    "mae_pct": closed.get("mae_pct"),
                    "ohlc_source": "heikin_ashi",
                })
        return closed

    def on_closed_candle(self) -> None:
        engine_state = self.engine_repo.get()
        if not bool(engine_state.get("running", 1)):
            return

        idx = sol_market.closed_candle_index()
        if idx < 0:
            return
        ha = sol_market.get_ha()
        atr = sol_market.get_atr()
        candle_time = int(ha.iloc[idx]["time"])
        if self._last_processed_candle == candle_time:
            return

        if self._last_processed_candle is None:
            self._last_processed_candle = candle_time
            return

        self._last_processed_candle = candle_time

        settings = self.settings()
        ha_high, ha_low, ha_close, ha_open = sol_market.ha_bar_at(idx)
        debug_on = bool(settings.get("debug_mode"))

        explain = explain_signal_at_index(ha, settings, idx, atr=atr)
        if debug_on and (settings.get("debug_log_bar_evals") or explain.get("signal")):
            log_debug_event("BAR_EVAL", {
                **explain,
                "ohlc_source": "heikin_ashi",
                "ha_bar": {"open": ha_open, "high": ha_high, "low": ha_low, "close": ha_close},
            })

        open_pos = self.paper.positions.get_open()
        if open_pos:
            self._monitor_bar(open_pos, idx=idx, candle_time=candle_time, settings=settings, debug_on=debug_on)
            open_pos = self.paper.positions.get_open()

        on_close_entry = bool(settings.get("process_orders_on_close", False))

        if open_pos is None and self._pending_entry:
            self._pending_entry = False
            entry = ha_open
            tp, sl = levels_for_side("BUY", entry, settings)
            opened = self.paper.open_trade("BUY", entry, settings)
            if opened:
                self.engine_repo.log("INFO", f"Opened BUY @ {entry} (next-bar open fill)")
                self.engine_repo.update(last_signal="BUY")
                if debug_on:
                    log_debug_event("TRADE_OPEN", {
                        "position_id": opened.get("id"),
                        "side": "BUY",
                        "entry": entry,
                        "entry_time": candle_time,
                        "take_profit": tp,
                        "stop_loss": sl,
                        "fill_mode": "next_bar_open",
                        "ha_bar": {"high": ha_high, "low": ha_low, "close": ha_close, "open": ha_open},
                        "entry_price_source": "ha_open",
                    })
                still_open = self.paper.positions.get_open()
                if still_open:
                    self._monitor_bar(
                        still_open, idx=idx, candle_time=candle_time, settings=settings, debug_on=debug_on
                    )
            elif debug_on:
                log_debug_event("TRADE_OPEN_FAILED", {
                    "signal": "BUY",
                    "entry": entry,
                    "reason": "pending_fill_failed",
                })
            open_pos = self.paper.positions.get_open()

        buy_condition = explain.get("signal") or detect_buy_condition_at_index(ha, settings, idx, atr=atr)
        if open_pos is None and not self._pending_entry and buy_condition:
            if debug_on:
                log_debug_event("BUY_CONDITION", explain)
            if on_close_entry:
                entry = ha_close
                tp, sl = levels_for_side("BUY", entry, settings)
                opened = self.paper.open_trade(buy_condition, entry, settings)
                if opened:
                    self.engine_repo.log("INFO", f"Opened BUY @ {entry}")
                    self.engine_repo.update(last_signal=buy_condition)
                    if debug_on:
                        log_debug_event("TRADE_OPEN", {
                            "position_id": opened.get("id"),
                            "side": "BUY",
                            "entry": entry,
                            "entry_time": candle_time,
                            "take_profit": tp,
                            "stop_loss": sl,
                            "signal_eval": explain,
                            "fill_mode": "bar_close",
                            "ha_bar": {"high": ha_high, "low": ha_low, "close": ha_close},
                            "entry_price_source": "ha_close",
                        })
                    still_open = self.paper.positions.get_open()
                    if still_open:
                        self._monitor_bar(
                            still_open, idx=idx, candle_time=candle_time, settings=settings, debug_on=debug_on
                        )
                elif debug_on:
                    log_debug_event("TRADE_OPEN_FAILED", {
                        "signal": buy_condition,
                        "entry": entry,
                        "reason": "sizing_or_blocked",
                    })
            else:
                self._pending_entry = True
                if debug_on:
                    log_debug_event("ENTRY_PENDING", {**explain, "fill": "next_bar_open"})
        elif open_pos is not None and buy_condition and debug_on:
            log_debug_event("BUY_CONDITION_SUPPRESSED", {**explain, "reason": "position_open"})

        snap = sol_market.snapshot()
        self.engine_repo.update(
            last_candle_time=snap.get("last_candle_time"),
            last_price=snap.get("last_price"),
        )

    def dashboard_state(self) -> dict[str, Any]:
        settings = self.settings()
        acct = self.paper.accounts.get()
        pos = self.paper.positions.get_open()
        snap = sol_market.snapshot()
        stats = self.paper.statistics()
        engine = self.engine_repo.get()

        unrealized = 0.0
        pos_view = None
        if pos:
            price = snap.get("last_price") or float(pos["entry"])
            unrealized, price_pct = self.paper.unrealized_pnl(pos, price)
            margin = float(pos.get("margin_used") or 0)
            roe_pct = round(unrealized / margin * 100, 2) if margin > 0 else 0.0
            ha_high = None
            if snap.get("ha_candle"):
                ha_high = float(snap["ha_candle"].get("high") or price)
            live = preview_open_position(
                pos,
                live_price=price,
                settings=settings,
                bar_high=ha_high,
            )
            tp_pct, sl_pct = target_price_pcts(
                "BUY",
                float(pos["entry"]),
                float(pos["take_profit"]),
                float(live.get("original_stop_loss") or pos["stop_loss"]),
            )
            eff_pct = target_price_pcts(
                "BUY",
                float(pos["entry"]),
                float(pos["take_profit"]),
                float(live.get("effective_stop") or pos["stop_loss"]),
            )[1]
            pos_view = {
                **pos,
                "current_price": price,
                "unrealized_usd": unrealized,
                "unrealized_pct": price_pct,
                "price_move_pct": live.get("price_move_pct", price_pct),
                "roe_pct": roe_pct,
                "take_profit_price_pct": tp_pct,
                "stop_loss_price_pct": sl_pct,
                "effective_stop_price_pct": eff_pct,
                "highest_profit_pct": live.get("highest_profit_pct", pos.get("highest_profit_pct", 0)),
                "highest_price_since_lock": live.get("highest_price_since_lock"),
                "original_stop_loss": live.get("original_stop_loss", pos.get("stop_loss")),
                "effective_stop": live.get("effective_stop", pos.get("stop_loss")),
                "lock_active": live.get("lock_active", bool(pos.get("lock_active"))),
                "lock_stop": live.get("lock_stop", pos.get("lock_stop")),
                "trigger_price": live.get("trigger_price"),
                "lock_trigger_pct": live.get("lock_trigger_pct"),
                "lock_profit_enabled": live.get("lock_profit_enabled"),
            }

        equity = float(acct["balance"]) + unrealized
        return {
            "engine": {
                "running": bool(engine.get("running", 1)),
                "mode": "PAPER",
                "ws_connected": snap.get("ws_connected"),
                "last_signal": engine.get("last_signal"),
            },
            "market": snap,
            "account": {
                "balance": float(acct["balance"]),
                "realized_pnl": float(acct["realized_pnl"]),
                "equity": round(equity, 2),
                "initial_capital": float(settings.get("initial_capital", 100000)),
            },
            "position": pos_view,
            "statistics": stats,
            "settings": settings,
        }


sol_engine = SolReversalEngine()


async def sol_engine_loop(interval: float = 2.0) -> None:
    """Poll for new closed candles and run strategy."""
    sol_engine.engine_repo.ensure()
    while True:
        try:
            sol_engine.on_closed_candle()
        except Exception:
            logger.exception("SOL engine tick failed")
        await asyncio.sleep(interval)
