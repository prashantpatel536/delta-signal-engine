"""Application configuration."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
DELTA_API_BASE_URL = "https://api.delta.exchange/v2"
CANDLE_LIMIT = 500
REFRESH_INTERVAL_SECONDS = 60
LIVE_PRICE_REFRESH_SECONDS = 10
PENDING_SIGNAL_EXPIRY_MINUTES = 15
MISSED_OPPORTUNITY_MONITOR_HOURS = int(os.getenv("MISSED_OPPORTUNITY_MONITOR_HOURS", "24") or "24")
DEFAULT_SIGNAL_TIMEFRAME = "5m"
DEFAULT_LEVERAGE = 25
DEFAULT_MARGIN_PERCENT = 50
TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d")
MARK_CANDLE_PREFIX = "MARK:"


def _resolve_database_path() -> Path:
    raw = os.getenv("DATABASE_PATH", "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path
    return PROJECT_ROOT / "data" / "signals.db"


DATABASE_PATH = _resolve_database_path()

# Short symbol (API path) -> Delta Exchange product symbol
SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}


@dataclass
class Settings:
    api_base_url: str = field(
        default_factory=lambda: os.getenv("DELTA_API_BASE_URL", DELTA_API_BASE_URL)
    )
    api_key: str | None = field(default_factory=lambda: os.getenv("DELTA_API_KEY"))
    api_secret: str | None = field(default_factory=lambda: os.getenv("DELTA_API_SECRET"))
    candle_limit: int = CANDLE_LIMIT
    refresh_interval_seconds: int = REFRESH_INTERVAL_SECONDS
    live_price_refresh_seconds: int = LIVE_PRICE_REFRESH_SECONDS
    pending_signal_expiry_minutes: int = PENDING_SIGNAL_EXPIRY_MINUTES
    default_signal_timeframe: str = field(
        default_factory=lambda: os.getenv("SIGNAL_TIMEFRAME", DEFAULT_SIGNAL_TIMEFRAME)
    )
    timeframes: tuple[str, ...] = TIMEFRAMES
    symbol_map: dict[str, str] = field(default_factory=lambda: SYMBOL_MAP.copy())
    enrich_flat_candles_with_mark: bool = field(
        default_factory=lambda: os.getenv("DELTA_ENRICH_MARK", "true").lower()
        not in ("0", "false", "no")
    )
    database_path: Path = field(default_factory=lambda: DATABASE_PATH)
    telegram_bot_token: str | None = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN")
    )
    telegram_chat_id: str | None = field(
        default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID")
    )
    telegram_proxy: str | None = field(
        default_factory=lambda: os.getenv("TELEGRAM_PROXY")
    )
    smtp_server: str | None = field(default_factory=lambda: os.getenv("SMTP_SERVER"))
    smtp_port: int | None = field(
        default_factory=lambda: int(os.getenv("SMTP_PORT", "587") or "587")
    )
    smtp_username: str | None = field(default_factory=lambda: os.getenv("SMTP_USERNAME"))
    smtp_password: str | None = field(default_factory=lambda: os.getenv("SMTP_PASSWORD"))
    alert_email_to: str | None = field(default_factory=lambda: os.getenv("ALERT_EMAIL_TO"))
    pushover_enabled: str | None = field(
        default_factory=lambda: os.getenv("PUSHOVER_ENABLED", "false")
    )
    pushover_user_key: str | None = field(
        default_factory=lambda: os.getenv("PUSHOVER_USER_KEY")
    )
    pushover_app_token: str | None = field(
        default_factory=lambda: os.getenv("PUSHOVER_APP_TOKEN")
    )
    missed_opportunity_monitor_hours: int = field(
        default_factory=lambda: MISSED_OPPORTUNITY_MONITOR_HOURS
    )
    default_leverage: float = field(
        default_factory=lambda: float(os.getenv("DEFAULT_LEVERAGE", str(DEFAULT_LEVERAGE)))
    )
    default_margin_percent: float = field(
        default_factory=lambda: float(
            os.getenv("DEFAULT_MARGIN_PERCENT", str(DEFAULT_MARGIN_PERCENT))
        )
    )


settings = Settings()
