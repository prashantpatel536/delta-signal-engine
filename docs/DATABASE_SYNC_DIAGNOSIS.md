# Database Sync Diagnosis — Localhost vs VPS

## Root cause

**Localhost and VPS use completely separate SQLite databases.**

| Factor | Localhost | VPS |
|--------|-----------|-----|
| Default DB path | `{project}/data/signals.db` | `{project}/data/signals.db` |
| Git tracking | **No** — `data/*.db` is in `.gitignore` | **No** |
| Shared on deploy | **No** — `git pull` only updates code | **No** |
| Signal engine | Writes signals/trades locally | Writes signals/trades locally |

Each environment accumulates its own:
- Signals (different counts, IDs, statuses)
- Paper trades and PnL (`paper_account.balance`)
- Missed opportunity resolutions
- Approved / missed winner / missed loser totals

This is **not a calculation bug** — it is **two independent databases**.

## How to verify

### 1. Check this host

```bash
curl http://localhost:8000/api/debug/system
```

Or open: **http://localhost:8000/debug/system**

### 2. Check VPS

```bash
curl http://YOUR_VPS_IP:8000/api/debug/system
```

### 3. Compare

On the diagnostic page (`/debug/system`), paste VPS `/api/debug/system/full` JSON and click **Compare**.

Or via API:

```bash
curl -X POST http://localhost:8000/api/debug/system/compare \
  -H "Content-Type: application/json" \
  -d @vps_full.json
```

## Expected differences (current localhost snapshot)

When databases are separate, these fields **will differ**:

- `database_path` (different absolute paths)
- `database_size`
- `signal_count`, `trade_count`, `approved_count`
- `latest_signal_time`, `latest_trade_time`
- `table_row_counts.signals`, `table_row_counts.positions`
- `paper_account.balance`, `paper_account.realized_pnl`

`git_commit` may also differ if VPS has not pulled latest code.

## Fix options (choose one)

### Option A — VPS is source of truth (recommended for production)

1. Stop localhost engine (avoid dual writes).
2. Copy VPS database to local for inspection only:
   ```bash
   scp user@vps:/path/to/delta-signal-engine/data/signals.db ./data/signals.db
   ```
3. Run localhost against copied file (read-only testing).

### Option B — Shared database path

Set the same `DATABASE_PATH` on both hosts pointing to a **shared volume** (NFS, mounted block storage). Only one writer should run at a time.

```env
DATABASE_PATH=/mnt/shared/delta/signals.db
```

### Option C — Single production instance

Run the engine **only on VPS**. Use localhost for code development with a fresh/test DB, never expecting parity.

## Localhost reference (at time of audit)

Run `GET /api/debug/system` locally to get current values. Example structure:

```json
{
  "git_commit": "...",
  "database_path": "C:\\Users\\LENOVO\\delta-signal-engine\\data\\signals.db",
  "database_size": 77824,
  "signal_count": 31,
  "trade_count": 10,
  "approved_count": 10,
  "latest_signal_time": "...",
  "latest_trade_time": "..."
}
```

Until VPS JSON is pasted into the compare tool, **parity cannot be confirmed** — but separate `data/signals.db` files on each host is sufficient explanation for all metric divergence.
