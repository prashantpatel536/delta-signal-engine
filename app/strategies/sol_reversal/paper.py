"""SOL Reversal paper trading — isolated from BTC account."""

from __future__ import annotations

from typing import Any

from app.contract_specs import contracts_from_notional, sizing_from_contracts
from app.models import utc_now_iso
from app.strategies.sol_reversal.repositories import (
    SolAccountRepository,
    SolPositionRepository,
    SolTradeRepository,
)
from app.strategies.sol_reversal.strategy import levels_for_side


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
        equity = self.equity(unrealized)
        margin_pct = float(settings.get("position_size_pct", 50.0)) / 100.0
        leverage = float(settings.get("leverage", 25.0))
        margin = equity * margin_pct
        notional = margin * leverage
        contracts = contracts_from_notional(notional, entry, self.SYMBOL)
        sized = sizing_from_contracts(contracts, entry, self.SYMBOL, leverage)
        sized["margin_allocated"] = round(margin, 2)
        sized["equity"] = round(equity, 2)
        return sized

    def open_trade(self, side: str, entry: float, settings: dict[str, Any]) -> dict[str, Any] | None:
        if self.positions.get_open():
            return None
        sized = self.size_position(entry, settings)
        if sized["contracts"] <= 0:
            return None
        tp, sl = levels_for_side(side, entry, settings)
        return self.positions.open_position({
            "symbol": self.SYMBOL,
            "side": side,
            "entry": entry,
            "stop_loss": sl,
            "take_profit": tp,
            "quantity": sized["quantity"],
            "leverage": settings.get("leverage", 25.0),
            "margin_used": sized["margin_used"],
            "position_value": sized["position_value"],
        })

    def unrealized_pnl(self, position: dict[str, Any], price: float) -> tuple[float, float]:
        entry = float(position["entry"])
        qty = float(position["quantity"])
        side = position["side"]
        if side == "BUY":
            pnl = (price - entry) * qty
            pnl_pct = (price - entry) / entry * 100.0
        else:
            pnl = (entry - price) * qty
            pnl_pct = (entry - price) / entry * 100.0
        return round(pnl, 4), round(pnl_pct, 4)

    def monitor(
        self,
        position: dict[str, Any],
        *,
        high: float,
        low: float,
        close: float,
        settings: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Check TP/SL/lock on bar. Returns close payload if exited."""
        side = position["side"]
        entry = float(position["entry"])
        sl = float(position["stop_loss"])
        tp = float(position["take_profit"])
        pos_id = int(position["id"])

        _, pnl_pct_high = self.unrealized_pnl(position, high if side == "BUY" else low)
        _, pnl_pct_low = self.unrealized_pnl(position, low if side == "BUY" else high)
        mfe = max(float(position.get("mfe_pct") or 0), pnl_pct_high)
        mae = min(float(position.get("mae_pct") or 0), pnl_pct_low)

        lock_active = bool(position.get("lock_active"))
        lock_stop = position.get("lock_stop")
        highest_profit = max(float(position.get("highest_profit_pct") or 0), pnl_pct_high)

        if settings.get("lock_profit_enabled") and highest_profit >= float(settings.get("lock_trigger_pct", 3.0)):
            lock_active = True
            dist = float(settings.get("lock_distance_pct", 3.0)) / 100.0
            if side == "BUY":
                peak = high
                lock_stop = round(peak * (1 - dist), 4)
                sl = max(sl, lock_stop)
            else:
                peak = low
                lock_stop = round(peak * (1 + dist), 4)
                sl = min(sl, lock_stop)

        self.positions.update_position(pos_id, {
            "lock_active": int(lock_active),
            "lock_stop": lock_stop,
            "highest_profit_pct": highest_profit,
            "highest_price": high if side == "BUY" else low,
            "mfe_pct": mfe,
            "mae_pct": mae,
            "stop_loss": sl,
        })

        exit_price = None
        reason = None
        if side == "BUY":
            if low <= sl:
                exit_price, reason = sl, "LOCK" if lock_active else "SL"
            elif high >= tp:
                exit_price, reason = tp, "TP"
        else:
            if high >= sl:
                exit_price, reason = sl, "LOCK" if lock_active else "SL"
            elif low <= tp:
                exit_price, reason = tp, "TP"

        if exit_price is None:
            return None

        pnl_usd, pnl_pct = self.unrealized_pnl(position, exit_price)
        closed = self.positions.close_position(pos_id, {
            "closed_at": utc_now_iso(),
            "exit_price": exit_price,
            "exit_reason": reason,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "bars_held": 0,
            "lock_active": int(lock_active),
            "lock_stop": lock_stop,
            "highest_profit_pct": highest_profit,
            "mfe_pct": mfe,
            "mae_pct": mae,
        })
        self.accounts.apply_pnl(pnl_usd)
        self.trades.insert({
            "position_id": pos_id,
            "symbol": self.SYMBOL,
            "side": side,
            "entry_time": position["opened_at"],
            "exit_time": closed["closed_at"],
            "entry": entry,
            "exit": exit_price,
            "pnl_pct": pnl_pct,
            "pnl_usd": pnl_usd,
            "bars_held": closed.get("bars_held") or 0,
            "exit_reason": reason,
            "mfe_pct": mfe,
            "mae_pct": mae,
        })
        return closed

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
