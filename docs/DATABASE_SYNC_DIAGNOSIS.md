# Database policy — VPS is canonical

## Rule

**Only the VPS database is production truth.** The VPS engine runs 24/7 at:

```
/root/delta-signal-engine/data/signals.db
```

Localhost must **not** be treated as a second production instance.

## Why localhost differed

| Localhost (old) | VPS (production) |
|-----------------|------------------|
| 31 signals | 42 signals |
| 10 trades | 6 trades |
| Balance $786.55 | Balance $1,092.69 |
| Latest signal 2026-06-19 | Latest signal 2026-06-22 |

Same git commit (`bf5daa6`), different SQLite files.

## Local workflow (audits & debugging)

### 1. Stop local engine (do not write to a separate DB)

Do not run `uvicorn` on Windows while VPS is live unless you use a **dev-only** database:

```env
# Optional: separate dev DB so you never fork production data
DATABASE_PATH=data/signals.dev.db
```

### 2. Pull VPS database before any audit

**Windows (PowerShell):**

```powershell
cd C:\Users\LENOVO\delta-signal-engine
.\scripts\sync_production_database.ps1
```

**Linux / macOS:**

```bash
./scripts/sync_production_database.sh
```

Requires SSH to VPS (`ssh root@vmi3381775`). Set in `.env` if needed:

```env
VPS_HOST=vmi3381775
VPS_USER=root
VPS_DATABASE_PATH=/root/delta-signal-engine/data/signals.db
```

### 3. Verify parity

```powershell
curl http://localhost:8000/api/debug/system
```

Expected after sync (match your VPS):

| Field | VPS value |
|-------|-----------|
| signal_count | 42 |
| trade_count | 6 |
| approved_count | 6 |
| balance | 1092.69 |
| latest_signal_time | 2026-06-22T16:35:00+00:00 |

Or open **http://localhost:8000/debug/system** and paste VPS JSON — Compare should show `"identical": true`.

## Production (VPS only)

- Keep **one** writer: VPS uvicorn/systemd service
- Deploy code with `git pull` on VPS — **never** copy `signals.db` from local to VPS
- Backups: copy VPS `data/signals.db` periodically on the server

```bash
# On VPS
cp /root/delta-signal-engine/data/signals.db \
   /root/delta-signal-engine/data/signals.db.backup-$(date -u +%Y%m%d)
```

## Summary

| Action | Where |
|--------|--------|
| Live trading / signals | VPS only |
| Audits | Pull VPS DB → local, then audit |
| Code changes | Git → deploy to VPS |
| Never | Run two engines on two DBs expecting same numbers |
