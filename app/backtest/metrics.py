"""Aggregate backtest metrics, equity curve, drawdown, monthly stats."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


def _max_streaks(pnls: list[float]) -> tuple[int, int]:
    max_w = max_l = cur_w = cur_l = 0
    for p in pnls:
        if p > 0:
            cur_w += 1
            cur_l = 0
        elif p < 0:
            cur_l += 1
            cur_w = 0
        max_w = max(max_w, cur_w)
        max_l = max(max_l, cur_l)
    return max_w, max_l


def build_equity_curve(
    initial_capital: float,
    trades: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    equity = initial_capital
    peak = initial_capital
    curve: list[dict[str, Any]] = [
        {"time": None, "equity": equity, "drawdown_pct": 0.0, "trade_num": 0}
    ]
    for i, tr in enumerate(trades, start=1):
        equity += float(tr["pnl_usd"])
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        curve.append({
            "time": tr.get("exit_time"),
            "equity": round(equity, 2),
            "drawdown_pct": round(dd, 4),
            "trade_num": i,
        })
    return curve


def build_drawdown_series(equity_curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak = 0.0
    series = []
    for pt in equity_curve:
        eq = float(pt["equity"])
        peak = max(peak, eq)
        dd = (peak - eq) / peak * 100 if peak > 0 else 0.0
        series.append({
            "time": pt.get("time"),
            "drawdown_pct": round(dd, 4),
            "equity": eq,
            "peak": round(peak, 2),
        })
    return series


def build_monthly_report(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_month: dict[str, list[dict]] = defaultdict(list)
    for tr in trades:
        ts = tr.get("exit_time")
        if not ts:
            continue
        month = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m")
        by_month[month].append(tr)

    rows = []
    for month in sorted(by_month.keys()):
        items = by_month[month]
        pnls = [float(t["pnl_usd"]) for t in items]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gw = sum(wins)
        gl = abs(sum(losses))
        pf = round(gw / gl, 4) if gl > 0 else (999.0 if gw > 0 else 0.0)
        rows.append({
            "month": month,
            "trades": len(items),
            "profit": round(sum(pnls), 2),
            "win_rate": round(len(wins) / len(items) * 100, 2) if items else 0.0,
            "profit_factor": pf,
        })
    return rows


def aggregate_statistics(
    initial_capital: float,
    final_equity: float,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    pnls = [float(t["pnl_usd"]) for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gw = sum(wins)
    gl = abs(sum(losses))
    net = final_equity - initial_capital
    total_return = (final_equity / initial_capital - 1) * 100 if initial_capital > 0 else 0.0
    max_dd = max((float(p.get("drawdown_pct") or 0) for p in equity_curve), default=0.0)
    max_w, max_l = _max_streaks(pnls)
    avg_hold = (
        sum(int(t.get("bars_held") or 0) for t in trades) / len(trades) if trades else 0.0
    )

    return {
        "total_return_pct": round(total_return, 2),
        "net_profit": round(net, 2),
        "initial_capital": round(initial_capital, 2),
        "final_equity": round(final_equity, 2),
        "profit_factor": round(gw / gl, 4) if gl > 0 else (999.0 if gw > 0 else 0.0),
        "win_rate": round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "total_trades": len(trades),
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "avg_win": round(gw / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gl / len(losses), 2) if losses else 0.0,
        "avg_trade": round(net / len(trades), 4) if trades else 0.0,
        "largest_win": round(max(wins, default=0), 2),
        "largest_loss": round(min(losses, default=0), 2),
        "max_drawdown_pct": round(max_dd, 2),
        "max_win_streak": max_w,
        "max_loss_streak": max_l,
        "expectancy": round(net / len(trades), 4) if trades else 0.0,
        "avg_holding_bars": round(avg_hold, 2),
    }


def build_performance_insights(
    initial_capital: float,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    """Period returns, rolling drawdown, and trade distributions for backtest UI."""
    from collections import defaultdict

    daily_eq: dict[str, float] = {}
    for pt in equity_curve:
        ts = pt.get("time")
        if ts is None:
            continue
        day = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
        daily_eq[day] = float(pt["equity"])

    days = sorted(daily_eq.keys())
    period_returns: dict[str, float | None] = {
        "daily_return_pct": None,
        "weekly_return_pct": None,
        "monthly_return_pct": None,
        "yearly_return_pct": None,
    }
    if len(days) >= 2:
        first_eq = daily_eq[days[0]]
        last_eq = daily_eq[days[-1]]
        if first_eq > 0:
            total = (last_eq / first_eq - 1) * 100
            span = max(len(days), 1)
            period_returns["daily_return_pct"] = round(total / span, 4)
            period_returns["weekly_return_pct"] = round(total / span * 5, 4)
            period_returns["monthly_return_pct"] = round(total / span * 21, 4)
            period_returns["yearly_return_pct"] = round(total / span * 252, 4)

    rolling_dd = [
        {"time": p.get("time"), "drawdown_pct": p.get("drawdown_pct", 0)}
        for p in build_drawdown_series(equity_curve)
    ]

    pnls = [float(t["pnl_usd"]) for t in trades]
    holds = [int(t.get("bars_held") or 0) for t in trades]

    def _histogram(values: list[float], bins: int = 12) -> list[dict[str, Any]]:
        if not values:
            return []
        lo, hi = min(values), max(values)
        if lo == hi:
            return [{"bin": f"{lo:.2f}", "count": len(values)}]
        step = (hi - lo) / bins
        counts = [0] * bins
        for v in values:
            idx = min(int((v - lo) / step), bins - 1) if step > 0 else 0
            counts[idx] += 1
        return [
            {"bin": f"{lo + i * step:.2f}", "count": counts[i]}
            for i in range(bins)
            if counts[i] > 0
        ]

    return {
        **period_returns,
        "rolling_drawdown": rolling_dd,
        "trade_distribution": _histogram(pnls),
        "profit_distribution": _histogram([p for p in pnls if p != 0]),
        "holding_time_distribution": _histogram([float(h) for h in holds]),
    }
