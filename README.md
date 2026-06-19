# Delta Signal Engine

A local Python application that connects to the [Delta Exchange](https://www.delta.exchange/) public API, fetches live perpetual futures candle data for **BTC**, **ETH**, and **SOL**, calculates trading indicators, generates BUY/SELL signals, and exposes results through a FastAPI backend.

## Features

- **Market Data**: Fetches OHLCV candles from Delta Exchange for BTCUSDT, ETHUSDT, and SOLUSDT perpetual futures
- **Timeframes**: 1m, 5m, 15m
- **Indicators**: SMA84, HH50 (highest high of previous 50 completed candles), LL50 (lowest low of previous 50 completed candles)
- **Signals**:
  - **BUY**: close crosses above HH50 AND close > SMA84
  - **SELL**: close crosses below LL50 AND close < SMA84
- **Background refresh**: Every 60 seconds — fetch candles, recalculate indicators, generate signals
- **In-memory cache**: Latest 500 candles per symbol/timeframe

## Requirements

- Python 3.11+
- Internet access to reach `https://api.delta.exchange`

## Setup

```bash
cd delta-signal-engine
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Run Locally

```bash
uvicorn app.main:app --reload
```

The server starts at [http://localhost:8000](http://localhost:8000).

- **Dashboard**: [http://localhost:8000/](http://localhost:8000/) — live charts, indicators, and signals
- **API docs**: [http://localhost:8000/docs](http://localhost:8000/docs)

On startup, a background task immediately fetches live data from Delta Exchange, then refreshes every 60 seconds.

## Dashboard

Open [http://localhost:8000/](http://localhost:8000/) for a live web UI that shows:

- Price chart with Close, SMA84, HH50, and LL50
- Latest BUY/SELL signals from the current session
- Engine status and last refresh time
- Symbol/timeframe selectors (BTC, ETH, SOL · 1m, 5m, 15m)

The dashboard auto-refreshes every 30 seconds.

## API Endpoints

### GET /health

Health check.

**Example response:**

```json
{
  "status": "ok",
  "last_refresh": "2026-06-16T10:55:00.123456+00:00"
}
```

### GET /signals

Returns signals generated during the current session (newest first).

**Example response:**

```json
{
  "signals": [
    {
      "symbol": "ETHUSDT",
      "signal": "BUY",
      "price": 1800.25,
      "timeframe": "5m",
      "timestamp": "2026-06-16T10:50:00+00:00"
    }
  ],
  "count": 1
}
```

### GET /chart/{symbol}

Returns latest candles and indicator series for a symbol.

- `{symbol}` accepts short names (`BTC`, `ETH`, `SOL`) or full symbols (`BTCUSDT`, etc.)
- Optional query param: `timeframe` (default: `5m`)

**Example:** `GET /chart/ETH?timeframe=5m`

**Example response:**

```json
{
  "symbol": "ETHUSDT",
  "timeframe": "5m",
  "candles": [
    {
      "time": 1781605500,
      "open": 1795.0,
      "high": 1798.25,
      "low": 1795.0,
      "close": 1798.25,
      "volume": 222.0
    }
  ],
  "sma84": [null, null, 1796.5],
  "hh50": [null, null, 1802.0],
  "ll50": [null, null, 1788.0]
}
```

Indicator arrays align with the `candles` array. Leading `null` values indicate insufficient history for that indicator at that index.

### GET /status

Returns monitored symbols, timeframes, and refresh settings.

**Example response:**

```json
{
  "symbols": ["BTC", "ETH", "SOL"],
  "timeframes": ["1m", "5m", "15m"],
  "delta_symbols": {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT"
  },
  "refresh_interval_seconds": 60,
  "candle_limit": 500,
  "last_refresh": "2026-06-16T10:55:00.123456+00:00"
}
```

## Signal Logic

### HH50 / LL50 (completed candles only)

For the current (latest) candle, indicators use the **previous 50 completed candles** — never the current candle:

```
HH50 = highest high from candles[-51:-1]
LL50 = lowest low from candles[-51:-1]
```

### BUY Signal

```
previous_close <= previous_HH50
AND current_close > current_HH50
AND current_close > SMA84
```

### SELL Signal

```
previous_close >= previous_LL50
AND current_close < current_LL50
AND current_close < SMA84
```

## Project Structure

```
delta-signal-engine/
├── app/
│   ├── main.py          # FastAPI app + background scheduler
│   ├── config.py        # Settings and symbol mapping
│   ├── market_data.py   # Delta API client + in-memory store
│   ├── indicators.py    # SMA84, HH50, LL50 calculations
│   ├── signals.py       # BUY/SELL signal detection
│   ├── api.py           # REST endpoints
│   └── models.py        # Pydantic response models
├── tests/
│   ├── test_indicators.py
│   ├── test_signals.py
│   └── test_api.py
├── requirements.txt
└── README.md
```

## Run Tests

```bash
pytest -v
```

## Logging

The application logs:

- New BUY/SELL signals
- Delta Exchange API failures
- Indicator calculation summaries
- Background refresh cycle start/completion

## Notes

- This is **Phase 1** only: no authentication, trade execution, database, or WebSockets
- Data comes from Delta Exchange Global public API (`https://api.delta.exchange/v2`)
- Signals appear in `/signals` only when a crossover condition is met during a refresh cycle
