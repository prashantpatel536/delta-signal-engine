"""FastAPI application entry point with background refresh scheduler."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from pathlib import Path

import pandas as pd

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import router as market_router
from app.approval_api import router as approval_router
from app.config import settings
from app.database import init_db
from app.indicators import calculate_indicators
from app.logging_config import setup_logging
from app.market_data import delta_client, store
from app.models import utc_now_iso
from app.paper_api import router as paper_router
from app.admin_api import router as admin_router
from app.pushover_api import router as pushover_router
from app.risk_api import router as risk_router
from app.validation_api import router as validation_router
from app.settings_api import router as settings_router
from app.telegram_api import router as telegram_router
from app.paper_trader import exit_status_label
from app.services.email_service import email_service
from app.services.pushover_service import pushover_service
from app.services.runtime_settings import get_signal_timeframe, initialize_signal_timeframe
from app.services.paper_trading_service import PaperTradingService
from app.services.missed_opportunity_service import missed_opportunity_service
from app.services.telegram_service import telegram_service
from app.services.signal_service import SignalService
from app.signals import generate_signals_for_pair

logger = logging.getLogger(__name__)
signal_service = SignalService()
paper_service = PaperTradingService()


async def refresh_market_data() -> None:
    """Fetch candles, recalculate indicators, and generate signals."""
    logger.info("Starting market data refresh cycle")
    signal_service.expire_stale_pending()
    cycle_errors: list[str] = []
    successful_updates = 0
    active_signal_tf = get_signal_timeframe()
    logger.info("Signal engine using timeframe: %s candles only", active_signal_tf)

    for short_symbol, delta_symbol in settings.symbol_map.items():
        store.ensure_symbol(delta_symbol)

        for timeframe in settings.timeframes:
            try:
                candles = await asyncio.to_thread(
                    delta_client.fetch_candles,
                    delta_symbol,
                    timeframe,
                )
                if candles.empty:
                    msg = f"Empty candles: {delta_symbol}/{timeframe}"
                    logger.warning("Skipping cache update — %s", msg)
                    cycle_errors.append(msg)
                    continue

                display_candles, enrich_stats = await asyncio.to_thread(
                    delta_client.resolve_ohlc_candles,
                    candles,
                    delta_symbol,
                    timeframe,
                )
                ohlc_candles = display_candles
                sma84, hh50, ll50 = calculate_indicators(ohlc_candles)
                signal = generate_signals_for_pair(
                    ohlc_candles,
                    sma84,
                    hh50,
                    ll50,
                    delta_symbol,
                    timeframe,
                )
                if signal is not None and timeframe == active_signal_tf:
                    hh_val = hh50.iloc[-1]
                    ll_val = ll50.iloc[-1]
                    if not pd.isna(hh_val) and not pd.isna(ll_val):
                        persisted = signal_service.persist_from_runtime_signal(
                            signal,
                            float(hh_val),
                            float(ll_val),
                        )
                        if persisted:
                            logger.info(
                                "Signal Generated: %s %s %s id=%s",
                                persisted["side"],
                                persisted["symbol"],
                                persisted["timeframe"],
                                persisted["id"],
                            )
                elif signal is not None and timeframe != active_signal_tf:
                    logger.debug(
                        "Skip signal persist for %s %s — active Signal TF is %s",
                        delta_symbol,
                        timeframe,
                        active_signal_tf,
                    )

                store.update(
                    delta_symbol,
                    timeframe,
                    ohlc_candles,
                    sma84,
                    hh50,
                    ll50,
                    signal,
                    display_candles=display_candles,
                )
                successful_updates += 1
                logger.info(
                    "Display candles %s %s: flat_before=%s enriched=%s flat_after=%s",
                    delta_symbol,
                    timeframe,
                    enrich_stats.get("flat_before"),
                    enrich_stats.get("enriched_from_mark"),
                    enrich_stats.get("flat_after"),
                )
            except Exception as exc:
                err = f"{delta_symbol}/{timeframe}: {exc}"
                cycle_errors.append(err)
                logger.exception(
                    "Refresh failed for %s (%s) %s",
                    short_symbol,
                    delta_symbol,
                    timeframe,
                )

    if successful_updates > 0:
        refresh_time = utc_now_iso()
        store.set_last_refresh(refresh_time)
    else:
        refresh_time = store.last_refresh

    if cycle_errors:
        store.set_last_error("; ".join(cycle_errors[-5:]))
    else:
        store.set_last_error(None)

    try:
        prices = store.get_latest_prices()
        if prices:
            closed = paper_service.monitor_positions(prices)
            for position in closed:
                reason = position.get("exit_reason")
                label = exit_status_label(reason) or reason
                logger.info(
                    "Trade Closed: id=%s %s %s pnl=%s (%s)",
                    position["id"],
                    position["symbol"],
                    position["side"],
                    position.get("pnl"),
                    label,
                )
                if reason == "TP":
                    logger.info("TP Hit: position id=%s", position["id"])
                elif reason == "SL":
                    logger.info("SL Hit: position id=%s", position["id"])
            if closed:
                logger.info("Paper monitor closed %d position(s)", len(closed))
    except Exception:
        logger.exception("Paper position monitor failed")

    try:
        prices = store.get_latest_prices()
        if prices:
            resolved = missed_opportunity_service.monitor_signals(prices)
            for record in resolved:
                logger.info(
                    "Missed opportunity resolved: id=%s status=%s pts=%s exit=%s @ %s",
                    record["id"],
                    record["status"],
                    record.get("points_captured"),
                    record.get("missed_exit_reason"),
                    record.get("missed_exit_price"),
                )
    except Exception:
        logger.exception("Missed opportunity monitor failed")

    logger.info(
        "Market data refresh complete at %s (%d updates, %d errors)",
        refresh_time,
        successful_updates,
        len(cycle_errors),
    )


async def refresh_live_prices() -> None:
    """Lightweight ticker poll — updates last candle close between full candle refreshes."""
    prices: dict[str, float] = {}
    for delta_symbol in settings.symbol_map.values():
        try:
            price = await asyncio.to_thread(delta_client.fetch_ticker_price, delta_symbol)
            prices[delta_symbol] = price
        except Exception as exc:
            logger.warning("Live price fetch failed for %s: %s", delta_symbol, exc)
    if prices:
        store.apply_live_prices(prices)
        try:
            missed_opportunity_service.monitor_signals(prices)
        except Exception:
            logger.exception("Missed opportunity live-price monitor failed")


async def scheduler_loop() -> None:
    """Run refresh every REFRESH_INTERVAL_SECONDS."""
    while True:
        try:
            await refresh_market_data()
        except Exception:
            logger.exception("Scheduler cycle failed — continuing")
        await asyncio.sleep(settings.refresh_interval_seconds)


async def live_price_loop() -> None:
    """Poll Delta tickers every few seconds for live price on the chart."""
    while True:
        try:
            await refresh_live_prices()
        except Exception:
            logger.exception("Live price cycle failed — continuing")
        await asyncio.sleep(settings.live_price_refresh_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log_path = setup_logging()
    logger.info("Delta Signal Engine starting up — log file %s", log_path)
    init_db()
    initialize_signal_timeframe()
    if email_service.is_configured():
        logger.info("Email alerts enabled → %s", settings.alert_email_to)
    else:
        logger.warning(
            "Email alerts not configured — set SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, "
            "SMTP_PASSWORD, ALERT_EMAIL_TO in .env"
        )
    if telegram_service.is_configured():
        logger.info("Telegram alerts enabled → chat_id %s", telegram_service.chat_id)
    else:
        logger.warning(
            "Telegram alerts not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env"
        )
    if pushover_service.is_configured():
        logger.info("Pushover alerts enabled")
    elif pushover_service.enabled:
        logger.warning(
            "Pushover enabled but not configured — set PUSHOVER_USER_KEY and PUSHOVER_APP_TOKEN"
        )
    refresh_task = asyncio.create_task(scheduler_loop())
    live_price_task = asyncio.create_task(live_price_loop())
    try:
        yield
    finally:
        refresh_task.cancel()
        live_price_task.cancel()
        for task in (refresh_task, live_price_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        logger.info("Delta Signal Engine shut down")


app = FastAPI(
    title="Delta Signal Engine",
    description=(
        "Live Delta Exchange perpetual futures signals for BTC, ETH, and SOL "
        "using SMA84, HH50, and LL50 indicators."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(market_router)
app.include_router(approval_router)
app.include_router(paper_router)
app.include_router(settings_router)
app.include_router(telegram_router)
app.include_router(pushover_router)
app.include_router(admin_router)
app.include_router(risk_router)
app.include_router(validation_router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def terminal_home() -> FileResponse:
    return FileResponse(STATIC_DIR / "terminal.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_redirect() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=302)


@app.get("/chart", include_in_schema=False)
def chart_redirect() -> RedirectResponse:
    return RedirectResponse(url="/", status_code=302)


@app.get("/history", include_in_schema=False)
def history_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "history.html")


@app.get("/history/trades", include_in_schema=False)
def trades_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "trades.html")


@app.get("/stats", include_in_schema=False)
def stats_page() -> RedirectResponse:
    return RedirectResponse(url="/performance", status_code=302)


@app.get("/performance", include_in_schema=False)
def performance_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "performance.html")


@app.get("/signals", include_in_schema=False)
def signals_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "signals.html")


@app.get("/positions", include_in_schema=False)
def positions_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "positions.html")


@app.get("/debug/signals", include_in_schema=False)
def debug_signals_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "debug-signals.html")


@app.get("/settings", include_in_schema=False)
def settings_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "settings.html")


@app.get("/risk", include_in_schema=False)
def risk_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "risk.html")


@app.get("/validation", include_in_schema=False)
def validation_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "validation.html")


@app.get("/health/page", include_in_schema=False)
def health_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "health.html")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> FileResponse | JSONResponse:
    if exc.status_code != 404:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    accept = request.headers.get("accept", "")
    path = request.url.path
    if path.startswith(("/docs", "/openapi.json", "/redoc")):
        return JSONResponse({"detail": exc.detail}, status_code=404)
    if "text/html" in accept and not path.startswith("/static"):
        return FileResponse(STATIC_DIR / "404.html", status_code=404)
    return JSONResponse({"detail": exc.detail}, status_code=404)
