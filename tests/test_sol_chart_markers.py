"""Tests for paper-trade chart markers."""

from datetime import datetime, timezone

from app.strategies.sol_reversal.chart_markers import markers_from_paper_trades


def _candles_from_iso(start_iso: str, count: int = 10) -> list[int]:
    start = int(datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc).timestamp())
    return [start + i * 300 for i in range(count)]


def test_open_position_shows_single_entry_marker():
    candle_times = _candles_from_iso("2026-06-30T18:35:00+00:00", 12)
    open_pos = {
        "side": "BUY",
        "opened_at": "2026-06-30T18:40:00+00:00",
    }
    markers = markers_from_paper_trades(
        candle_times,
        open_position=open_pos,
        closed_positions=[],
    )
    entries = [m for m in markers if m["status"] == "ENTRY"]
    assert len(entries) == 1
    assert entries[0]["candle_time"] == candle_times[1]


def test_closed_trade_shows_entry_and_exit():
    candle_times = _candles_from_iso("2026-06-30T18:35:00+00:00", 30)
    closed = [{
        "side": "BUY",
        "opened_at": "2026-06-30T18:40:00+00:00",
        "closed_at": "2026-06-30T19:40:00+00:00",
        "exit_reason": "SL",
    }]
    markers = markers_from_paper_trades(
        candle_times,
        open_position=None,
        closed_positions=closed,
    )
    assert any(m["status"] == "ENTRY" for m in markers)
    assert any(m["status"] == "SL_HIT" for m in markers)
