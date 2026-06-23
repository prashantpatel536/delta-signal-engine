"""Chronological account balance reconstruction for historical sizing."""

from __future__ import annotations

from typing import Any

from app.repositories.account_repository import STARTING_BALANCE
from app.repositories.position_repository import PositionRepository


class BalanceTimeline:
    """Replay closed-trade PnL to determine balance at any prior timestamp."""

    def __init__(self, closed_positions: list[dict[str, Any]] | None = None) -> None:
        if closed_positions is None:
            closed_positions = PositionRepository().list_closed_chronological()
        self._events: list[tuple[str, float, int]] = []
        for position in closed_positions:
            ts = str(position.get("closed_at") or "")
            if not ts:
                continue
            pnl = float(position.get("pnl") or 0.0)
            self._events.append((ts, pnl, int(position.get("id") or 0)))
        self._events.sort(key=lambda item: (item[0], item[2]))

    def balance_before(self, iso_timestamp: str) -> float:
        """Balance immediately before any event at iso_timestamp."""
        if not iso_timestamp:
            return float(STARTING_BALANCE)
        balance = float(STARTING_BALANCE)
        for ts, pnl, _ in self._events:
            if ts < iso_timestamp:
                balance += pnl
            else:
                break
        return round(balance, 2)

    def balance_at_open(self, opened_at: str) -> float:
        """Balance available when a position was opened (before its own close)."""
        return self.balance_before(opened_at)

    def balance_at_signal(self, created_at: str) -> float:
        """Balance when a signal was generated (before trades opened at same instant)."""
        return self.balance_before(created_at)

    @property
    def event_count(self) -> int:
        return len(self._events)


def balance_at_signal_time(
    created_at: str,
    timeline: BalanceTimeline | None = None,
) -> float:
    tl = timeline or BalanceTimeline()
    return tl.balance_at_signal(created_at)
