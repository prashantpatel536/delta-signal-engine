# Delta Exchange Calculation Audit Report

## 1. Formulas Used

- **margin_budget**: `margin_budget = balance × (margin_percent / 100)`
- **target_notional**: `target_notional = margin_budget × leverage`
- **contracts**: `contracts = floor(target_notional / (contract_size × entry_price))`
- **quantity**: `quantity = contracts × contract_size`
- **position_value**: `position_value = quantity × entry_price`
- **margin_used**: `margin_used = position_value / leverage`
- **pnl_long**: `PnL (BUY) = (exit_price − entry_price) × quantity`
- **pnl_short**: `PnL (SELL) = (entry_price − exit_price) × quantity`
- **roe**: `ROE % = (PnL / margin_used) × 100`
- **account_impact**: `Account Impact % = (PnL / balance) × 100`
- **missed_profit**: `Missed Profit $ = max(PnL, 0) when signal was not traded`
- **missed_loss**: `Missed Loss $ = abs(min(PnL, 0)) when signal was not traded`

## 2. Delta Contract Specifications

- **BTCUSDT**: contract_size=0.001, SL range=300.0–700.0 pts
- **ETHUSDT**: contract_size=0.01, SL range=15.0–45.0 pts
- **SOLUSDT**: contract_size=1.0, SL range=0.8–3.0 pts

## 3. Sample Calculations

### BTCUSDT
- Entry: 100000.0, Exit: 100505.0, Side: BUY
- Balance: $1000.0
- Contracts: 125.0 × 0.001
- Quantity: 0.125
- Margin Used: $500.0
- PnL: $63.12
- ROE: 12.62%
- Account Impact: 6.31%

### ETHUSDT
- Entry: 3500.0, Exit: 3566.0, Side: BUY
- Balance: $1000.0
- Contracts: 357.0 × 0.01
- Quantity: 3.57
- Margin Used: $499.8
- PnL: $235.62
- ROE: 47.14%
- Account Impact: 23.56%

### SOLUSDT
- Entry: 150.0, Exit: 153.0, Side: BUY
- Balance: $1000.0
- Contracts: 83.0 × 1.0
- Quantity: 83.0
- Margin Used: $498.0
- PnL: $249.0
- ROE: 50.0%
- Account Impact: 24.9%

## 4. Trade Validation (Expected vs Actual PnL)

Total: 10, Passed (<1% diff): 10, Failed: 0

| Trade ID | Symbol | Entry | Exit | Qty | Margin | Expected | Actual | Diff % | OK |
|---|---|---|---|---|---|---|---|---|---|
| 2 | ETHUSDT | 1731.0 | 1728.3 | 7.22 | 499.91 | -19.49 | -19.49 | 0.0 | ✓ |
| 1 | ETHUSDT | 1726.0 | 1726.0 | 7.1 | 490.18 | 0.0 | 0.0 | 0.0 | ✓ |
| 5 | SOLUSDT | 71.8 | 71.8 | 170.0 | 488.24 | 0.0 | 0.0 | 0.0 | ✓ |
| 3 | ETHUSDT | 1751.45 | 1740.2 | 6.99 | 489.71 | -78.64 | -78.64 | 0.0 | ✓ |
| 4 | BTCUSDT | 64320.5 | 64012.0 | 0.175 | 450.24 | -53.99 | -53.99 | 0.0 | ✓ |
| 6 | ETHUSDT | 1750.0 | 1747.5 | 6.05 | 423.5 | -15.12 | -15.12 | 0.0 | ✓ |
| 7 | SOLUSDT | 68.96 | 68.55 | 150.0 | 413.76 | -61.5 | -61.5 | 0.0 | ✓ |
| 8 | BTCUSDT | 62592.5 | 62592.5 | 0.154 | 385.57 | 0.0 | 0.0 | 0.0 | ✓ |
| 9 | BTCUSDT | 62769.5 | 62343.0 | 0.153 | 384.15 | -65.25 | -65.25 | 0.0 | ✓ |
| 10 | ETHUSDT | 1684.35 | 1699.75 | 5.23 | 352.37 | 80.54 | 80.54 | 0.0 | ✓ |

## 5. Strategy Account Simulation

- Starting Capital: $1000.0
- Ending Capital: $786.55
- Net Profit: $-213.45
- Total Return: -21.34%
- Total Trades: 10 (W: 1, L: 9)

## 6. Missed Opportunity Simulation

- Starting Capital: $1000.0
- Ending Capital: $360.17
- Missed Strategy Growth: $-639.83
- Total Missed Return: -63.98%
- Signals Simulated: 24

## 7. Proof Portal Matches Delta Exchange

{
  "trade_validation_pass_rate_pct": 100.0,
  "all_trades_within_1pct": true,
  "strategy_simulation_matches_recalc": true,
  "sample_btc_pnl_per_505pts": 63.12,
  "sample_eth_pnl_per_66pts": 235.62,
  "note": "PnL scales with quantity (contracts \u00d7 contract_size), not uniformly across symbols. Missed $ now uses balance at signal time, not current account balance."
}