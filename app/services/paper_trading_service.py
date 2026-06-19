"""Virtual paper trading — Delta margin allocation model."""



from __future__ import annotations



import logging

from datetime import datetime

from typing import Any



from app.models import utc_now_iso

from app.performance_analytics import build_performance_payload

from app.paper_trader import (

    calculate_from_margin_allocation,

    calculate_pnl,

    calculate_roe,

    check_exit_reason,

    exit_status_label,

    format_duration_seconds,

    risk_reward_usd,

    trade_result,

    validate_position_levels,

)

from app.repositories.account_repository import AccountRepository, STARTING_BALANCE

from app.repositories.position_event_repository import PositionEventRepository

from app.repositories.position_repository import PositionRepository

from app.repositories.signal_repository import SignalRepository

from app.services.telegram_service import TelegramService, telegram_service



logger = logging.getLogger(__name__)





class InsufficientMarginError(ValueError):

    pass





class PaperTradingService:

    def __init__(

        self,

        repository: PositionRepository | None = None,

        account_repository: AccountRepository | None = None,

        signal_repository: SignalRepository | None = None,

        event_repository: PositionEventRepository | None = None,

        telegram: TelegramService | None = None,

    ) -> None:

        self.repository = repository or PositionRepository()

        self.account_repository = account_repository or AccountRepository()

        self.signal_repository = signal_repository or SignalRepository()

        self.event_repository = event_repository or PositionEventRepository()

        self.telegram = telegram if telegram is not None else telegram_service



    def get_account_summary(self, prices: dict[str, float] | None = None) -> dict[str, Any]:

        account = self.account_repository.ensure_account()

        balance = float(account["balance"])

        realized_pnl = float(account["realized_pnl"])

        used_margin = self.repository.sum_open_margin()



        unrealized_pnl = 0.0

        if prices:

            for position in self.repository.list_open():

                price = prices.get(position["symbol"])

                if price is not None:

                    unrealized_pnl += calculate_pnl(

                        position["side"],

                        position["entry"],

                        price,

                        position.get("quantity", 1.0),

                    )

        unrealized_pnl = round(unrealized_pnl, 2)



        available_margin = round(balance - used_margin, 2)

        total_balance = round(balance + unrealized_pnl, 2)



        return {

            "starting_balance": STARTING_BALANCE,

            "balance": balance,

            "total_balance": total_balance,

            "available_margin": available_margin,

            "used_margin": round(used_margin, 2),

            "unrealized_pnl": unrealized_pnl,

            "realized_pnl": round(realized_pnl, 2),

        }



    def _resolve_trade_size(

        self,

        *,

        entry: float,

        margin_percent: float,

        leverage: float,

        prices: dict[str, float] | None = None,

    ) -> tuple[float, float, float, float]:

        account = self.get_account_summary(prices)

        available = account["available_margin"]

        margin_used, position_value, quantity = calculate_from_margin_allocation(

            available,

            margin_percent,

            leverage,

            entry,

        )

        return margin_used, position_value, quantity, available



    def preview_trade(

        self,

        *,

        entry: float,

        margin_percent: float,

        leverage: float,

        side: str,

        stop_loss: float,

        take_profit: float,

        prices: dict[str, float] | None = None,

    ) -> dict[str, Any]:

        margin_used, position_value, quantity, available = self._resolve_trade_size(

            entry=entry,

            margin_percent=margin_percent,

            leverage=leverage,

            prices=prices,

        )

        sufficient = margin_used > 0 and margin_used <= available + 0.001

        risk, reward, rr = risk_reward_usd(side, entry, stop_loss, take_profit, quantity)

        return {

            "margin_used": margin_used,

            "position_value": position_value,

            "quantity": quantity,

            "available_margin": available,

            "sufficient_margin": sufficient,

            "risk_usd": risk,

            "reward_usd": reward,

            "risk_reward": rr,

        }



    def open_paper_trade(

        self,

        *,

        symbol: str,

        side: str,

        entry: float,

        margin_percent: float,

        leverage: float,

        stop_loss: float,

        take_profit: float,

        signal_id: int | None = None,

        prices: dict[str, float] | None = None,

    ) -> dict[str, Any]:

        if leverage < 1:

            raise ValueError("Leverage must be at least 1")

        if margin_percent <= 0 or margin_percent > 100:

            raise ValueError("Margin percent must be between 1 and 100")



        preview = self.preview_trade(

            entry=entry,

            margin_percent=margin_percent,

            leverage=leverage,

            side=side,

            stop_loss=stop_loss,

            take_profit=take_profit,

            prices=prices,

        )

        if not preview["sufficient_margin"]:

            raise InsufficientMarginError(

                f"Insufficient margin: need {preview['margin_used']}, "

                f"available {preview['available_margin']}"

            )



        if self.repository.has_open_for_symbol(symbol):

            raise ValueError(f"Open position already exists for {symbol}")



        if signal_id is not None:

            existing = self.repository.get_by_signal_id(signal_id)

            if existing is not None and existing["status"] == "OPEN":

                return existing



        quantity = preview["quantity"]

        margin_used = preview["margin_used"]

        position_value = preview["position_value"]



        position = self.repository.create(

            signal_id=signal_id,

            symbol=symbol,

            side=side,

            entry=float(entry),

            stop_loss=float(stop_loss),

            take_profit=float(take_profit),

            quantity=float(quantity),

            leverage=float(leverage),

            margin_used=margin_used,

            position_value=position_value,

            risk_reward=float(preview["risk_reward"]),

            opened_at=utc_now_iso(),

        )

        logger.info(

            "Opened paper trade id=%s %s %s margin=%s lev=%sx qty=%s pos=%s",

            position["id"],

            symbol,

            side,

            margin_used,

            leverage,

            quantity,

            position_value,

        )

        return position



    def monitor_positions(self, prices: dict[str, float]) -> list[dict[str, Any]]:

        closed: list[dict[str, Any]] = []

        for position in self.repository.list_open():

            symbol = position["symbol"]

            price = prices.get(symbol)

            if price is None:

                continue



            reason = check_exit_reason(

                position["side"],

                price,

                position["stop_loss"],

                position["take_profit"],

            )

            if reason is None:

                continue



            exit_price = (

                position["take_profit"] if reason == "TP" else position["stop_loss"]

            )

            updated = self._close_position(position["id"], exit_price, reason)

            if updated:

                closed.append(updated)

                logger.info(

                    "Paper position id=%s closed via %s pnl=%s",

                    updated["id"],

                    exit_status_label(reason),

                    updated["pnl"],

                )

        return closed



    def update_position_levels(

        self,

        position_id: int,

        *,

        stop_loss: float | None = None,

        take_profit: float | None = None,

    ) -> dict[str, Any]:

        position = self.repository.get_by_id(position_id)

        if position is None:

            raise LookupError(f"Position {position_id} not found")

        if position["status"] != "OPEN":

            raise ValueError(f"Position {position_id} is not open")

        if stop_loss is None and take_profit is None:

            raise ValueError("At least one of stop_loss or take_profit is required")



        new_sl = float(stop_loss if stop_loss is not None else position["stop_loss"])

        new_tp = float(take_profit if take_profit is not None else position["take_profit"])

        validate_position_levels(position["side"], position["entry"], new_sl, new_tp)



        qty = float(position.get("quantity") or 1.0)

        _, _, rr = risk_reward_usd(

            position["side"],

            position["entry"],

            new_sl,

            new_tp,

            qty,

        )



        updated = self.repository.update_levels(

            position_id,

            stop_loss=new_sl,

            take_profit=new_tp,

            risk_reward=rr,

        )

        if updated is None:

            raise LookupError(f"Position {position_id} not found")



        if stop_loss is not None and new_sl != float(position["stop_loss"]):

            self.event_repository.create(

                position_id=position_id,

                event_type="SL_MODIFIED",

                field_name="stop_loss",

                old_value=float(position["stop_loss"]),

                new_value=new_sl,

                message="SL Modified",

            )

            logger.info(

                "Position %s SL modified: %s -> %s (RR=%s)",

                position_id,

                position["stop_loss"],

                new_sl,

                rr,

            )



        if take_profit is not None and new_tp != float(position["take_profit"]):

            self.event_repository.create(

                position_id=position_id,

                event_type="TP_MODIFIED",

                field_name="take_profit",

                old_value=float(position["take_profit"]),

                new_value=new_tp,

                message="TP Modified",

            )

            logger.info(

                "Position %s TP modified: %s -> %s (RR=%s)",

                position_id,

                position["take_profit"],

                new_tp,

                rr,

            )



        return updated



    def move_stop_to_breakeven(self, position_id: int) -> dict[str, Any]:

        position = self.repository.get_by_id(position_id)

        if position is None:

            raise LookupError(f"Position {position_id} not found")

        if position["status"] != "OPEN":

            raise ValueError(f"Position {position_id} is not open")

        return self.update_position_levels(

            position_id,

            stop_loss=float(position["entry"]),

        )



    def close_manually(

        self,

        position_id: int,

        current_price: float,

    ) -> dict[str, Any]:

        position = self.repository.get_by_id(position_id)

        if position is None:

            raise LookupError(f"Position {position_id} not found")

        if position["status"] != "OPEN":

            raise ValueError(f"Position {position_id} is not open")



        self.event_repository.create(

            position_id=position_id,

            event_type="POSITION_CLOSED_MANUALLY",

            message="Position Closed Manually",

        )



        updated = self._close_position(position_id, current_price, "MANUAL")

        if updated is None:

            raise LookupError(f"Position {position_id} not found")

        return updated



    def get_open_positions_enriched(

        self,

        prices: dict[str, float],

    ) -> list[dict[str, Any]]:

        enriched: list[dict[str, Any]] = []

        for position in self.repository.list_open():

            current = prices.get(position["symbol"])

            qty = float(position.get("quantity") or 1.0)

            margin = float(position.get("margin_used") or 0.0)

            pnl = (

                calculate_pnl(position["side"], position["entry"], current, qty)

                if current is not None

                else None

            )

            row = dict(position)

            row["current_price"] = current

            row["unrealized_pnl"] = pnl

            row["roe"] = calculate_roe(pnl, margin) if pnl is not None and margin > 0 else None

            enriched.append(row)

        return enriched



    def get_position_events(self, position_id: int) -> list[dict[str, Any]]:

        position = self.repository.get_by_id(position_id)

        if position is None:

            raise LookupError(f"Position {position_id} not found")

        return self.event_repository.list_for_position(position_id)



    def get_closed_trades(self) -> list[dict[str, Any]]:

        trades: list[dict[str, Any]] = []

        for position in self.repository.list_closed():

            duration = self._duration_seconds(position["opened_at"], position["closed_at"])

            pnl = float(position["pnl"] or 0)

            margin = float(position.get("margin_used") or 0.0)

            trades.append(

                {

                    **position,

                    "result": trade_result(pnl),

                    "duration_seconds": duration,

                    "duration": format_duration_seconds(duration),

                    "exit_status": exit_status_label(position.get("exit_reason")),

                    "roe": calculate_roe(pnl, margin) if margin > 0 else None,

                }

            )

        return trades



    def get_statistics(self) -> dict[str, Any]:

        rows = self.repository.closed_pnl_rows()

        pnls = [float(r["pnl"]) for r in rows]

        wins = [p for p in pnls if p > 0]

        losses = [p for p in pnls if p <= 0]



        gross_profit = sum(wins)

        gross_loss = abs(sum(losses))

        total = len(pnls)

        account = self.account_repository.get_account()



        return {

            "total_trades": total,

            "wins": len(wins),

            "losses": len(losses),

            "win_rate": round(len(wins) / total * 100, 2) if total else 0.0,

            "net_pnl": round(float(account["realized_pnl"]), 2),

            "average_win": round(gross_profit / len(wins), 2) if wins else 0.0,

            "average_loss": round(gross_loss / len(losses), 2) if losses else 0.0,

            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,

            "open_positions": len(self.repository.list_open()),

        }



    def get_performance_analytics(

        self,

        prices: dict[str, float] | None = None,

    ) -> dict[str, Any]:

        account = self.get_account_summary(prices)

        closed = self.repository.list_closed_chronological()

        return build_performance_payload(

            starting_balance=float(account["starting_balance"]),

            current_balance=float(account["total_balance"]),

            closed_trades=closed,

            open_positions=len(self.repository.list_open()),

            fallback_date=utc_now_iso()[:10],

        )



    def _close_position(

        self,

        position_id: int,

        exit_price: float,

        exit_reason: str,

    ) -> dict[str, Any] | None:

        position = self.repository.get_by_id(position_id)

        if position is None or position["status"] != "OPEN":

            return None

        qty = float(position.get("quantity") or 1.0)

        pnl = calculate_pnl(position["side"], position["entry"], exit_price, qty)

        updated = self.repository.close(

            position_id,

            exit_price=exit_price,

            exit_reason=exit_reason,

            pnl=pnl,

        )

        if updated:

            self.account_repository.apply_realized_pnl(pnl)

            signal_id = updated.get("signal_id")

            if signal_id and exit_reason in ("TP", "SL"):

                target = "TP_HIT" if exit_reason == "TP" else "SL_HIT"

                record = self.signal_repository.get_by_id(signal_id)

                if record and record["status"] == "APPROVED":

                    self.signal_repository.update_status(signal_id, target)

                    logger.info(

                        "Signal %s marked %s after position %s closed",

                        signal_id,

                        target,

                        position_id,

                    )

            try:

                self.telegram.notify_position_closed(updated)

            except Exception:

                logger.exception("Telegram position close notification failed — continuing")

        return updated



    @staticmethod

    def _duration_seconds(opened_at: str, closed_at: str | None) -> float:

        if not closed_at:

            return 0.0

        opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))

        closed = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))

        return max(0.0, (closed - opened).total_seconds())

