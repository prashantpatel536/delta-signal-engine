# Delta Exchange Audit — Round 2

## 1. Contract Specifications (Live API Verification)

**All verified:** True  
**Source:** https://api.delta.exchange/v2/products

### BTCUSDT
- **Contract size (contract_value):** 0.001 BTC
- **Lot size:** 1 contract (minimum order increment)
- **Tick size:** 0.5
- **Quantity formula:** `quantity = contracts × contract_value`
- **Margin formula:** `initial_margin = position_notional / leverage = (contracts × contract_value × mark_price) / leverage`
- **PnL (long):** `PnL (long) = contracts × contract_value × (exit_price − entry_price)`
- **Portal match:** True (configured=0.001)
- **State:** live

### ETHUSDT
- **Contract size (contract_value):** 0.01 ETH
- **Lot size:** 1 contract (minimum order increment)
- **Tick size:** 0.05
- **Quantity formula:** `quantity = contracts × contract_value`
- **Margin formula:** `initial_margin = position_notional / leverage = (contracts × contract_value × mark_price) / leverage`
- **PnL (long):** `PnL (long) = contracts × contract_value × (exit_price − entry_price)`
- **Portal match:** True (configured=0.01)
- **State:** live

### SOLUSDT
- **Contract size (contract_value):** 1.0 SOL
- **Lot size:** 1 contract (minimum order increment)
- **Tick size:** 0.0001
- **Quantity formula:** `quantity = contracts × contract_value`
- **Margin formula:** `initial_margin = position_notional / leverage = (contracts × contract_value × mark_price) / leverage`
- **PnL (long):** `PnL (long) = contracts × contract_value × (exit_price − entry_price)`
- **Portal match:** True (configured=1.0)
- **State:** live

## 2. Trade Replay Validation (Last 20 Trades)

Verified: 10/10 — All pass: True

| ID | Symbol | Entry | Exit | Qty | Margin | PnL | ROE | Impact | Manual | OK |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | ETHUSDT | 1684.35 | 1699.75 | 5.23 | 352.37 | 80.54 | 22.86% | 10.44% | 80.54 | ✓ |
| 9 | BTCUSDT | 62769.5 | 62343.0 | 0.153 | 384.15 | -65.25 | -16.99% | -8.46% | -65.25 | ✓ |
| 8 | BTCUSDT | 62592.5 | 62592.5 | 0.154 | 385.57 | 0.0 | 0.0% | 0.0% | 0.0 | ✓ |
| 7 | SOLUSDT | 68.96 | 68.55 | 150.0 | 413.76 | -61.5 | -14.86% | -7.39% | -61.5 | ✓ |
| 6 | ETHUSDT | 1750.0 | 1747.5 | 6.05 | 423.5 | -15.12 | -3.57% | -1.78% | -15.12 | ✓ |
| 4 | BTCUSDT | 64320.5 | 64012.0 | 0.175 | 450.24 | -53.99 | -11.99% | -5.51% | -53.99 | ✓ |
| 3 | ETHUSDT | 1751.45 | 1740.2 | 6.99 | 489.71 | -78.64 | -16.06% | -8.02% | -78.64 | ✓ |
| 5 | SOLUSDT | 71.8 | 71.8 | 170.0 | 488.24 | 0.0 | 0.0% | 0.0% | 0.0 | ✓ |
| 1 | ETHUSDT | 1726.0 | 1726.0 | 7.1 | 490.18 | 0.0 | 0.0% | 0.0% | 0.0 | ✓ |
| 2 | ETHUSDT | 1731.0 | 1728.3 | 7.22 | 499.91 | -19.49 | -3.9% | -1.95% | -19.49 | ✓ |

## 3. Net Missed Profit by Symbol

**Similar values detected:** False
**Current spread (USD):** 469.06
**Diagnosis:** If BTC/ETH/SOL net missed $ are within ~5% of each other (e.g. $846/$807/$835), that indicates the old bug: all symbols sized from current account balance instead of balance-at-signal-time. After fix, values diverge by symbol mix and entry price.

### BTC
- Total Winning Signals: 1
- Total Losing Signals: 4
- Gross Profit $: 46.11
- Gross Loss $: -136.41
- Net $ (stored): -90.3
- Net $ (recomputed): -90.3
- Stored matches recomputed: True

### ETH
- Total Winning Signals: 1
- Total Losing Signals: 3
- Gross Profit $: 90.56
- Gross Loss $: -123.26
- Net $ (stored): -32.7
- Net $ (recomputed): -32.7
- Stored matches recomputed: True

### SOL
- Total Winning Signals: 0
- Total Losing Signals: 6
- Gross Profit $: 0.0
- Gross Loss $: -501.76
- Net $ (stored): -501.76
- Net $ (recomputed): -501.76
- Stored matches recomputed: True

## 4. Strategy Reality Check

- **ending_capital:** 786.55
- **net_profit_usd:** -213.45
- **strategy_return_pct:** -21.35
- **cagr_equivalent_pct:** -21.35
- **cagr_note:** Sample period 4.0 days — CAGR equivalent uses simple return (annualized CAGR requires >=30 days of data)
- **expected_monthly_return_pct:** -21.35
- **maximum_drawdown_usd:** 293.99
- **maximum_drawdown_pct:** 29.4
- **sharpe_like_score:** -1.19
- **period_days:** 4.0

## 5. Portfolio Simulator (API — UI deferred)

Starting capital: $1000.0
### approved_trades_only
- Ending: $786.55 | Return: -21.35%
- Max DD: 29.4% | Sharpe-like: -1.19
- Trades/signals: 10

### all_generated_signals
- Ending: $360.17 | Return: -63.98%
- Max DD: 66.17% | Sharpe-like: -2.91
- Trades/signals: 24

### missed_winners_only
- Ending: $1163.65 | Return: 16.37%
- Max DD: 0.0% | Sharpe-like: 5.82
- Trades/signals: 2
