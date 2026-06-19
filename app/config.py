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
TIMEFRAMES = ("1m", "5m", "15m", "1h")
MARK_CANDLE_PREFIX = "MARK:"
DATABASE_PATH = PROJECT_ROOT / "data" / "signals.db"

# Short symbol (API path) -> Delta Exchange product symbol
SYMBOL_MAP: dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
}

RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
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


settings = Settings()
