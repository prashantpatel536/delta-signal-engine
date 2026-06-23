"""Historical closed-trade recalculation with Delta-style 50% / 25x assumptions."""

from __future__ import annotations

import logging
from typing import Any

from app.paper_trader import calculate_pnl, calculate_roe, realized_points
from app.repositories.account_repository import AccountRepository, STARTING_BALANCE
from app.repositories.position_repository import PositionRepository
from app.risk_engine import account_impact_pct, enforce_trade_params, standard_sizing

logger = logging.getLogger(__name__)


class TradeRecalcService:
    def __init__(
        self,
        position_repository: PositionRepository | None = None,
        account_repository: AccountRepository | None = None,
    ) -> None:
        self.position_repository = position_repository or PositionRepository()
        self.account_repository = account_repository or AccountRepository()

    def recalculate_all(self) -> dict[str, Any]:
        closed = self.position_repository.list_closed_chronological()
        balance = float(STARTING_BALANCE)
        cumulative_pnl = 0.0
        updated = 0

        for position in closed:
            lev, margin_pct = enforce_trade_params(None, None)
            entry = float(position["entry"])
            exit_price = float(position.get("exit_price") or entry)
            side = position["side"]

            sizing = standard_sizing(
                balance,
                entry,
                margin_percent=margin_pct,
                leverage=lev,
            )
            qty = sizing["quantity"]
            pnl = calculate_pnl(side, entry, exit_price, qty)
            pts = realized_points(side, entry, exit_price)
            impact = account_impact_pct(pnl, balance)

            self.position_repository.update_closed_metrics(
                int(position["id"]),
                pnl=pnl,
                quantity=qty,
                leverage=lev,
                margin_used=sizing["margin_used"],
                position_value=sizing["position_value"],
                price_points=pts,
                account_impact_pct=impact,
            )
            balance += pnl
            cumulative_pnl += pnl
            updated += 1
            logger.info(
                "Trade recalc id=%s %s pnl=%.2f pts=%.2f impact=%.2f%%",
                position["id"],
                position["symbol"],
                pnl,
                pts,
                impact,
            )

        self.account_repository.set_balances(
            round(STARTING_BALANCE + cumulative_pnl, 2),
            round(cumulative_pnl, 2),
        )

        return {
            "ok": True,
            "recalculated": updated,
            "net_pnl": round(cumulative_pnl, 2),
            "ending_balance": round(STARTING_BALANCE + cumulative_pnl, 2),
        }


trade_recalc_service = TradeRecalcService()
