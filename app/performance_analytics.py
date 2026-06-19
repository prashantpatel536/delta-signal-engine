"""Pure functions for paper-trading performance analytics."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.paper_trader import format_duration_seconds


def duration_seconds(opened_at: str, closed_at: str | None) -> float:
    if not closed_at:
        return 0.0
    opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    closed = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
    return max(0.0, (closed - opened).total_seconds())


def build_daily_equity_curve(
    closed_trades: list[dict[str, Any]],
    starting_balance: float,
    *,
    fallback_date: str,
) -> list[dict[str, float | str]]:
    if not closed_trades:
        return [
            {
                "date": fallback_date,
                "equity": round(starting_balance, 2),
                "daily_pnl": 0.0,
            }
        ]

    sorted_trades = sorted(
        closed_trades,
        key=lambda t: (t.get("closed_at") or "", t.get("id") or 0),
    )

    daily_pnl: dict[str, float] = defaultdict(float)
    for trade in sorted_trades:
        day = (trade.get("closed_at") or "")[:10]
        if day:
            daily_pnl[day] += float(trade.get("pnl") or 0)

    curve: list[dict[str, float | str]] = []
    equity = float(starting_balance)
    for day in sorted(daily_pnl.keys()):
        pnl = daily_pnl[day]
        equity = round(equity + pnl, 2)
        curve.append({"date": day, "equity": equity, "daily_pnl": round(pnl, 2)})

    return curve


def equity_series_from_trades(
    closed_trades: list[dict[str, Any]],
    starting_balance: float,
) -> list[float]:
    sorted_trades = sorted(
        closed_trades,
        key=lambda t: (t.get("closed_at") or "", t.get("id") or 0),
    )
    series = [float(starting_balance)]
    for trade in sorted_trades:
        series.append(round(series[-1] + float(trade.get("pnl") or 0), 2))
    return series


def compute_max_drawdown(equity_series: list[float]) -> tuple[float, float]:
    if not equity_series:
        return 0.0, 0.0

    peak = equity_series[0]
    max_dd_usd = 0.0
    max_dd_pct = 0.0
    for equity in equity_series:
        if equity > peak:
            peak = equity
        drawdown = peak - equity
        if drawdown > max_dd_usd:
            max_dd_usd = drawdown
            max_dd_pct = (drawdown / peak * 100) if peak > 0 else 0.0
    return round(max_dd_usd, 2), round(max_dd_pct, 2)


def assess_edge(
    *,
    total_trades: int,
    net_pnl: float,
    profit_factor: float | None,
    win_rate: float,
) -> dict[str, str]:
    if total_trades < 5:
        return {
            "status": "insufficient_data",
            "label": "Insufficient Sample",
            "summary": (
                f"Only {total_trades} closed trade(s). "
                "Collect at least 5 trades before judging edge."
            ),
        }

    if net_pnl > 0 and profit_factor is not None and profit_factor >= 1.25:
        return {
            "status": "positive_edge",
            "label": "Promising Edge",
            "summary": (
                "Positive net PnL with profit factor ≥ 1.25. "
                "Continue paper trading to confirm consistency before live execution."
            ),
        }

    if net_pnl > 0 and profit_factor is not None and profit_factor >= 1.0:
        return {
            "status": "marginal",
            "label": "Marginal Edge",
            "summary": (
                "Profitable but thin margin. "
                f"Win rate {win_rate:.1f}% — monitor drawdown and sample size."
            ),
        }

    return {
        "status": "no_edge",
        "label": "No Clear Edge",
        "summary": (
            "Net PnL or profit factor does not support live execution yet. "
            "Review signal quality and risk parameters."
        ),
    }


def build_performance_payload(
    *,
    starting_balance: float,
    current_balance: float,
    closed_trades: list[dict[str, Any]],
    open_positions: int,
    fallback_date: str,
) -> dict[str, Any]:
    pnls = [float(t.get("pnl") or 0) for t in closed_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total = len(pnls)

    durations = [
        duration_seconds(t.get("opened_at", ""), t.get("closed_at"))
        for t in closed_trades
    ]
    avg_duration_seconds = sum(durations) / len(durations) if durations else 0.0

    equity_series = equity_series_from_trades(closed_trades, starting_balance)
    max_dd_usd, max_dd_pct = compute_max_drawdown(equity_series)
    daily_equity_curve = build_daily_equity_curve(
        closed_trades,
        starting_balance,
        fallback_date=fallback_date,
    )

    net_pnl = round(current_balance - starting_balance, 2)
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None
    win_rate = round(len(wins) / total * 100, 2) if total else 0.0

    edge = assess_edge(
        total_trades=total,
        net_pnl=net_pnl,
        profit_factor=profit_factor,
        win_rate=win_rate,
    )

    return {
        "starting_balance": round(starting_balance, 2),
        "current_balance": round(current_balance, 2),
        "net_pnl": net_pnl,
        "total_trades": total,
        "winning_trades": len(wins),
        "losing_trades": len(losses),
        "win_rate": win_rate,
        "average_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "average_loss": round(gross_loss / len(losses), 2) if losses else 0.0,
        "largest_win": round(max(wins), 2) if wins else 0.0,
        "largest_loss": round(min(losses), 2) if losses else 0.0,
        "profit_factor": profit_factor,
        "max_drawdown_usd": max_dd_usd,
        "max_drawdown_pct": max_dd_pct,
        "average_trade_duration_seconds": round(avg_duration_seconds, 1),
        "average_trade_duration": format_duration_seconds(avg_duration_seconds),
        "open_positions": open_positions,
        "edge_status": edge["status"],
        "edge_label": edge["label"],
        "edge_summary": edge["summary"],
        "daily_equity_curve": daily_equity_curve,
    }
