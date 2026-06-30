"""24/7 SOL Reversal strategy engine loop."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.strategies.sol_reversal.market import sol_market
from app.strategies.sol_reversal.paper import SolPaperService
from app.strategies.sol_reversal.repositories import SolEngineRepository, SolSettingsRepository
from app.strategies.sol_reversal.strategy import detect_signal_at_index, target_price_pcts

logger = logging.getLogger(__name__)


class SolReversalEngine:
    def __init__(self) -> None:
        self.paper = SolPaperService()
        self.settings_repo = SolSettingsRepository()
        self.engine_repo = SolEngineRepository()
        self._last_processed_candle: int | None = None

    def settings(self) -> dict[str, Any]:
        return self.settings_repo.get_all()

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

        # First tick after start: sync to current closed bar, don't trade stale history.
        if self._last_processed_candle is None:
            self._last_processed_candle = candle_time
            return

        self._last_processed_candle = candle_time

        settings = self.settings()
        high, low, close, _ = sol_market.last_bar_ohlc()

        open_pos = self.paper.positions.get_open()
        if open_pos:
            closed = self.paper.monitor(
                open_pos, high=high, low=low, close=close, settings=settings, bar_time=candle_time
            )
            if closed:
                self.engine_repo.log("INFO", f"Closed {closed['side']} {closed['exit_reason']} pnl={closed['pnl_usd']}")
            open_pos = self.paper.positions.get_open()

        if open_pos is None:
            signal = detect_signal_at_index(ha, settings, idx, atr=atr)
            if signal:
                entry = float(ha.iloc[idx]["close"])
                opened = self.paper.open_trade(signal, entry, settings)
                if opened:
                    self.engine_repo.log("INFO", f"Opened {signal} @ {entry}")
                    self.engine_repo.update(last_signal=signal)

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
        unrealized_pct = 0.0
        pos_view = None
        if pos:
            price = snap.get("last_price") or float(pos["entry"])
            unrealized, price_pct = self.paper.unrealized_pnl(pos, price)
            margin = float(pos.get("margin_used") or 0)
            roe_pct = round(unrealized / margin * 100, 2) if margin > 0 else 0.0
            tp_pct, sl_pct = target_price_pcts(
                pos["side"], float(pos["entry"]), float(pos["take_profit"]), float(pos["stop_loss"])
            )
            pos_view = {
                **pos,
                "current_price": price,
                "unrealized_usd": unrealized,
                "unrealized_pct": price_pct,
                "price_move_pct": price_pct,
                "roe_pct": roe_pct,
                "take_profit_price_pct": tp_pct,
                "stop_loss_price_pct": sl_pct,
                "highest_profit_pct": pos.get("highest_profit_pct", 0),
                "lock_active": bool(pos.get("lock_active")),
                "lock_stop": pos.get("lock_stop"),
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
                "initial_capital": float(settings.get("initial_capital", 1000)),
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
