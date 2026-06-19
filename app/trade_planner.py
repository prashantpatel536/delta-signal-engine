"""Trade plan calculation from signal entry and indicator levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Side = Literal["BUY", "SELL"]
DEFAULT_RISK_REWARD = 2.0


@dataclass(frozen=True)
class TradePlan:
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float

    def as_dict(self) -> dict[str, float | str]:
        return {
            "side": self.side,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
        }


def build_trade_plan(
    side: Side,
    entry: float,
    hh50: float,
    ll50: float,
    risk_reward: float = DEFAULT_RISK_REWARD,
) -> TradePlan:
    """
    Build a trade plan for human approval.

    BUY:  SL = LL50, TP = entry + 2 * (entry - SL)
    SELL: SL = HH50, TP = entry - 2 * (SL - entry)
    """
    entry = round(float(entry), 2)
    hh50 = round(float(hh50), 2)
    ll50 = round(float(ll50), 2)

    if side == "BUY":
        stop_loss = ll50
        risk = entry - stop_loss
        if risk <= 0:
            risk = max(abs(entry) * 0.005, 0.01)
            stop_loss = round(entry - risk, 2)
        take_profit = round(entry + (risk * risk_reward), 2)
    else:
        stop_loss = hh50
        risk = stop_loss - entry
        if risk <= 0:
            risk = max(abs(entry) * 0.005, 0.01)
            stop_loss = round(entry + risk, 2)
        take_profit = round(entry - (risk * risk_reward), 2)

    return TradePlan(
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
    )
