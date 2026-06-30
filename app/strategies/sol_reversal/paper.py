"""SOL Reversal paper trading — uses simulation.py (same logic as backtest)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models import utc_now_iso
from app.strategies.sol_reversal.repositories import (
    SolAccountRepository,
    SolPositionRepository,
    SolTradeRepository,
)
from app.strategies.sol_reversal.simulation import (
    open_position as sim_open,
    pnl_at_price,
    process_bar,
    size_position,
)


def _iso_to_unix(iso: str | None) -> int:
    if not iso:
        return int(datetime.now(tz=timezone.utc).timestamp())
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return int(datetime.now(tz=timezone.utc).timestamp())


class SolPaperService:
    SYMBOL = "SOLUSDT"

    def __init__(self) -> None:
        self.accounts = SolAccountRepository()
        self.positions = SolPositionRepository()
        self.trades = SolTradeRepository()

    def equity(self, unrealized: float = 0.0) -> float:
        acct = self.accounts.get()
        return float(acct["balance"]) + unrealized

    def size_position(self, entry: float, settings: dict[str, Any], unrealized: float = 0.0) -> dict[str, Any]:
        return size_position(self.equity(unrealized), entry, settings, self.SYMBOL) or {}

    def _to_sim(self, position: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": position.get("symbol", self.SYMBOL),
            "side": position["side"],
            "entry": float(position["entry"]),
            "entry_time": _iso_to_unix(position.get("opened_at")),
            "stop_loss": float(position["stop_loss"]),
            "take_profit": float(position["take_profit"]),
            "quantity": float(position["quantity"]),
            "leverage": float(position.get("leverage") or 25),
            "margin_used": float(position.get("margin_used") or 0),
            "position_value": float(position.get("position_value") or 0),
            "lock_active": bool(position.get("lock_active")),
            "lock_stop": position.get("lock_stop"),
            "highest_profit_pct": float(position.get("highest_profit_pct") or 0),
            "mfe_pct": float(position.get("mfe_pct") or 0),
            "mae_pct": float(position.get("mae_pct") or 0),
            "bars_held": int(position.get("bars_held") or 0),
        }

    def open_trade(self, side: str, entry: float, settings: dict[str, Any]) -> dict[str, Any] | None:
        if self.positions.get_open():
            return None
        equity = self.equity()
        sim = sim_open(side, entry, int(datetime.now(tz=timezone.utc).timestamp()), settings, equity, self.SYMBOL)
        if not sim:
            return None
        return self.positions.open_position({
            "symbol": self.SYMBOL,
            "side": side,
            "entry": entry,
            "stop_loss": sim["stop_loss"],
            "take_profit": sim["take_profit"],
            "quantity": sim["quantity"],
            "leverage": settings.get("leverage", 25.0),
            "margin_used": sim["margin_used"],
            "position_value": sim["position_value"],
        })

    def unrealized_pnl(self, position: dict[str, Any], price: float) -> tuple[float, float]:
        """Returns (account PnL USD, SOL price move % from entry)."""
        pnl, move_pct = pnl_at_price(self._to_sim(position), price)
        return pnl, move_pct

    def monitor(
        self,
        position: dict[str, Any],
        *,
        high: float,
        low: float,
        close: float,
        settings: dict[str, Any],
        bar_time: int | None = None,
    ) -> dict[str, Any] | None:
        """Check TP/SL/lock on bar. Returns close payload if exited."""
        ts = bar_time or int(datetime.now(tz=timezone.utc).timestamp())
        updated, closed = process_bar(
            self._to_sim(position),
            bar_time=ts,
            high=high,
            low=low,
            close=close,
            settings=settings,
        )
        pos_id = int(position["id"])

        if updated and not closed:
            self.positions.update_position(pos_id, {
                "lock_active": int(updated["lock_active"]),
                "lock_stop": updated.get("lock_stop"),
                "highest_profit_pct": updated["highest_profit_pct"],
                "highest_price": high if position["side"] == "BUY" else low,
                "mfe_pct": updated["mfe_pct"],
                "mae_pct": updated["mae_pct"],
                "stop_loss": updated["stop_loss"],
                "bars_held": updated["bars_held"],
            })
            return None

        if not closed:
            return None

        pnl_usd = closed["pnl_usd"]
        pnl_pct = closed["price_move_pct"]
        db_closed = self.positions.close_position(pos_id, {
            "closed_at": utc_now_iso(),
            "exit_price": closed["exit_price"],
            "exit_reason": closed["exit_reason"],
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "bars_held": closed["bars_held"],
            "lock_active": int(closed["lock_active"]),
            "lock_stop": closed.get("lock_stop"),
            "highest_profit_pct": closed["highest_profit_pct"],
            "mfe_pct": closed["mfe_pct"],
            "mae_pct": closed["mae_pct"],
        })
        self.accounts.apply_pnl(pnl_usd)
        self.trades.insert({
            "position_id": pos_id,
            "symbol": self.SYMBOL,
            "side": closed["side"],
            "entry_time": position["opened_at"],
            "exit_time": db_closed["closed_at"],
            "entry": closed["entry_price"],
            "exit": closed["exit_price"],
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "bars_held": closed["bars_held"],
            "exit_reason": closed["exit_reason"],
            "mfe_pct": closed["mfe_pct"],
            "mae_pct": closed["mae_pct"],
        })
        return db_closed

    def statistics(self) -> dict[str, Any]:
        rows = self.positions.list_closed(10000)
        if not rows:
            return {
                "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "profit_factor": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
                "expected_value": 0.0, "largest_win": 0.0, "largest_loss": 0.0,
                "current_win_streak": 0, "current_loss_streak": 0,
                "max_win_streak": 0, "max_loss_streak": 0,
            }
        wins = [r for r in rows if float(r.get("pnl_usd") or 0) > 0]
        losses = [r for r in rows if float(r.get("pnl_usd") or 0) < 0]
        gw = sum(float(r["pnl_usd"]) for r in wins)
        gl = abs(sum(float(r["pnl_usd"]) for r in losses))
        pf = round(gw / gl, 4) if gl > 0 else (999.0 if gw > 0 else 0.0)

        cur_w = cur_l = max_w = max_l = 0
        for r in reversed(rows):
            pnl = float(r.get("pnl_usd") or 0)
            if pnl > 0:
                cur_w += 1
                cur_l = 0
            elif pnl < 0:
                cur_l += 1
                cur_w = 0
            max_w = max(max_w, cur_w)
            max_l = max(max_l, cur_l)

        return {
            "total_trades": len(rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(rows) * 100, 2),
            "profit_factor": pf,
            "avg_win": round(gw / len(wins), 2) if wins else 0.0,
            "avg_loss": round(-gl / len(losses), 2) if losses else 0.0,
            "expected_value": round(sum(float(r["pnl_usd"]) for r in rows) / len(rows), 4),
            "largest_win": round(max((float(r["pnl_usd"]) for r in wins), default=0), 2),
            "largest_loss": round(min((float(r["pnl_usd"]) for r in losses), default=0), 2),
            "current_win_streak": cur_w,
            "current_loss_streak": cur_l,
            "max_win_streak": max_w,
            "max_loss_streak": max_l,
        }
