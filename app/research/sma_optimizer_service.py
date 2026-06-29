"""Background SMA parameter grid optimizer (research only)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from app.research.candle_cache import fetch_candles_range, months_back_range
from app.research.sma_crossover_sim import compute_sma
from app.research.sma_optimizer_engine import (
    candles_to_arrays,
    sma_optimizer_worker,
)
from app.research.sma_optimizer_grid import build_sma_grid

logger = logging.getLogger(__name__)

HEAVY_KEYS = ("trades",)


def _strip(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in HEAVY_KEYS}


def _sorted_results(results: list[dict[str, Any]], sort_by: str = "score") -> list[dict[str, Any]]:
    reverse = sort_by != "max_drawdown_points"
    return sorted(results, key=lambda r: float(r.get(sort_by) or 0), reverse=reverse)


@dataclass
class SmaOptimizerJob:
    job_id: str
    status: str = "pending"
    request: dict[str, Any] = field(default_factory=dict)
    grid_plan: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    completed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    date_tested: str | None = None
    current_param: dict[str, Any] | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _executor: ProcessPoolExecutor | None = None
    candles_cache: dict[str, Any] | None = None
    sma_cache: dict[str, list[float]] = field(default_factory=dict)

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
        cur = self.current_param or {}
        return {
            "job_id": self.job_id,
            "status": self.status,
            "total": self.total,
            "completed": self.completed,
            "remaining": remaining,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta,
            "error": self.error,
            "current_sma": cur.get("sma_length"),
            "current_stop": cur.get("stop_points"),
            "current_target": cur.get("target_points"),
            "current_param": cur,
            "grid_plan": self.grid_plan,
            "date_tested": self.date_tested,
        }

    def top_results(self, limit: int = 20, sort_by: str = "score") -> list[dict[str, Any]]:
        rows = [_strip(r) for r in _sorted_results(self.results, sort_by)[:limit]]
        for i, row in enumerate(rows, start=1):
            row["rank"] = i
        return rows


class SmaOptimizerService:
    def __init__(self) -> None:
        self._jobs: dict[str, SmaOptimizerJob] = {}
        self._lock = threading.Lock()

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = build_sma_grid(request)
        return {k: v for k, v in plan.items() if k != "combinations"}

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = build_sma_grid(request)
        combos = plan["combinations"]
        job_id = str(uuid.uuid4())
        job = SmaOptimizerJob(
            job_id=job_id,
            request=request,
            grid_plan=self.preview(request),
            total=len(combos),
        )
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job_id, combos), daemon=True)
        job._thread = thread
        thread.start()
        return {"job_id": job_id, "grid_plan": job.grid_plan, "total_combinations": job.total}

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

    def get_progress(self, job_id: str) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        return job.progress() if job else None

    def get_results(
        self,
        job_id: str,
        *,
        sort_by: str = "score",
        include_trades: bool = False,
    ) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        if include_trades:
            rows = _sorted_results(job.results, sort_by)
        else:
            rows = [_strip(r) for r in _sorted_results(job.results, sort_by)]
        top = job.top_results(20, sort_by)
        return {
            "job_id": job_id,
            "status": job.status,
            "progress": job.progress(),
            "grid_plan": job.grid_plan,
            "sort_by": sort_by,
            "top_results": top,
            "results": rows,
            "date_tested": job.date_tested,
        }

    def get_trades(self, job_id: str, result_index: int, sort_by: str = "score") -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        sorted_rows = _sorted_results(job.results, sort_by)
        if result_index < 0 or result_index >= len(sorted_rows):
            return None
        row = sorted_rows[result_index]
        rank = None
        for i, r in enumerate(_sorted_results(job.results, sort_by), start=1):
            if (
                r["sma_length"] == row["sma_length"]
                and r["stop_points"] == row["stop_points"]
                and r["target_points"] == row["target_points"]
            ):
                rank = i
                break
        return {
            "job_id": job_id,
            "result_index": result_index,
            "rank": rank,
            "params": {
                "sma_length": row["sma_length"],
                "stop_points": row["stop_points"],
                "target_points": row["target_points"],
            },
            "metrics": _strip(row),
            "trades": row.get("trades") or [],
        }

    def heatmap(
        self,
        job_id: str,
        *,
        chart: str,
        fix_sma: int | None = None,
        fix_stop: float | None = None,
        fix_target: float | None = None,
        metric: str = "win_rate",
    ) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job or not job.results:
            return None

        def metric_val(r: dict[str, Any]) -> float:
            return float(r.get(metric) or 0)

        if chart in ("sma_win_rate", "sma_pf", "sma_net"):
            subset = list(job.results)
            if fix_stop is not None and fix_target is not None:
                subset = [
                    r for r in subset
                    if abs(float(r["stop_points"]) - fix_stop) < 1e-6
                    and abs(float(r["target_points"]) - fix_target) < 1e-6
                ]
            buckets: dict[int, list[float]] = {}
            for r in subset:
                key = int(r["sma_length"])
                buckets.setdefault(key, []).append(metric_val(r))
            xs = sorted(buckets.keys())
            ys = [round(sum(buckets[x]) / len(buckets[x]), 4) for x in xs]
            return {"chart": chart, "x_labels": xs, "y_values": ys, "metric": metric}

        if chart == "tp_sl":
            sma = fix_sma or int(job.top_results(1)[0]["sma_length"])
            subset = [r for r in job.results if int(r["sma_length"]) == sma]
            stops = sorted({float(r["stop_points"]) for r in subset})
            targets = sorted({float(r["target_points"]) for r in subset})
            lookup = {
                (float(r["stop_points"]), float(r["target_points"])): metric_val(r)
                for r in subset
            }
            grid = []
            for stop in stops:
                row = [lookup.get((stop, tgt)) for tgt in targets]
                grid.append(row)
            return {
                "chart": chart,
                "x_labels": targets,
                "y_labels": stops,
                "grid": grid,
                "metric": metric,
                "fixed_sma": sma,
            }

        if chart == "sma_target":
            stop = fix_stop or float(job.top_results(1)[0]["stop_points"])
            subset = [r for r in job.results if abs(float(r["stop_points"]) - stop) < 1e-6]
            smas = sorted({int(r["sma_length"]) for r in subset})
            targets = sorted({float(r["target_points"]) for r in subset})
            lookup = {
                (int(r["sma_length"]), float(r["target_points"])): metric_val(r)
                for r in subset
            }
            grid = [[lookup.get((sma, tgt)) for tgt in targets] for sma in smas]
            return {
                "chart": chart,
                "x_labels": targets,
                "y_labels": smas,
                "grid": grid,
                "metric": metric,
                "fixed_stop": stop,
            }

        if chart == "sma_stop":
            target = fix_target or float(job.top_results(1)[0]["target_points"])
            subset = [r for r in job.results if abs(float(r["target_points"]) - target) < 1e-6]
            smas = sorted({int(r["sma_length"]) for r in subset})
            stops = sorted({float(r["stop_points"]) for r in subset})
            lookup = {
                (int(r["sma_length"]), float(r["stop_points"])): metric_val(r)
                for r in subset
            }
            grid = [[lookup.get((sma, stop)) for stop in stops] for sma in smas]
            return {
                "chart": chart,
                "x_labels": stops,
                "y_labels": smas,
                "grid": grid,
                "metric": metric,
                "fixed_target": target,
            }

        return None

    def _precompute_smas(self, job: SmaOptimizerJob, candles: pd.DataFrame, lengths: list[int]) -> None:
        close = candles["close"].to_numpy(dtype=np.float64)
        for length in sorted(set(lengths)):
            sma = compute_sma(close, length)
            job.sma_cache[str(length)] = sma.tolist()

    def _run_job(self, job_id: str, combos: list[dict[str, Any]]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = time.time()
        job.date_tested = datetime.now(timezone.utc).isoformat()
        req = job.request

        try:
            start_date, end_date = months_back_range(int(req.get("months_back", 6)))
            candles = fetch_candles_range(
                req["symbol"],
                start_date,
                end_date,
                resolution=req.get("timeframe", "5m"),
                use_cache=True,
            )
            job.candles_cache = candles_to_arrays(candles)
            lengths = [int(c["sma_length"]) for c in combos]
            self._precompute_smas(job, candles, lengths)

            ambiguous = req.get("ambiguous", "STOP_FIRST")
            payloads = [
                {
                    "candles": job.candles_cache,
                    "sma_cache": job.sma_cache,
                    "sma_length": c["sma_length"],
                    "stop_points": c["stop_points"],
                    "target_points": c["target_points"],
                    "ambiguous": ambiguous,
                }
                for c in combos
            ]

            workers = min(6, max(1, len(payloads) // 100))
            use_pool = workers > 1 and len(payloads) > 16

            if use_pool:
                job._executor = ProcessPoolExecutor(max_workers=workers)
                future_map: dict[Future, dict[str, Any]] = {}
                for combo, payload in zip(combos, payloads):
                    if job._stop.is_set():
                        break
                    job.current_param = combo
                    fut = job._executor.submit(sma_optimizer_worker, payload)
                    future_map[fut] = combo
                for fut in as_completed(future_map):
                    if job._stop.is_set():
                        break
                    job.current_param = future_map[fut]
                    try:
                        job.results.append(fut.result())
                    except Exception as exc:
                        logger.exception("SMA optimizer worker failed: %s", exc)
                    job.completed += 1
                job._executor.shutdown(wait=False)
            else:
                for combo, payload in zip(combos, payloads):
                    if job._stop.is_set():
                        break
                    job.current_param = combo
                    job.results.append(sma_optimizer_worker(payload))
                    job.completed += 1

            job.status = "stopped" if job._stop.is_set() else "completed"
        except Exception as exc:
            logger.exception("SMA optimizer job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            job.current_param = None


sma_optimizer_service = SmaOptimizerService()
