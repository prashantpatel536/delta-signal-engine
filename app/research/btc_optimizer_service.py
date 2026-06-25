"""Background BTC parameter grid optimizer (research only)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.research.btc_backtest_engine import (
    BtcBacktestParams,
    backtest_worker_payload,
    candles_to_arrays,
    run_btc_backtest,
)
from app.research.historical_data import fetch_btc_candles_range
from app.research.scoring import overall_score

logger = logging.getLogger(__name__)


def _frange(start: float, end: float, step: float) -> list[float]:
    if step <= 0:
        raise ValueError("step must be positive")
    values: list[float] = []
    current = float(start)
    end_f = float(end)
    while current <= end_f + 1e-9:
        values.append(round(current, 6))
        current += step
    return values


def _int_range(start: float, end: float, step: float) -> list[int]:
    return [int(v) for v in _frange(start, end, step)]


def build_param_combinations(request: dict[str, Any]) -> list[dict[str, float]]:
    gaps = _frange(request["gap_start"], request["gap_end"], request["gap_step"])
    min_sls = _int_range(request["min_sl_start"], request["min_sl_end"], request["min_sl_step"])
    max_sls = _int_range(request["max_sl_start"], request["max_sl_end"], request["max_sl_step"])
    combos: list[dict[str, float]] = []
    for gap in gaps:
        for min_sl in min_sls:
            for max_sl in max_sls:
                if min_sl <= max_sl:
                    combos.append({
                        "gap_filter_pct": gap,
                        "min_sl_points": float(min_sl),
                        "max_sl_points": float(max_sl),
                    })
    return combos


@dataclass
class OptimizerJob:
    job_id: str
    status: str = "pending"
    request: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    completed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _executor: ProcessPoolExecutor | None = None
    candles_cache: dict[str, Any] | None = None

    def progress(self) -> dict[str, Any]:
        elapsed = 0.0
        if self.started_at:
            elapsed = (self.finished_at or time.time()) - self.started_at
        remaining = max(self.total - self.completed, 0)
        eta = None
        if self.completed > 0 and self.status == "running":
            rate = self.completed / elapsed
            if rate > 0:
                eta = round(remaining / rate, 1)
        return {
            "job_id": self.job_id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "remaining": remaining,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta,
            "error": self.error,
        }

    def best_result(self) -> dict[str, Any] | None:
        if not self.results:
            return None
        return max(self.results, key=lambda r: float(r.get("score") or 0))


class BtcOptimizerService:
    """In-memory job store — research workloads only."""

    def __init__(self) -> None:
        self._jobs: dict[str, OptimizerJob] = {}
        self._lock = threading.Lock()

    def start(self, request: dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        combos = build_param_combinations(request)
        job = OptimizerJob(job_id=job_id, request=request, total=len(combos))
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job_id,), daemon=True)
        job._thread = thread
        thread.start()
        return job_id

    def stop(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        job._stop.set()
        if job._executor:
            job._executor.shutdown(wait=False, cancel_futures=True)
        job.status = "stopped"
        job.finished_at = time.time()
        return True

    def get_job(self, job_id: str) -> OptimizerJob | None:
        return self._jobs.get(job_id)

    def get_progress(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return job.progress() if job else None

    def get_results(self, job_id: str, *, include_trades: bool = False) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        rows = sorted(job.results, key=lambda r: float(r.get("score") or 0), reverse=True)
        if not include_trades:
            rows = [{k: v for k, v in row.items() if k != "trades"} for row in rows]
        return {
            "job_id": job_id,
            "status": job.status,
            "progress": job.progress(),
            "best": job.best_result(),
            "results": rows,
        }

    def get_trades(self, job_id: str, result_index: int) -> list[dict[str, Any]] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        sorted_rows = sorted(job.results, key=lambda r: float(r.get("score") or 0), reverse=True)
        if result_index < 0 or result_index >= len(sorted_rows):
            return None
        return sorted_rows[result_index].get("trades") or []

    def heatmap(
        self,
        job_id: str,
        *,
        gap_filter_pct: float,
        metric: str = "profit_factor",
    ) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        subset = [
            r for r in job.results
            if abs(float(r.get("gap_filter_pct") or 0) - gap_filter_pct) < 1e-6
        ]
        min_sls = sorted({int(r["min_sl_points"]) for r in subset})
        max_sls = sorted({int(r["max_sl_points"]) for r in subset})
        grid: list[list[float | None]] = []
        lookup = {
            (int(r["min_sl_points"]), int(r["max_sl_points"])): float(r.get(metric) or 0)
            for r in subset
        }
        for min_sl in min_sls:
            row: list[float | None] = []
            for max_sl in max_sls:
                row.append(lookup.get((min_sl, max_sl)))
            grid.append(row)
        return {
            "gap_filter_pct": gap_filter_pct,
            "metric": metric,
            "min_sl_labels": min_sls,
            "max_sl_labels": max_sls,
            "grid": grid,
        }

    def _run_job(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = time.time()
        req = job.request

        try:
            candles = fetch_btc_candles_range(
                req["start_date"],
                req["end_date"],
                resolution=req.get("timeframe", "5m"),
            )
            job.candles_cache = candles_to_arrays(candles)
            combos = build_param_combinations(req)
            base_params = {
                "initial_capital": float(req.get("initial_capital", 1000)),
                "commission_pct": float(req.get("commission_pct", 0)),
                "leverage": float(req.get("leverage", 25)),
                "margin_percent": float(req.get("margin_percent", 50)),
                "timeframe": req.get("timeframe", "5m"),
            }

            workers = min(4, max(1, (len(combos) // 50) or 1))
            payloads = [
                {
                    "candles": job.candles_cache,
                    "params": {**base_params, **combo},
                }
                for combo in combos
            ]

            if workers > 1 and len(payloads) > 8:
                job._executor = ProcessPoolExecutor(max_workers=workers)
                futures: list[Future] = [
                    job._executor.submit(backtest_worker_payload, p) for p in payloads
                ]
                for fut in as_completed(futures):
                    if job._stop.is_set():
                        break
                    try:
                        job.results.append(fut.result())
                    except Exception as exc:
                        logger.exception("Optimizer worker failed: %s", exc)
                    job.completed += 1
                job._executor.shutdown(wait=False)
            else:
                for payload in payloads:
                    if job._stop.is_set():
                        break
                    job.results.append(backtest_worker_payload(payload))
                    job.completed += 1

            if job._stop.is_set():
                job.status = "stopped"
            else:
                job.status = "completed"
        except Exception as exc:
            logger.exception("Optimizer job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()


btc_optimizer_service = BtcOptimizerService()
