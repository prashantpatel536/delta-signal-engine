"""Pydantic models for API responses."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


SignalStatus = Literal[
    "PENDING",
    "APPROVED",
    "REJECTED",
    "EXPIRED",
    "TP_HIT",
    "SL_HIT",
    "MISSED_WINNER",
    "MISSED_LOSER",
]


class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Signal(BaseModel):
    symbol: str
    signal: Literal["BUY", "SELL"]
    price: float
    timeframe: str
    timestamp: str
    candle_time: int | None = None
    status: SignalStatus | None = None
    signal_id: int | None = None


class ChartResponse(BaseModel):
    symbol: str
    timeframe: str
    candles: list[Candle]
    sma84: list[float | None] = Field(default_factory=list)
    hh50: list[float | None] = Field(default_factory=list)
    ll50: list[float | None] = Field(default_factory=list)
    signals: list[Signal] = Field(default_factory=list)
    candle_audit: dict = Field(default_factory=dict)
    candle_counts: dict = Field(default_factory=dict)
    signal_context: dict = Field(default_factory=dict)


class WatchlistItem(BaseModel):
    symbol: str
    short_symbol: str
    price: float
    change: float
    change_pct: float
    signal: Literal["BUY", "SELL"] | None = None


class WatchlistResponse(BaseModel):
    timeframe: str
    items: list[WatchlistItem] = Field(default_factory=list)


class ChartDebugResponse(BaseModel):
    symbol: str
    timeframe: str
    last_candle: Candle | None = None
    last_candle_trade: Candle | None = None
    sma84: float | None = None
    hh50: float | None = None
    ll50: float | None = None
    candle_count: int = 0
    expected_interval_seconds: int = 0
    candle_audit: dict = Field(default_factory=dict)
    indicator_source: str = "trade_candles"


class DebugRawResponse(BaseModel):
    symbol: str
    timeframe: str
    raw_candle_count: int
    processed_candle_count: int
    first_candle: Candle | None = None
    last_candle: Candle | None = None
    pipeline: dict = Field(default_factory=dict)


class StatusResponse(BaseModel):
    symbols: list[str]
    timeframes: list[str]
    delta_symbols: dict[str, str]
    refresh_interval_seconds: int
    candle_limit: int
    last_refresh: str | None = None


class SubsystemHealth(BaseModel):
    status: Literal["healthy", "degraded", "fail"]
    detail: str | None = None


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "fail"]
    last_refresh: str | None = None
    last_error: str | None = None
    cache_ready: bool = False
    cached_pairs: int = 0
    total_pairs: int = 0
    refresh_interval_seconds: int = 60
    market_data: SubsystemHealth
    database: SubsystemHealth
    signal_engine: SubsystemHealth
    paper_trading: SubsystemHealth
    notifications: SubsystemHealth


class SignalsResponse(BaseModel):
    signals: list[Signal]
    count: int


class RiskSettingsResponse(BaseModel):
    leverage: float
    margin_percent: float
    default_leverage: float
    default_margin_percent: float


class RiskMatrixRow(BaseModel):
    symbol: str
    current_price: float
    balance: float
    margin_percent: float
    leverage: float
    risk_10pct_distance: float = 0.0
    risk_20pct_distance: float = 0.0
    risk_30pct_distance: float = 0.0
    reward_25pct_distance: float = 0.0
    reward_50pct_distance: float = 0.0
    reward_100pct_distance: float = 0.0


class RiskMatrixResponse(BaseModel):
    balance: float
    leverage: float
    margin_percent: float
    rows: list[RiskMatrixRow] = Field(default_factory=list)


class StoredSignal(BaseModel):
    id: int
    symbol: str
    timeframe: str
    signal_timeframe: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    status: SignalStatus
    created_at: str
    updated_at: str
    max_favorable_excursion: float = 0.0
    max_adverse_excursion: float = 0.0
    points_captured: float | None = None
    missed_monitoring: bool = False
    monitoring_started_at: str | None = None
    missed_resolved_at: str | None = None
    missed_exit_reason: str | None = None
    missed_exit_price: float | None = None
    missed_pnl_usd: float | None = None
    missed_roe_pct: float | None = None
    missed_account_impact_pct: float | None = None
    risk_profile: dict[str, Any] | None = None

    @classmethod
    def from_record(cls, record: dict) -> "StoredSignal":
        import json

        row = dict(record)
        row.setdefault("signal_timeframe", row.get("timeframe", ""))
        row["missed_monitoring"] = bool(row.get("missed_monitoring"))
        raw_risk = row.get("risk_profile")
        if isinstance(raw_risk, str) and raw_risk.strip():
            try:
                row["risk_profile"] = json.loads(raw_risk)
            except json.JSONDecodeError:
                row["risk_profile"] = None
        for field in (
            "max_favorable_excursion",
            "max_adverse_excursion",
            "points_captured",
            "missed_exit_price",
            "missed_pnl_usd",
            "missed_roe_pct",
            "missed_account_impact_pct",
        ):
            if row.get(field) is not None:
                row[field] = float(row[field])
        return cls(**row)


class StoredSignalsResponse(BaseModel):
    signals: list[StoredSignal]
    count: int


class ApproveTradeRequest(BaseModel):
    leverage: float | None = Field(default=None, ge=1)
    margin_percent: float | None = Field(default=None, ge=1, le=100)
    stop_loss: float | None = None
    take_profit: float | None = None


class ApproveTradeResponse(BaseModel):
    signal: StoredSignal
    position: "Position"


class SignalDiagnosticsResponse(BaseModel):
    symbol: str | None = None
    timeframe: str | None = None
    latest_stored_signal: StoredSignal | None = None
    runtime_signal: Signal | None = None
    signal_time: str | None = None
    sma84: float | None = None
    hh50: float | None = None
    ll50: float | None = None
    last_candle_time: int | None = None
    candle_count: int = 0
    duplicate_pending_blocked: bool = False
    indicator_source: str = "trade_candles"


class MissedOpportunitySymbolNet(BaseModel):
    symbol: str
    label: str
    missed_winners: int = 0
    missed_losers: int = 0
    net_missed_profit: float = 0.0
    net_missed_pnl_usd: float = 0.0


class SignalStatistics(BaseModel):
    total: int
    pending: int
    approved: int
    rejected: int
    expired: int
    missed_opportunities: int = 0
    missed_winners: int = 0
    missed_losers: int = 0
    gross_missed_profit: float = 0.0
    gross_missed_loss: float = 0.0
    net_missed_profit: float = 0.0
    gross_missed_pnl_usd: float = 0.0
    gross_missed_loss_usd: float = 0.0
    net_missed_pnl_usd: float = 0.0
    net_missed_roe_pct: float = 0.0
    monitoring: int = 0
    by_symbol: list[MissedOpportunitySymbolNet] = Field(default_factory=list)


class MissedOpportunitySummary(BaseModel):
    missed_opportunities: int
    missed_winners: int
    missed_losers: int
    gross_missed_profit: float
    gross_missed_loss: float
    net_missed_profit: float
    gross_missed_pnl_usd: float = 0.0
    gross_missed_loss_usd: float = 0.0
    net_missed_pnl_usd: float = 0.0
    net_missed_roe_pct: float = 0.0
    monitoring: int
    totals_valid: bool = True
    by_symbol: list[MissedOpportunitySymbolNet] = Field(default_factory=list)


class MissedOpportunityAuditItem(BaseModel):
    signal_id: int
    symbol: str
    outcome: str
    points_missed: float | None = None
    exit_reason: str | None = None
    exit_price: float | None = None


class MissedOpportunityDebugResponse(BaseModel):
    total_missed: int
    total_winners: int
    total_losers: int
    totals_consistent: bool
    duplicate_outcome_count: int
    monitoring_active: int
    gross_missed_profit: float
    gross_missed_loss: float
    net_missed_profit: float
    signals: list[MissedOpportunityAuditItem]


class RecalculateMissedResponse(BaseModel):
    ok: bool
    recalculated: int
    changed: int
    unchanged: int
    summary: MissedOpportunitySummary


class MissedOpportunityAnalytics(BaseModel):
    period: str
    since: str
    signals_generated: int
    signals_approved: int
    missed_opportunities: int
    missed_winners: int
    missed_losers: int
    gross_missed_profit: float
    gross_missed_loss: float
    net_missed_profit: float
    gross_missed_pnl_usd: float = 0.0
    gross_missed_loss_usd: float = 0.0
    net_missed_pnl_usd: float = 0.0
    totals_valid: bool = True


PositionStatus = Literal["OPEN", "CLOSED"]


class PaperStatistics(BaseModel):
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    net_pnl: float
    average_win: float
    average_loss: float
    profit_factor: float | None = None
    open_positions: int = 0


class EquityCurvePoint(BaseModel):
    date: str
    equity: float
    daily_pnl: float = 0.0


class PerformanceAnalytics(BaseModel):
    starting_balance: float
    current_balance: float
    net_pnl: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    profit_factor: float | None = None
    max_drawdown_usd: float
    max_drawdown_pct: float
    average_trade_duration_seconds: float
    average_trade_duration: str
    open_positions: int = 0
    edge_status: str
    edge_label: str
    edge_summary: str
    daily_equity_curve: list[EquityCurvePoint]


class PaperAccount(BaseModel):
    starting_balance: float
    balance: float
    total_balance: float
    available_margin: float
    used_margin: float
    unrealized_pnl: float
    realized_pnl: float


class OpenPaperTradeRequest(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    entry: float
    margin_percent: float = Field(ge=1, le=100)
    leverage: float = Field(ge=1)
    stop_loss: float
    take_profit: float
    signal_id: int | None = None


class PaperTradePreview(BaseModel):
    margin_used: float
    position_value: float
    quantity: float
    available_margin: float
    sufficient_margin: bool
    risk_usd: float
    reward_usd: float
    risk_reward: float


class Position(BaseModel):
    id: int
    signal_id: int | None = None
    symbol: str
    side: Literal["BUY", "SELL"]
    entry: float
    stop_loss: float
    take_profit: float
    original_stop_loss: float | None = None
    original_take_profit: float | None = None
    risk_reward: float = 0.0
    quantity: float = 1.0
    leverage: float = 1.0
    margin_used: float = 0.0
    position_value: float = 0.0
    status: PositionStatus
    opened_at: str
    closed_at: str | None = None
    exit_price: float | None = None
    exit_reason: Literal["TP", "SL", "MANUAL"] | None = None
    pnl: float | None = None
    price_points: float | None = None
    account_impact_pct: float | None = None
    roe: float | None = None


class UpdatePositionLevelsRequest(BaseModel):
    stop_loss: float | None = None
    take_profit: float | None = None


class PositionEvent(BaseModel):
    id: int
    position_id: int
    event_type: str
    field_name: str | None = None
    old_value: float | None = None
    new_value: float | None = None
    message: str | None = None
    created_at: str


class PositionEventsResponse(BaseModel):
    events: list[PositionEvent]
    count: int


class OpenPosition(Position):
    current_price: float | None = None
    unrealized_pnl: float | None = None
    roe: float | None = None


class OpenPositionsResponse(BaseModel):
    positions: list[OpenPosition]
    count: int


class ClosedTrade(Position):
    result: str
    duration_seconds: float
    duration: str
    exit_status: str | None = None


class ClosedTradesResponse(BaseModel):
    trades: list[ClosedTrade]
    count: int


class PushoverStatusResponse(BaseModel):
    configured: bool
    enabled: bool
    user_key_set: bool
    app_token_set: bool
    user_key_valid: bool = False
    app_token_valid: bool = False
    config_hint: str | None = None


class PushoverTestResponse(BaseModel):
    ok: bool
    message: str


class TelegramStatusResponse(BaseModel):
    configured: bool
    chat_id_set: bool
    bot_token_set: bool
    bot_token_valid: bool = False
    proxy_set: bool = False
    last_error: str | None = None
    config_hint: str | None = None


class TelegramTestResponse(BaseModel):
    ok: bool
    message: str


class EmailStatusResponse(BaseModel):
    configured: bool
    smtp_server_set: bool
    smtp_port_set: bool
    smtp_username_set: bool
    smtp_password_set: bool
    alert_email_to_set: bool


class EmailTestResponse(BaseModel):
    ok: bool
    message: str


class SignalTimeframeResponse(BaseModel):
    signal_timeframe: str


class SignalTimeframeUpdate(BaseModel):
    signal_timeframe: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
