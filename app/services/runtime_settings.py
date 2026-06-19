"""Runtime settings shared between API and background scheduler."""

from __future__ import annotations

import logging
import os
from threading import Lock

from app.config import DEFAULT_SIGNAL_TIMEFRAME, settings
from app.repositories.app_settings_repository import AppSettingsRepository

logger = logging.getLogger(__name__)

SIGNAL_TIMEFRAME_KEY = "signal_timeframe"

_lock = Lock()
_repository = AppSettingsRepository()


def _env_signal_timeframe() -> str:
    tf = settings.default_signal_timeframe
    if tf not in settings.timeframes:
        return DEFAULT_SIGNAL_TIMEFRAME
    return tf


def initialize_signal_timeframe() -> str:
    """Load Signal TF from .env (SIGNAL_TIMEFRAME) or seed default 5m."""
    env_tf = _env_signal_timeframe()
    with _lock:
        if os.environ.get("SIGNAL_TIMEFRAME") is not None:
            _repository.set(SIGNAL_TIMEFRAME_KEY, env_tf)
            logger.info("Signal timeframe loaded: %s (from .env)", env_tf)
            return env_tf
        stored = _repository.get(SIGNAL_TIMEFRAME_KEY)
        if stored is None:
            _repository.set(SIGNAL_TIMEFRAME_KEY, env_tf)
            logger.info("Signal timeframe loaded: %s (default)", env_tf)
            return env_tf
    tf = get_signal_timeframe()
    logger.info("Signal timeframe loaded: %s", tf)
    return tf


def get_signal_timeframe() -> str:
    """Active signal generation timeframe — DB override, else SIGNAL_TIMEFRAME env (default 5m)."""
    with _lock:
        stored = _repository.get(SIGNAL_TIMEFRAME_KEY)
        if stored and stored in settings.timeframes:
            return stored
        return _env_signal_timeframe()


def set_signal_timeframe(timeframe: str) -> str:
    """Explicit user change (terminal Signal TF selector)."""
    tf = str(timeframe).strip()
    if tf not in settings.timeframes:
        raise ValueError(
            f"Invalid signal timeframe '{tf}'. Supported: {', '.join(settings.timeframes)}"
        )
    with _lock:
        _repository.set(SIGNAL_TIMEFRAME_KEY, tf)
    logger.info("Signal timeframe changed to: %s", tf)
    return tf
