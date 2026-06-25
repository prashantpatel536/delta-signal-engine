"""
BTC strategy backtest engine — research only.

Mirrors live signal rules (HH50/LL50 breakout + SMA84) without modifying production modules.
Adds optimizer parameters: gap filter, min/max SL, and V2 partial exit simulation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

from app.delta_calculator import size_position
from app.indicators import calculate_indicators
from app.paper_trader import calculate_pnl, check_candle_exit, risk_points
from app.signals import _append_if_alternating, _signal_at_index

Side = Literal["BUY", "SELL"]
BTC_SYMBOL = "BTCUSDT"


@dataclass(frozen=True)
class BtcBacktestParams:
    gap_filter_pct: float
    min_sl_points: float
    max_sl_points: float
    initial_capital: float = 1000.0
    commission_pct: float = 0.0
    leverage: float = 25.0
    margin_percent: float = 50.0
    timeframe: str = "5m"


@dataclass
class ResearchTrade:
    side: str
    entry: float
    exit_price: float
    entry_time: str
    exit_time: str
    stop_loss: float
    take_profit_2r: float
    exit_reason: str
    profit_usd: float
    r_multiple: float
    duration_seconds: int
    quantity: float
    gap_pct: float
    exit_bar_index: int = 0


@dataclass
class BtcBacktestResult:
    params: BtcBacktestParams
    trades: list[ResearchTrade] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def _iso_from_unix(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()


def _breakout_gap_pct(side: str, close: float, hh50: float, ll50: float) -> float:
    close = float(close)
    if side == "BUY" and hh50 > 0:
        return round((close - float(hh50)) / close * 100.0, 4)
    if side == "SELL" and ll50 > 0:
        return round((float(ll50) - close) / close * 100.0, 4)
    return 0.0


def _research_stop_loss(
    side: Side,
    entry: float,
    structure_sl: float,
    min_sl: float,
    max_sl: float,
) -> tuple[float, float]:
    dist = risk_points(side, entry, structure_sl)
    if dist <= 0:
        dist = min_sl
    dist = max(float(min_sl), min(dist, float(max_sl)))
    if side == "BUY":
        sl = round(entry - dist, 2)
    else:
        sl = round(entry + dist, 2)
    return sl, round(dist, 4)


def _detect_research_signals(
    candles: pd.DataFrame,
    sma84: pd.Series,
    hh50: pd.Series,
    ll50: pd.Series,
    *,
    gap_filter_pct: float,
    min_sl: float,
    max_sl: float,
    timeframe: str,
) -> list[dict[str, Any]]:
    """Production signal rules + research gap/min/max SL filters."""
    if len(candles) < 2 or min_sl > max_sl:
        return []

    signals: list[dict[str, Any]] = []
    last_type: str | None = None

    for idx in range(1, len(candles)):
        raw = _signal_at_index(candles, sma84, hh50, ll50, idx, BTC_SYMBOL, timeframe)
        if raw is None:
            continue

        side = raw["signal"]
        if side == last_type:
            continue

        entry = float(raw["price"])
        hh = float(hh50.iloc[idx])
        ll = float(ll50.iloc[idx])
        gap_pct = _breakout_gap_pct(side, entry, hh, ll)
        if gap_pct < float(gap_filter_pct):
            continue

        structure_sl = ll if side == "BUY" else hh
        sl, sl_dist = _research_stop_loss(side, entry, structure_sl, min_sl, max_sl)
        if sl_dist <= 0:
            continue

        risk = sl_dist
        tp_2r = round(entry + 2 * risk, 2) if side == "BUY" else round(entry - 2 * risk, 2)

        signals.append({
            **raw,
            "side": side,
            "entry": entry,
            "stop_loss": sl,
            "take_profit_2r": tp_2r,
            "sl_distance": sl_dist,
            "gap_pct": gap_pct,
            "bar_index": idx,
        })
        last_type = side

    return signals


def _commission_usd(notional: float, commission_pct: float) -> float:
    return round(abs(notional) * float(commission_pct) / 100.0, 4)


def _simulate_v2_trade(
    candles: pd.DataFrame,
    sma84: pd.Series,
    signal: dict[str, Any],
    *,
    balance: float,
    params: BtcBacktestParams,
) -> tuple[ResearchTrade | None, int]:
    side = signal["side"]
    entry = float(signal["entry"])
    sl = float(signal["stop_loss"])
    tp_2r = float(signal["take_profit_2r"])
    start_idx = int(signal["bar_index"]) + 1

    sized = size_position(
        balance,
        entry,
        BTC_SYMBOL,
        stop_loss=sl,
        side=side,
        margin_percent=params.margin_percent,
        leverage=params.leverage,
    )
    qty = float(sized["quantity"])
    if qty <= 0:
        return None, -1

    open_commission = _commission_usd(sized["position_value"], params.commission_pct)
    remaining_qty = qty
    partial_qty = qty / 2.0
    partial_done = False
    total_pnl = -open_commission
    exit_price = entry
    exit_reason = "OPEN"
    exit_time = signal["timestamp"]
    risk = float(signal["sl_distance"])

    exit_bar_index = start_idx

    for idx in range(start_idx, len(candles)):
        row = candles.iloc[idx]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        bar_time = _iso_from_unix(int(row["time"]))
        sma = float(sma84.iloc[idx]) if not pd.isna(sma84.iloc[idx]) else None

        reason, level = check_candle_exit(
            side,
            high=high,
            low=low,
            stop_loss=sl,
            take_profit=tp_2r if not partial_done else (entry + 1e12 if side == "BUY" else entry - 1e12),
        )
        if reason == "SL":
            leg_pnl = calculate_pnl(side, entry, float(level), remaining_qty)
            notional = abs(float(level) * remaining_qty)
            total_pnl += leg_pnl - _commission_usd(notional, params.commission_pct)
            remaining_qty = 0.0
            exit_price = float(level)
            exit_reason = "SL"
            exit_time = bar_time
            exit_bar_index = idx
            break

        if not partial_done:
            hit_2r = (side == "BUY" and high >= tp_2r) or (side == "SELL" and low <= tp_2r)
            if hit_2r:
                leg_pnl = calculate_pnl(side, entry, tp_2r, partial_qty)
                notional = abs(tp_2r * partial_qty)
                total_pnl += leg_pnl - _commission_usd(notional, params.commission_pct)
                remaining_qty -= partial_qty
                partial_done = True
                exit_price = tp_2r
                exit_reason = "2R_PARTIAL"
                exit_time = bar_time

        if partial_done and remaining_qty > 0 and sma is not None:
            reversed_trend = (side == "BUY" and close < sma) or (side == "SELL" and close > sma)
            if reversed_trend:
                leg_pnl = calculate_pnl(side, entry, close, remaining_qty)
                notional = abs(close * remaining_qty)
                total_pnl += leg_pnl - _commission_usd(notional, params.commission_pct)
                remaining_qty = 0.0
                exit_price = close
                exit_reason = "SMA84_REVERSAL"
                exit_time = bar_time
                exit_bar_index = idx
                break

    if remaining_qty > 0:
        last = candles.iloc[-1]
        close = float(last["close"])
        leg_pnl = calculate_pnl(side, entry, close, remaining_qty)
        notional = abs(close * remaining_qty)
        total_pnl += leg_pnl - _commission_usd(notional, params.commission_pct)
        exit_price = close
        exit_reason = "END_OF_DATA"
        exit_time = _iso_from_unix(int(last["time"]))
        exit_bar_index = len(candles) - 1

    entry_ts = int(candles.iloc[int(signal["bar_index"])]["time"])
    exit_ts = int(pd.to_datetime(exit_time.replace("Z", "+00:00")).timestamp())
    r_mult = round(total_pnl / (risk * qty), 4) if risk > 0 and qty > 0 else 0.0

    trade = ResearchTrade(
        side=side,
        entry=entry,
        exit_price=round(exit_price, 2),
        entry_time=signal["timestamp"],
        exit_time=exit_time,
        stop_loss=sl,
        take_profit_2r=tp_2r,
        exit_reason=exit_reason,
        profit_usd=round(total_pnl, 2),
        r_multiple=r_mult,
        duration_seconds=max(exit_ts - entry_ts, 0),
        quantity=qty,
        gap_pct=float(signal["gap_pct"]),
        exit_bar_index=exit_bar_index,
    )
    return trade, exit_bar_index


def _streaks(pnls: list[float]) -> tuple[int, int]:
    longest_win = longest_loss = 0
    current_win = current_loss = 0
    for pnl in pnls:
        if pnl > 0:
            current_win += 1
            current_loss = 0
        elif pnl < 0:
            current_loss += 1
            current_win = 0
        else:
            current_win = 0
            current_loss = 0
        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)
    return longest_win, longest_loss


def _build_curves(
    trades: list[ResearchTrade],
    *,
    initial_capital: float,
) -> dict[str, list[dict[str, Any]]]:
    equity_curve: list[dict[str, Any]] = [
        {"trade_index": 0, "time": None, "equity": round(initial_capital, 2)},
    ]
    drawdown_curve: list[dict[str, Any]] = []
    daily_pnl: dict[str, float] = {}

    equity = float(initial_capital)
    peak = equity

    for idx, trade in enumerate(trades, start=1):
        equity += trade.profit_usd
        peak = max(peak, equity)
        dd_pct = (peak - equity) / peak * 100.0 if peak > 0 else 0.0
        exit_day = (trade.exit_time or "")[:10]
        if exit_day:
            daily_pnl[exit_day] = daily_pnl.get(exit_day, 0.0) + trade.profit_usd
        equity_curve.append({
            "trade_index": idx,
            "time": trade.exit_time,
            "equity": round(equity, 2),
        })
        drawdown_curve.append({
            "time": trade.exit_time,
            "drawdown_pct": round(dd_pct, 2),
        })

    daily_profit_curve = [
        {"date": day, "profit_usd": round(profit, 2)}
        for day, profit in sorted(daily_pnl.items())
    ]
    return {
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "daily_profit_curve": daily_profit_curve,
    }


def _aggregate_metrics(
    trades: list[ResearchTrade],
    *,
    initial_capital: float,
) -> dict[str, Any]:
    empty = {
        "total_trades": 0,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_return_pct": 0.0,
        "net_profit_usd": 0.0,
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "loss_rate": 0.0,
        "max_drawdown_pct": 0.0,
        "trade_count": 0,
        "avg_winner": 0.0,
        "avg_loser": 0.0,
        "avg_r_multiple": 0.0,
        "expectancy": 0.0,
        "avg_trade": 0.0,
        "avg_duration_seconds": 0.0,
        "largest_winner": 0.0,
        "largest_loser": 0.0,
        "longest_winning_streak": 0,
        "longest_losing_streak": 0,
    }
    if not trades:
        return empty

    pnls = [t.profit_usd for t in trades]
    winners = [p for p in pnls if p > 0]
    losers = [p for p in pnls if p < 0]
    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    pf = round(gross_profit / gross_loss, 4) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    balance = float(initial_capital)
    peak = balance
    max_dd_pct = 0.0
    for pnl in pnls:
        balance += pnl
        peak = max(peak, balance)
        if peak > 0:
            dd = (peak - balance) / peak * 100.0
            max_dd_pct = max(max_dd_pct, dd)

    net = round(balance - initial_capital, 2)
    ret_pct = round(net / initial_capital * 100.0, 2) if initial_capital else 0.0
    win_count = len(winners)
    loss_count = len(losers)
    longest_win, longest_loss = _streaks(pnls)

    return {
        "total_trades": len(trades),
        "winning_trades": win_count,
        "losing_trades": loss_count,
        "total_return_pct": ret_pct,
        "return_pct": ret_pct,
        "net_profit_usd": net,
        "profit_factor": pf,
        "win_rate": round(win_count / len(pnls) * 100.0, 2),
        "loss_rate": round(loss_count / len(pnls) * 100.0, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "trade_count": len(trades),
        "avg_winner": round(sum(winners) / len(winners), 2) if winners else 0.0,
        "avg_loser": round(sum(losers) / len(losers), 2) if losers else 0.0,
        "avg_r_multiple": round(sum(t.r_multiple for t in trades) / len(trades), 4),
        "expectancy": round(sum(pnls) / len(pnls), 2),
        "avg_trade": round(sum(pnls) / len(pnls), 2),
        "avg_duration_seconds": round(sum(t.duration_seconds for t in trades) / len(trades), 0),
        "largest_winner": round(max(winners), 2) if winners else 0.0,
        "largest_loser": round(min(losers), 2) if losers else 0.0,
        "longest_winning_streak": longest_win,
        "longest_losing_streak": longest_loss,
    }


def run_btc_backtest(
    candles: pd.DataFrame,
    params: BtcBacktestParams,
) -> BtcBacktestResult:
    """Full BTC research backtest for one parameter set."""
    if candles.empty or len(candles) < 100:
        empty = _aggregate_metrics([], initial_capital=params.initial_capital)
        empty.update(_build_curves([], initial_capital=params.initial_capital))
        return BtcBacktestResult(params=params, metrics=empty)

    sma84, hh50, ll50 = calculate_indicators(candles)
    signals = _detect_research_signals(
        candles,
        sma84,
        hh50,
        ll50,
        gap_filter_pct=params.gap_filter_pct,
        min_sl=params.min_sl_points,
        max_sl=params.max_sl_points,
        timeframe=params.timeframe,
    )

    balance = float(params.initial_capital)
    trades: list[ResearchTrade] = []
    last_exit_idx = -1

    for sig in signals:
        if sig["bar_index"] <= last_exit_idx:
            continue
        trade, exit_idx = _simulate_v2_trade(candles, sma84, sig, balance=balance, params=params)
        if trade is None:
            continue
        trades.append(trade)
        balance += trade.profit_usd
        last_exit_idx = exit_idx

    metrics = _aggregate_metrics(trades, initial_capital=params.initial_capital)
    curves = _build_curves(trades, initial_capital=params.initial_capital)
    return BtcBacktestResult(params=params, trades=trades, metrics={**metrics, **curves})


def candles_to_arrays(candles: pd.DataFrame) -> dict[str, Any]:
    """Compact serializable candle bundle for multiprocessing workers."""
    return {
        "time": candles["time"].astype(int).tolist(),
        "open": candles["open"].astype(float).tolist(),
        "high": candles["high"].astype(float).tolist(),
        "low": candles["low"].astype(float).tolist(),
        "close": candles["close"].astype(float).tolist(),
        "volume": candles["volume"].astype(float).tolist(),
    }


def arrays_to_candles(data: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(data)


def backtest_worker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Top-level worker for ProcessPoolExecutor."""
    from app.research.scoring import is_rankable, overall_score, rank_disqualify_reason

    candles = arrays_to_candles(payload["candles"])
    params = BtcBacktestParams(**payload["params"])
    result = run_btc_backtest(candles, params)
    curves = {
        "equity_curve": result.metrics.get("equity_curve", []),
        "drawdown_curve": result.metrics.get("drawdown_curve", []),
        "daily_profit_curve": result.metrics.get("daily_profit_curve", []),
    }
    metrics = {k: v for k, v in result.metrics.items() if k not in curves}
    row = {
        "gap_filter_pct": params.gap_filter_pct,
        "min_sl_points": params.min_sl_points,
        "max_sl_points": params.max_sl_points,
        **metrics,
    }
    row["score"] = overall_score(row)
    row["rankable"] = is_rankable(row)
    row["rank_disqualify_reason"] = rank_disqualify_reason(row)
    row["trades"] = [
        {
            "trade_num": i + 1,
            "side": t.side,
            "entry": t.entry,
            "exit_price": t.exit_price,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit_2r,
            "exit_reason": t.exit_reason,
            "profit_usd": t.profit_usd,
            "r_multiple": t.r_multiple,
            "duration_seconds": t.duration_seconds,
            "quantity": t.quantity,
        }
        for i, t in enumerate(result.trades)
    ]
    row.update(curves)
    return row
