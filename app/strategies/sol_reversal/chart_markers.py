"""Chart markers from executed paper trades — not independent replay."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _iso_to_unix(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return None


def _snap_candle_time(target_unix: int, candle_times: list[int], *, tolerance_sec: int = 600) -> int | None:
    if not candle_times:
        return None
    best = min(candle_times, key=lambda t: abs(t - target_unix))
    return best if abs(best - target_unix) <= tolerance_sec else None


def _exit_status(reason: str | None) -> str:
    if reason == "TP":
        return "TP_HIT"
    if reason == "SL":
        return "SL_HIT"
    if reason == "LOCK":
        return "LOCK_HIT"
    return "SL_HIT"


def markers_from_paper_trades(
    candle_times: list[int],
    *,
    open_position: dict[str, Any] | None,
    closed_positions: list[dict[str, Any]],
    timeframe: str = "5m",
) -> list[dict[str, Any]]:
    """
    Entry/exit markers from real paper positions only.
    One entry marker per open or closed trade — no replay simulation.
    """
    markers: list[dict[str, Any]] = []
    seen: set[int] = set()

    def _add(candle_time: int | None, *, status: str, side: str = "BUY") -> None:
        if candle_time is None or candle_time in seen:
            return
        seen.add(candle_time)
        markers.append({
            "candle_time": candle_time,
            "signal": side,
            "status": status,
            "timeframe": timeframe,
            "source": "paper_trade",
        })

    window_start = min(candle_times) if candle_times else 0
    window_end = max(candle_times) if candle_times else 0

    for tr in closed_positions:
        entry_unix = _iso_to_unix(tr.get("opened_at"))
        exit_unix = _iso_to_unix(tr.get("closed_at"))
        if entry_unix is None:
            continue
        if entry_unix > window_end or (exit_unix and exit_unix < window_start):
            continue
        _add(_snap_candle_time(entry_unix, candle_times), status="ENTRY", side=tr.get("side", "BUY"))
        if exit_unix:
            _add(
                _snap_candle_time(exit_unix, candle_times),
                status=_exit_status(tr.get("exit_reason")),
                side=tr.get("side", "BUY"),
            )

    if open_position:
        entry_unix = _iso_to_unix(open_position.get("opened_at"))
        if entry_unix is not None and window_start - 600 <= entry_unix <= window_end + 600:
            _add(_snap_candle_time(entry_unix, candle_times), status="ENTRY", side=open_position.get("side", "BUY"))

    return sorted(markers, key=lambda m: m["candle_time"])
