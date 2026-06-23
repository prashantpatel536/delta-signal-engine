"""Trade plan calculation from signal entry and indicator levels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.contract_specs import MIN_RISK_REWARD, MIN_TARGET_ROE_PCT, get_contract_spec
from app.paper_trader import calculate_pnl, calculate_roe, risk_points, reward_points

Side = Literal["BUY", "SELL"]
DEFAULT_RISK_REWARD = 2.0


@dataclass(frozen=True)
class TradePlan:
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    symbol: str = "BTCUSDT"
    structure_stop_loss: float | None = None
    sl_distance_points: float = 0.0
    tp_distance_points: float = 0.0

    def as_dict(self) -> dict[str, float | str]:
        return {
            "side": self.side,
            "entry": self.entry,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "symbol": self.symbol,
            "structure_stop_loss": self.structure_stop_loss or self.stop_loss,
            "sl_distance_points": self.sl_distance_points,
            "tp_distance_points": self.tp_distance_points,
        }


def _clamp_sl_distance(
    side: Side,
    entry: float,
    structure_sl: float,
    symbol: str,
) -> tuple[float, float]:
    """Apply min/max SL point limits; return (stop_loss, sl_distance)."""
    spec = get_contract_spec(symbol)
    entry = float(entry)
    structure_sl = float(structure_sl)
    dist = risk_points(side, entry, structure_sl)
    if dist <= 0:
        dist = spec.min_sl_points
    dist = max(spec.min_sl_points, min(dist, spec.max_sl_points))
    if side == "BUY":
        sl = round(entry - dist, 4 if symbol == "SOLUSDT" else 2)
    else:
        sl = round(entry + dist, 4 if symbol == "SOLUSDT" else 2)
    return sl, round(dist, 4)


def _tp_for_min_rr(side: Side, entry: float, sl: float, min_rr: float) -> float:
    risk = risk_points(side, entry, sl)
    reward_dist = risk * min_rr
    if side == "BUY":
        return round(entry + reward_dist, 2)
    return round(entry - reward_dist, 2)


def _extend_tp_for_min_roe(
    side: Side,
    entry: float,
    sl: float,
    tp: float,
    *,
    symbol: str,
    balance: float,
    margin_percent: float,
    leverage: float,
    min_roe: float = MIN_TARGET_ROE_PCT,
) -> float:
    """Extend TP until expected ROE at target meets minimum."""
    from app.paper_trader import calculate_from_margin_allocation

    entry = float(entry)
    tp = float(tp)
    margin_used, _, qty, _ = calculate_from_margin_allocation(
        balance, margin_percent, leverage, entry, symbol
    )
    if qty <= 0 or margin_used <= 0:
        return tp

    reward = abs(calculate_pnl(side, entry, tp, qty))
    roe = calculate_roe(reward, margin_used)
    if roe >= min_roe:
        return tp

    # Binary search TP distance for min ROE
    sl_dist = risk_points(side, entry, sl)
    low = reward_points(side, entry, tp)
    high = max(low * 2, sl_dist * MIN_RISK_REWARD * 3)
    best_tp = tp
    for _ in range(40):
        mid = (low + high) / 2.0
        candidate = entry + mid if side == "BUY" else entry - mid
        reward = abs(calculate_pnl(side, entry, candidate, qty))
        roe = calculate_roe(reward, margin_used)
        if roe >= min_roe:
            best_tp = round(candidate, 4 if symbol == "SOLUSDT" else 2)
            high = mid
        else:
            low = mid
    return best_tp


def build_trade_plan(
    side: Side,
    entry: float,
    hh50: float,
    ll50: float,
    *,
    symbol: str = "BTCUSDT",
    risk_reward: float = DEFAULT_RISK_REWARD,
    balance: float | None = None,
    margin_percent: float | None = None,
    leverage: float | None = None,
) -> TradePlan:
    """
    Build trade plan with HH50/LL50 structure, SL min/max clamps, min RR 2:1, min 50% ROE TP.
    """
    from app.risk_engine import trading_leverage, trading_margin_percent

    entry = round(float(entry), 4 if symbol == "SOLUSDT" else 2)
    hh50 = round(float(hh50), 4 if symbol == "SOLUSDT" else 2)
    ll50 = round(float(ll50), 4 if symbol == "SOLUSDT" else 2)
    bal = float(balance if balance is not None else 1000.0)
    margin_pct = float(margin_percent if margin_percent is not None else trading_margin_percent())
    lev = float(leverage if leverage is not None else trading_leverage())
    min_rr = max(float(risk_reward), MIN_RISK_REWARD)

    if side == "BUY":
        structure_sl = ll50
    else:
        structure_sl = hh50

    stop_loss, sl_dist = _clamp_sl_distance(side, entry, structure_sl, symbol)
    take_profit = _tp_for_min_rr(side, entry, stop_loss, min_rr)
    take_profit = _extend_tp_for_min_roe(
        side,
        entry,
        stop_loss,
        take_profit,
        symbol=symbol,
        balance=bal,
        margin_percent=margin_pct,
        leverage=lev,
    )

    tp_dist = reward_points(side, entry, take_profit)
    rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0

    return TradePlan(
        side=side,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=rr,
        symbol=symbol,
        structure_stop_loss=structure_sl,
        sl_distance_points=sl_dist,
        tp_distance_points=tp_dist,
    )
