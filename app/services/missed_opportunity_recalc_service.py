"""One-time and on-demand historical missed-opportunity recalculation."""

from __future__ import annotations

import logging
from typing import Any, Callable

from app.config import settings
from app.market_data import delta_client
from app.missed_recalc import (
    ProgressCallback,
    RecalcOutcome,
    candles_from_dataframe,
    evaluate_missed_record,
    parse_utc,
)
from app.models import utc_now_iso
from app.repositories.signal_repository import SignalRepository

logger = logging.getLogger(__name__)


class MissedOpportunityRecalcService:
    def __init__(
        self,
        repository: SignalRepository | None = None,
        *,
        candle_fetcher=None,
    ) -> None:
        self.repository = repository or SignalRepository()
        self._fetch_candles = candle_fetcher or delta_client.fetch_candles

    def recalculate_all(
        self,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        candidates = self.repository.list_missed_recalc_candidates()
        signal_index = self.repository.list_signal_recalc_index()
        candle_cache = self._build_candle_cache(candidates)

        records_out: list[dict[str, Any]] = []
        changed = 0

        for index, record in enumerate(candidates, start=1):
            signal_id = int(record["id"])
            if progress:
                progress(index, len(candidates), signal_id)

            candles = candle_cache.get((record["symbol"], record["timeframe"]), [])
            outcome = evaluate_missed_record(
                record,
                all_signals=signal_index,
                candles=candles,
            )
            before = self._snapshot(record)
            updated = self.repository.apply_recalculated_missed(signal_id, outcome)
            after = self._snapshot(updated) if updated else before
            if self._changed(before, after):
                changed += 1

            records_out.append(
                {
                    "signal_id": signal_id,
                    "symbol": record["symbol"],
                    "before": before,
                    "after": after,
                }
            )
            logger.info(
                "Missed recalc id=%s %s → %s pts=%s exit=%s",
                signal_id,
                before.get("status"),
                after.get("status"),
                after.get("points_captured"),
                after.get("missed_exit_reason"),
            )

        summary = self.repository.get_missed_summary()
        return {
            "ok": True,
            "recalculated": len(candidates),
            "changed": changed,
            "unchanged": len(candidates) - changed,
            "summary": summary,
            "records": records_out,
        }

    def _build_candle_cache(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        windows: dict[tuple[str, str], tuple[Any, Any]] = {}
        now = parse_utc(utc_now_iso())

        for record in candidates:
            key = (record["symbol"], record["timeframe"])
            start = parse_utc(record.get("monitoring_started_at")) or parse_utc(
                record.get("updated_at")
            )
            if start is None:
                continue
            end = now
            current = windows.get(key)
            if current is None:
                windows[key] = (start, end)
            else:
                windows[key] = (min(current[0], start), max(current[1], end))

        cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for (symbol, timeframe), (start_dt, end_dt) in windows.items():
            cache[(symbol, timeframe)] = self._fetch_candles_for_window(
                symbol,
                timeframe,
                start_dt,
                end_dt,
            )
        return cache

    def _fetch_candles_for_window(
        self,
        symbol: str,
        timeframe: str,
        start_dt,
        end_dt,
    ) -> list[dict[str, Any]]:
        from datetime import timedelta

        from app.config import RESOLUTION_SECONDS

        interval = RESOLUTION_SECONDS.get(timeframe, 300)
        window_seconds = max(int((end_dt - start_dt).total_seconds()), interval)
        bars_needed = int(window_seconds / interval) + 20
        limit = min(max(bars_needed, 50), settings.candle_limit)
        try:
            df = self._fetch_candles(symbol, timeframe, limit=limit)
        except Exception as exc:
            logger.warning(
                "Missed recalc candle fetch failed for %s %s: %s",
                symbol,
                timeframe,
                exc,
            )
            return []

        candles = candles_from_dataframe(df)
        start_ts = int(start_dt.timestamp())
        end_ts = int(end_dt.timestamp()) + interval
        return [bar for bar in candles if start_ts <= int(bar["time"]) <= end_ts]

    @staticmethod
    def _snapshot(record: dict[str, Any] | None) -> dict[str, Any]:
        if not record:
            return {}
        return {
            "status": record.get("status"),
            "points_captured": record.get("points_captured"),
            "missed_exit_reason": record.get("missed_exit_reason"),
            "missed_exit_price": record.get("missed_exit_price"),
            "max_favorable_excursion": record.get("max_favorable_excursion"),
            "max_adverse_excursion": record.get("max_adverse_excursion"),
        }

    @staticmethod
    def _changed(before: dict[str, Any], after: dict[str, Any]) -> bool:
        keys = (
            "status",
            "points_captured",
            "missed_exit_reason",
            "missed_exit_price",
            "max_favorable_excursion",
            "max_adverse_excursion",
        )
        for key in keys:
            if before.get(key) != after.get(key):
                return True
        return False


missed_opportunity_recalc_service = MissedOpportunityRecalcService()
