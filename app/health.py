"""Health and readiness checks for production monitoring."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.database import get_connection
from app.market_data import store
from app.services.email_service import email_service
from app.services.paper_trading_service import PaperTradingService
from app.services.pushover_service import pushover_service
from app.services.signal_service import SignalService
from app.services.telegram_service import telegram_service

signal_service = SignalService()
paper_service = PaperTradingService()


def _subsystem(status: str, detail: str | None = None) -> dict[str, Any]:
    public = "healthy" if status == "ok" else status
    return {"status": public, "detail": detail}


def check_database() -> dict[str, Any]:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return _subsystem("ok")
    except Exception as exc:
        return _subsystem("fail", str(exc))


def check_market_data() -> dict[str, Any]:
    ready, total = store.cache_pair_counts()
    last_error = store.last_error
    if ready == 0:
        return _subsystem("fail", last_error or "No cached candle data")
    if last_error:
        return _subsystem("degraded", last_error)
    if ready < total:
        return _subsystem("degraded", f"{ready}/{total} symbol/timeframe pairs cached")
    return _subsystem("ok", f"{ready}/{total} pairs cached")


def check_signal_engine() -> dict[str, Any]:
    try:
        latest = signal_service.get_latest_signal()
        if latest is None and store.last_refresh is None:
            return _subsystem("degraded", "No signals persisted yet")
        return _subsystem("ok", f"Latest signal id={latest['id']}" if latest else "Engine idle")
    except Exception as exc:
        return _subsystem("fail", str(exc))


def check_paper_trading() -> dict[str, Any]:
    try:
        summary = paper_service.get_account_summary(store.get_latest_prices())
        open_count = paper_service.repository.list_open()
        return _subsystem(
            "ok",
            f"Balance={summary['balance']:.2f} open={len(open_count)}",
        )
    except Exception as exc:
        return _subsystem("fail", str(exc))


def check_notifications() -> dict[str, Any]:
    channels: list[str] = []
    if pushover_service.is_configured():
        channels.append("Pushover")
    if telegram_service.is_configured():
        channels.append("Telegram")
    if email_service.is_configured():
        channels.append("Email")
    if not channels:
        return _subsystem("degraded", "No server push channels configured")
    return _subsystem("ok", ", ".join(channels))


def build_health_payload() -> dict[str, Any]:
    market = check_market_data()
    database = check_database()
    signals = check_signal_engine()
    paper = check_paper_trading()
    notifications = check_notifications()
    ready, total = store.cache_pair_counts()

    subsystems = [market, database, signals, paper, notifications]
    if any(s["status"] == "fail" for s in subsystems):
        overall = "fail"
    elif any(s["status"] == "degraded" for s in subsystems):
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "last_refresh": store.last_refresh,
        "last_error": store.last_error,
        "cache_ready": ready > 0,
        "cached_pairs": ready,
        "total_pairs": total,
        "refresh_interval_seconds": settings.refresh_interval_seconds,
        "market_data": market,
        "database": database,
        "signal_engine": signals,
        "paper_trading": paper,
        "notifications": notifications,
    }
