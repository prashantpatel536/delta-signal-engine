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
    backtest_worker_payload,
    candles_to_arrays,
)
from app.research.historical_data import fetch_btc_candles_range
from app.research.param_grid import analyze_param_grid

logger = logging.getLogger(__name__)

CURVE_KEYS = ("equity_curve", "drawdown_curve", "daily_profit_curve")
HEAVY_RESULT_KEYS = ("trades", *CURVE_KEYS)


def _strip_heavy_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in HEAVY_RESULT_KEYS}


def _sorted_rankable(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rankable = [r for r in results if r.get("rankable")]
    return sorted(rankable, key=lambda r: float(r.get("score") or 0), reverse=True)


def _sorted_all(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(results, key=lambda r: float(r.get("score") or 0), reverse=True)


@dataclass
class OptimizerJob:
    job_id: str
    status: str = "pending"
    request: dict[str, Any] = field(default_factory=dict)
    grid_plan: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    expected: int = 0
    skipped: int = 0
    completed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    debug_log: list[dict[str, Any]] = field(default_factory=list)
    current_param: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    date_tested: str | None = None
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
        current = self.current_param or {}
        payload = {
            "job_id": self.job_id,
            "status": self.status,
            "expected_combinations": self.expected,
            "total": self.total,
            "completed": self.completed,
            "skipped": self.skipped,
            "remaining": remaining,
            "elapsed_seconds": round(elapsed, 1),
            "eta_seconds": eta,
            "error": self.error,
            "current_gap": current.get("gap_filter_pct"),
            "current_min_sl": current.get("min_sl_points"),
            "current_max_sl": current.get("max_sl_points"),
            "current_param": current,
            "grid_plan": self.grid_plan,
            "date_tested": self.date_tested,
        }
        if self.request.get("debug"):
            payload["debug_log"] = self.debug_log[-200:]
        return payload

    def best_result(self) -> dict[str, Any] | None:
        ranked = _sorted_rankable(self.results)
        return ranked[0] if ranked else None

    def top_results(self, limit: int = 20) -> list[dict[str, Any]]:
        return [_strip_heavy_fields(r) for r in _sorted_rankable(self.results)[:limit]]


class BtcOptimizerService:
    """In-memory job store — research workloads only."""

    def __init__(self) -> None:
        self._jobs: dict[str, OptimizerJob] = {}
        self._lock = threading.Lock()

    def preview_grid(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = analyze_param_grid(request)
        return {
            "gap_values": plan["gap_values"],
            "gap_count": plan["gap_count"],
            "min_sl_values": plan["min_sl_values"],
            "min_sl_count": plan["min_sl_count"],
            "max_sl_values": plan["max_sl_values"],
            "max_sl_count": plan["max_sl_count"],
            "expected_combinations": plan["expected_combinations"],
            "skipped_combinations": plan["skipped_combinations"],
            "skip_reasons": plan["skip_reasons"],
            "final_tested_combinations": plan["final_tested_combinations"],
            "actual_generated_combinations": plan["actual_generated_combinations"],
            "combination_formula": plan["combination_formula"],
            "mismatch_reason": plan["mismatch_reason"],
        }

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = analyze_param_grid(request)
        combos = plan["combinations"]
        job_id = str(uuid.uuid4())
        job = OptimizerJob(
            job_id=job_id,
            request=request,
            grid_plan=self.preview_grid(request),
            total=len(combos),
            expected=plan["expected_combinations"],
            skipped=plan["skipped_combinations"],
        )
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run_job, args=(job_id, combos), daemon=True)
        job._thread = thread
        thread.start()
        return {
            "job_id": job_id,
            "grid_plan": job.grid_plan,
            "total_combinations": job.total,
        }

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

    def get_results(
        self,
        job_id: str,
        *,
        include_trades: bool = False,
        include_curves: bool = False,
    ) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None

        def shape(row: dict[str, Any]) -> dict[str, Any]:
            if include_trades and include_curves:
                return dict(row)
            if include_trades:
                return {k: v for k, v in row.items() if k not in CURVE_KEYS}
            if include_curves:
                return {k: v for k, v in row.items() if k != "trades"}
            return _strip_heavy_fields(row)

        all_rows = [shape(r) for r in _sorted_all(job.results)]
        top = job.top_results(20)
        for i, row in enumerate(top, start=1):
            row["rank"] = i

        best = job.best_result()
        return {
            "job_id": job_id,
            "status": job.status,
            "progress": job.progress(),
            "grid_plan": job.grid_plan,
            "best": _strip_heavy_fields(best) if best else None,
            "top_results": top,
            "rankable_count": sum(1 for r in job.results if r.get("rankable")),
            "results": all_rows,
            "date_tested": job.date_tested,
        }

    def get_result_detail(self, job_id: str, result_index: int) -> dict[str, Any] | None:
        job = self._jobs.get(job_id)
        if not job:
            return None
        sorted_rows = _sorted_all(job.results)
        if result_index < 0 or result_index >= len(sorted_rows):
            return None
        row = sorted_rows[result_index]
        rank = None
        if row.get("rankable"):
            rankable = _sorted_rankable(job.results)
            for i, r in enumerate(rankable, start=1):
                if (
                    r["gap_filter_pct"] == row["gap_filter_pct"]
                    and r["min_sl_points"] == row["min_sl_points"]
                    and r["max_sl_points"] == row["max_sl_points"]
                ):
                    rank = i
                    break
        return {
            "job_id": job_id,
            "result_index": result_index,
            "rank": rank,
            "result": row,
            "date_tested": job.date_tested,
        }

    def get_trades(self, job_id: str, result_index: int) -> dict[str, Any] | None:
        detail = self.get_result_detail(job_id, result_index)
        if not detail:
            return None
        row = detail["result"]
        return {
            "job_id": job_id,
            "result_index": result_index,
            "rank": detail.get("rank"),
            "params": {
                "gap_filter_pct": row.get("gap_filter_pct"),
                "min_sl_points": row.get("min_sl_points"),
                "max_sl_points": row.get("max_sl_points"),
            },
            "metrics": _strip_heavy_fields(row),
            "trades": row.get("trades") or [],
            "equity_curve": row.get("equity_curve") or [],
            "drawdown_curve": row.get("drawdown_curve") or [],
            "daily_profit_curve": row.get("daily_profit_curve") or [],
        }

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

    def _append_debug(self, job: OptimizerJob, entry: dict[str, Any]) -> None:
        if job.request.get("debug"):
            job.debug_log.append(entry)

    def _run_job(self, job_id: str, combos: list[dict[str, float]]) -> None:
        job = self._jobs.get(job_id)
        if not job:
            return
        job.status = "running"
        job.started_at = time.time()
        job.date_tested = datetime.now(timezone.utc).isoformat()
        req = job.request

        if req.get("debug"):
            plan = job.grid_plan
            self._append_debug(job, {
                "event": "grid_plan",
                "gap_values": plan.get("gap_values"),
                "min_sl_values": plan.get("min_sl_values"),
                "max_sl_values": plan.get("max_sl_values"),
                "combination_formula": plan.get("combination_formula"),
                "expected_combinations": plan.get("expected_combinations"),
                "skipped_combinations": plan.get("skipped_combinations"),
                "skip_reasons": plan.get("skip_reasons"),
                "final_tested_combinations": plan.get("final_tested_combinations"),
            })

        try:
            candles = fetch_btc_candles_range(
                req["start_date"],
                req["end_date"],
                resolution=req.get("timeframe", "5m"),
            )
            job.candles_cache = candles_to_arrays(candles)
            base_params = {
                "initial_capital": float(req.get("initial_capital", 1000)),
                "commission_pct": float(req.get("commission_pct", 0)),
                "leverage": float(req.get("leverage", 25)),
                "margin_percent": float(req.get("margin_percent", 50)),
                "timeframe": req.get("timeframe", "5m"),
            }

            payloads = [
                {"candles": job.candles_cache, "params": {**base_params, **combo}}
                for combo in combos
            ]

            workers = min(4, max(1, (len(payloads) // 50) or 1))
            use_pool = workers > 1 and len(payloads) > 8

            if use_pool:
                job._executor = ProcessPoolExecutor(max_workers=workers)
                future_map: dict[Future, dict[str, float]] = {}
                for combo, payload in zip(combos, payloads):
                    if job._stop.is_set():
                        break
                    job.current_param = combo
                    fut = job._executor.submit(backtest_worker_payload, payload)
                    future_map[fut] = combo

                for fut in as_completed(future_map):
                    if job._stop.is_set():
                        break
                    combo = future_map[fut]
                    job.current_param = combo
                    try:
                        row = fut.result()
                        job.results.append(row)
                        self._append_debug(job, {
                            "event": "backtest_complete",
                            "gap_filter_pct": combo.get("gap_filter_pct"),
                            "min_sl_points": combo.get("min_sl_points"),
                            "max_sl_points": combo.get("max_sl_points"),
                            "trades_found": row.get("trade_count"),
                            "score": row.get("score"),
                            "rankable": row.get("rankable"),
                            "skip_reason": row.get("rank_disqualify_reason"),
                        })
                    except Exception as exc:
                        logger.exception("Optimizer worker failed: %s", exc)
                        self._append_debug(job, {
                            "event": "worker_error",
                            "param": combo,
                            "error": str(exc),
                        })
                    job.completed += 1
                job._executor.shutdown(wait=False)
            else:
                for combo, payload in zip(combos, payloads):
                    if job._stop.is_set():
                        break
                    job.current_param = combo
                    try:
                        row = backtest_worker_payload(payload)
                        job.results.append(row)
                        self._append_debug(job, {
                            "event": "backtest_complete",
                            "gap_filter_pct": combo.get("gap_filter_pct"),
                            "min_sl_points": combo.get("min_sl_points"),
                            "max_sl_points": combo.get("max_sl_points"),
                            "trades_found": row.get("trade_count"),
                            "score": row.get("score"),
                            "rankable": row.get("rankable"),
                            "skip_reason": row.get("rank_disqualify_reason"),
                        })
                    except Exception as exc:
                        logger.exception("Optimizer backtest failed: %s", exc)
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
            job.current_param = None


btc_optimizer_service = BtcOptimizerService()

# Backward-compatible helper for tests
def build_param_combinations(request: dict[str, Any]) -> list[dict[str, float]]:
    return analyze_param_grid(request)["combinations"]
