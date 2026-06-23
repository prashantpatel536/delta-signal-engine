"""Historical replay for missed-opportunity recalculation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

from app.config import RESOLUTION_SECONDS, settings
from app.paper_trader import (
    check_candle_exit,
    excursion_points,
    realized_points,
    reward_points,
    risk_points,
)
from app.services.missed_opportunity_service import (
    MISSED_EXIT_OPPOSITE,
    MISSED_EXIT_SL,
    MISSED_EXIT_TP,
)

ProgressCallback = Callable[[int, int, int], None]


def parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def infer_restore_status(record: dict[str, Any]) -> str:
    """Guess REJECTED vs EXPIRED when a missed trade never resolves."""
    created = parse_utc(record.get("created_at"))
    started = parse_utc(record.get("monitoring_started_at"))
    if created and started:
        gap = started - created
        expiry = timedelta(minutes=settings.pending_signal_expiry_minutes)
        if gap >= expiry * 0.75:
            return "EXPIRED"
    return "REJECTED"


@dataclass(frozen=True)
class RecalcOutcome:
    resolved: bool
    status: str
    points_captured: float | None
    exit_reason: str | None
    exit_price: float | None
    max_favorable_excursion: float
    max_adverse_excursion: float
    missed_resolved_at: str | None
    missed_pnl_usd: float | None = None
    missed_roe_pct: float | None = None
    missed_account_impact_pct: float | None = None


@dataclass(frozen=True)
class _TimelineEvent:
    at: datetime
    kind: str
    payload: dict[str, Any]

    @property
    def sort_key(self) -> tuple[datetime, int]:
        # Opposite signals at bar close take precedence over TP/SL on the same bar.
        kind_order = 0 if self.kind == "opposite" else 1
        return (self.at, kind_order)


def evaluate_missed_record(
    record: dict[str, Any],
    *,
    all_signals: Iterable[dict[str, Any]],
    candles: list[dict[str, Any]],
    monitor_hours: int | None = None,
) -> RecalcOutcome:
    """Replay TP / SL / opposite-signal rules for one missed opportunity."""
    hours = monitor_hours if monitor_hours is not None else settings.missed_opportunity_monitor_hours
    side = record["side"]
    entry = float(record["entry"])
    sl = float(record["stop_loss"])
    tp = float(record["take_profit"])

    start_dt = parse_utc(record.get("monitoring_started_at")) or parse_utc(record.get("updated_at"))
    if start_dt is None:
        start_dt = parse_utc(record.get("created_at")) or datetime.now(timezone.utc)

    end_dt = min(
        datetime.now(timezone.utc),
        start_dt + timedelta(hours=hours),
    )

    opposite_side = "SELL" if side == "BUY" else "BUY"
    events: list[_TimelineEvent] = []

    for signal in all_signals:
        if int(signal["id"]) <= int(record["id"]):
            continue
        if signal["symbol"] != record["symbol"]:
            continue
        if signal["timeframe"] != record["timeframe"]:
            continue
        if signal["side"] != opposite_side:
            continue
        at = parse_utc(signal.get("created_at"))
        if at is None or at < start_dt or at > end_dt:
            continue
        events.append(
            _TimelineEvent(
                at=at,
                kind="opposite",
                payload={"entry": float(signal["entry"]), "signal_id": int(signal["id"])},
            )
        )

    interval = RESOLUTION_SECONDS.get(record["timeframe"], 300)
    for candle in candles:
        bar_time = int(candle["time"])
        at = datetime.fromtimestamp(bar_time + interval, tz=timezone.utc)
        if at < start_dt or at > end_dt:
            continue
        events.append(
            _TimelineEvent(
                at=at,
                kind="candle",
                payload={
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                },
            )
        )

    events.sort(key=lambda event: event.sort_key)

    mfe = 0.0
    mae = 0.0
    for event in events:
        if event.kind == "candle":
            fav_high, _ = excursion_points(side, entry, float(event.payload["high"]))
            _, adv_low = excursion_points(side, entry, float(event.payload["low"]))
            mfe = max(mfe, fav_high)
            mae = max(mae, adv_low)

            reason, exit_price = check_candle_exit(
                side,
                high=event.payload["high"],
                low=event.payload["low"],
                stop_loss=sl,
                take_profit=tp,
            )
            if reason == "TP":
                points = reward_points(side, entry, tp)
                return RecalcOutcome(
                    resolved=True,
                    status="MISSED_WINNER",
                    points_captured=points,
                    exit_reason=MISSED_EXIT_TP,
                    exit_price=float(exit_price or tp),
                    max_favorable_excursion=mfe,
                    max_adverse_excursion=mae,
                    missed_resolved_at=event.at.isoformat(),
                )
            if reason == "SL":
                points = -risk_points(side, entry, sl)
                return RecalcOutcome(
                    resolved=True,
                    status="MISSED_LOSER",
                    points_captured=points,
                    exit_reason=MISSED_EXIT_SL,
                    exit_price=float(exit_price or sl),
                    max_favorable_excursion=mfe,
                    max_adverse_excursion=mae,
                    missed_resolved_at=event.at.isoformat(),
                )
        elif event.kind == "opposite":
            exit_price = float(event.payload["entry"])
            points = realized_points(side, entry, exit_price)
            status = "MISSED_WINNER" if points > 0 else "MISSED_LOSER"
            return RecalcOutcome(
                resolved=True,
                status=status,
                points_captured=points,
                exit_reason=MISSED_EXIT_OPPOSITE,
                exit_price=exit_price,
                max_favorable_excursion=mfe,
                max_adverse_excursion=mae,
                missed_resolved_at=event.at.isoformat(),
            )

    restore = infer_restore_status(record)
    return RecalcOutcome(
        resolved=False,
        status=restore,
        points_captured=None,
        exit_reason=None,
        exit_price=None,
        max_favorable_excursion=mfe,
        max_adverse_excursion=mae,
        missed_resolved_at=None,
    )


def candles_from_dataframe(df) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        )
    return rows
