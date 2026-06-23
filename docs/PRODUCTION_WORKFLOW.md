# Production workflow — VPS only

## Your workflow

1. **Edit code** on your PC (Cursor / local clone)
2. **Deploy to VPS** (`git pull` or your deploy script on the server)
3. **Verify on VPS only** — balances, signals, trades, audits

Do **not** compare localhost stats to VPS. They will differ unless you explicitly sync databases (you are not doing that).

## Source of truth

| What | Where |
|------|--------|
| Live engine | VPS 24/7 |
| Database | `/root/delta-signal-engine/data/signals.db` |
| Audits & metrics | VPS URLs only |
| Git code | Same repo; deploy pulls to VPS |

## After each deploy

On VPS:

```bash
cd /root/delta-signal-engine
git pull
# restart service, e.g.:
sudo systemctl restart delta-signal-engine
# or: pkill -f uvicorn && nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
```

Verify:

```bash
curl http://127.0.0.1:8000/api/debug/system
curl http://127.0.0.1:8000/validation/full-audit
```

Or open in browser: `http://YOUR_VPS_IP:8000/debug/system`

## Local machine (optional)

Use local only for **editing code**, not as a second production instance.

- **Do not run** local uvicorn against `data/signals.db` expecting VPS numbers
- If you need local UI dev, use a separate dev database:

```env
DATABASE_PATH=data/signals.dev.db
```

## Scripts (optional, not required for your workflow)

`scripts/sync_production_database.ps1` exists if you ever want a local copy for offline inspection. **You do not need it** if you always audit on VPS.

## Summary

**Edit → Deploy VPS → Check VPS.** That is the only production loop.
