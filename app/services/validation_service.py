"""Validation report for risk-engine compliance."""

from __future__ import annotations

import json
from typing import Any

from app.config import settings
from app.contract_specs import MIN_RISK_REWARD, MIN_TARGET_ROE_PCT
from app.paper_trader import calculate_roe, risk_points, reward_points
from app.repositories.position_repository import PositionRepository
from app.repositories.signal_repository import SignalRepository
from app.risk_engine import _liquidation_beyond_sl, trading_leverage, trading_margin_percent


class ValidationService:
    def __init__(
        self,
        signal_repository: SignalRepository | None = None,
        position_repository: PositionRepository | None = None,
    ) -> None:
        self.signals = signal_repository or SignalRepository()
        self.positions = position_repository or PositionRepository()

    def build_report(self) -> dict[str, Any]:
        symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
        symbol_stats: dict[str, Any] = {}
        compliance = {
            "capital_usage_pct": trading_margin_percent(),
            "leverage": trading_leverage(),
            "min_target_roe_pct": MIN_TARGET_ROE_PCT,
            "min_risk_reward": MIN_RISK_REWARD,
            "opposite_signal_exits": 0,
            "liq_beyond_sl_pass": 0,
            "liq_beyond_sl_fail": 0,
            "min_roe_pass": 0,
            "min_roe_fail": 0,
            "min_rr_pass": 0,
            "min_rr_fail": 0,
        }

        for symbol in symbols:
            symbol_stats[symbol] = self._symbol_stats(symbol, compliance)

        closed = self.positions.list_closed_chronological()
        for trade in closed:
            if trade.get("exit_reason") == "Opposite Signal":
                compliance["opposite_signal_exits"] += 1

        from app.services.audit_service import audit_service

        strategy_sim = audit_service.strategy_account_simulation()
        missed_sim = audit_service.missed_opportunity_simulation()
        trade_audit = audit_service.validate_trades()

        return {
            "assumptions": {
                "capital_usage_pct": trading_margin_percent(),
                "leverage": trading_leverage(),
                "min_target_roe_pct": MIN_TARGET_ROE_PCT,
                "min_risk_reward": MIN_RISK_REWARD,
            },
            "symbols": symbol_stats,
            "compliance": compliance,
            "total_closed_trades": len(closed),
            "strategy_account_simulation": strategy_sim,
            "missed_opportunity_simulation": missed_sim,
            "trade_validation_summary": {
                "total": trade_audit["total_trades"],
                "passed": trade_audit["passed"],
                "failed": trade_audit["failed"],
                "all_within_1pct": trade_audit["all_within_1pct"],
            },
        }

    def _symbol_stats(self, symbol: str, compliance: dict[str, Any]) -> dict[str, Any]:
        records = self.signals.list_filtered(symbol=symbol)
        sl_dists: list[float] = []
        tp_dists: list[float] = []
        roes: list[float] = []
        loss_pcts: list[float] = []
        profit_pcts: list[float] = []

        for record in records:
            raw = record.get("risk_profile")
            profile: dict[str, Any] | None = None
            if isinstance(raw, str) and raw.strip():
                try:
                    profile = json.loads(raw)
                except json.JSONDecodeError:
                    profile = None
            elif isinstance(raw, dict):
                profile = raw

            side = record["side"]
            entry = float(record["entry"])
            sl = float(record["stop_loss"])
            tp = float(record["take_profit"])

            sl_d = risk_points(side, entry, sl)
            tp_d = reward_points(side, entry, tp)
            sl_dists.append(sl_d)
            tp_dists.append(tp_d)

            if profile:
                if profile.get("expected_roe") is not None:
                    roe = float(profile["expected_roe"])
                    roes.append(roe)
                    if roe >= MIN_TARGET_ROE_PCT:
                        compliance["min_roe_pass"] += 1
                    else:
                        compliance["min_roe_fail"] += 1
                if profile.get("expected_loss_pct") is not None:
                    loss_pcts.append(abs(float(profile["expected_loss_pct"])))
                if profile.get("expected_profit_pct") is not None:
                    profit_pcts.append(float(profile["expected_profit_pct"]))
                rr = float(profile.get("risk_reward") or record.get("risk_reward") or 0)
                if rr >= MIN_RISK_REWARD:
                    compliance["min_rr_pass"] += 1
                else:
                    compliance["min_rr_fail"] += 1
                lev = float(profile.get("leverage") or trading_leverage())
                if _liquidation_beyond_sl(side, entry, sl, lev):
                    compliance["liq_beyond_sl_pass"] += 1
                else:
                    compliance["liq_beyond_sl_fail"] += 1

        closed = [p for p in self.positions.list_closed() if p["symbol"] == symbol]
        trade_roes = []
        for t in closed:
            margin = float(t.get("margin_used") or 0)
            pnl = float(t.get("pnl") or 0)
            if margin > 0:
                trade_roes.append(calculate_roe(pnl, margin))

        def avg(vals: list[float]) -> float:
            return round(sum(vals) / len(vals), 2) if vals else 0.0

        short = next((k for k, v in settings.symbol_map.items() if v == symbol), symbol[:3])
        return {
            "label": short,
            "symbol": symbol,
            "signal_count": len(records),
            "average_sl_points": avg(sl_dists),
            "average_tp_points": avg(tp_dists),
            "average_expected_roe": avg(roes),
            "average_loss_pct": avg(loss_pcts),
            "average_profit_pct": avg(profit_pcts),
            "average_trade_roe": avg(trade_roes),
            "closed_trades": len(closed),
        }


validation_service = ValidationService()
