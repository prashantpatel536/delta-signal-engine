"""Background SOL parameter grid optimizer (research only)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

from app.backtest.candle_store import get_candles
from app.strategies.sol_reversal.optimizer_param_grid import analyze_sol_param_grid
from app.strategies.sol_reversal.optimizer_worker import ohlc_to_arrays, sol_optimizer_worker
from app.strategies.sol_reversal.settings_defaults import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

HEAVY_KEYS = ("trades",)


def _strip_heavy(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in HEAVY_KEYS}


@dataclass
class SolOptimizerJob:
    job_id: str
    status: str = "pending"
    request: dict[str, Any] = field(default_factory=dict)
    grid_plan: dict[str, Any] = field(default_factory=dict)
    total: int = 0
    completed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    current_param: dict[str, Any] | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None
    _executor: ProcessPoolExecutor | None = None
    ohlc_cache: dict[str, Any] | None = None

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
            "current_param": self.current_param,
            "grid_plan": self.grid_plan,
        }


class SolOptimizerService:
    def __init__(self) -> None:
        self._jobs: dict[str, SolOptimizerJob] = {}
        self._lock = threading.Lock()

    def preview(self, request: dict[str, Any]) -> dict[str, Any]:
        return analyze_sol_param_grid(request)

    def start(self, request: dict[str, Any]) -> dict[str, Any]:
        plan = analyze_sol_param_grid(request)
        combos = plan["combinations"]
        job_id = str(uuid.uuid4())
        job = SolOptimizerJob(
            job_id=job_id,
            request=request,
            grid_plan=plan,
            total=len(combos),
        )
        with self._lock:
            self._jobs[job_id] = job
        thread = threading.Thread(target=self._run_job, args=(job_id, combos), daemon=True)
        job._thread = thread
        thread.start()
        return {"job_id": job_id, "grid_plan": plan, "total_combinations": job.total}

    def stop(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return False
        job._stop.set()
        return True

    def get_progress(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        return job.progress() if job else None

    def get_results(
        self,
        job_id: str,
        *,
        include_trades: bool = False,
        limit: int = 100,
    ) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None
        ranked = sorted(job.results, key=lambda r: float(r.get("score") or 0), reverse=True)
        rows = ranked if include_trades else [_strip_heavy(r) for r in ranked[:limit]]
        return {
            "job_id": job_id,
            "status": job.status,
            "grid_plan": job.grid_plan,
            "results": rows,
            "best": _strip_heavy(ranked[0]) if ranked else None,
        }

    def get_trades(self, job_id: str, result_index: int) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return None
        ranked = sorted(job.results, key=lambda r: float(r.get("score") or 0), reverse=True)
        if result_index < 0 or result_index >= len(ranked):
            return None
        row = ranked[result_index]
        return {"params": {k: row.get(k) for k in job.grid_plan.get("axis_names", [])}, "trades": row.get("trades", [])}

    def _run_job(self, job_id: str, combos: list[dict[str, Any]]) -> None:
        with self._lock:
            job = self._jobs[job_id]
        req = job.request
        try:
            job.status = "running"
            job.started_at = time.time()

            symbol = req.get("symbol", "SOLUSDT")
            timeframe = req.get("timeframe", "5m")
            ohlc = get_candles(symbol, timeframe, req["start_date"], req["end_date"])
            if ohlc.empty:
                raise ValueError("No candle data for optimizer range")
            job.ohlc_cache = ohlc_to_arrays(ohlc)

            base_settings = {**DEFAULT_SETTINGS, **(req.get("base_settings") or {})}
            workers = int(req.get("workers", 2))
            job._executor = ProcessPoolExecutor(max_workers=max(1, workers))

            futures = []
            for combo in combos:
                if job._stop.is_set():
                    break
                payload = {
                    "ohlc": job.ohlc_cache,
                    "base_settings": base_settings,
                    "param_overrides": combo,
                    "initial_capital": float(req.get("initial_capital", 1000)),
                    "commission_pct": float(req.get("commission_pct", 0.05)),
                    "slippage_pct": float(req.get("slippage_pct", 0.02)),
                    "symbol": symbol,
                    "timeframe": timeframe,
                }
                futures.append((combo, job._executor.submit(sol_optimizer_worker, payload)))

            for combo, fut in futures:
                if job._stop.is_set():
                    break
                job.current_param = combo
                try:
                    result = fut.result()
                    job.results.append(result)
                except Exception as exc:
                    logger.exception("SOL optimizer worker failed: %s", exc)
                    job.results.append({**combo, "error": str(exc), "score": -9999})
                job.completed += 1

            job.status = "stopped" if job._stop.is_set() else "completed"
        except Exception as exc:
            logger.exception("SOL optimizer job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = time.time()
            job.current_param = None
            if job._executor:
                job._executor.shutdown(wait=False, cancel_futures=True)
                job._executor = None


sol_optimizer_service = SolOptimizerService()
