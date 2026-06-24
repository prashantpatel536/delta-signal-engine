# VPS deploy — fix git pull + install service

## Errors you saw

1. **`Please commit your changes or stash them before you merge`** — VPS has local modified files (often `logs/app.log` or `.env`). Git refuses to pull.
2. **`Unit delta-signal-engine.service not found`** — systemd service was never installed.

---

## Fix right now (on VPS)

Run these on the server:

```bash
cd ~/delta-signal-engine

# See what is blocking the pull
git status

# Stash local changes (safe — keeps your .env and data/*.db; logs only)
git stash push -u -m "before-deploy"

# Pull latest code
git pull origin main

# One-time: install systemd service (after pull includes deploy/ folder)
chmod +x scripts/vps_deploy.sh
./scripts/vps_deploy.sh
```

If `git pull` still fails, discard **only** tracked junk (not `.env` or database):

```bash
git checkout -- logs/app.log 2>/dev/null || true
git pull origin main
```

---

## One-time systemd setup (manual)

If `deploy/delta-signal-engine.service` exists after pull:

```bash
cd ~/delta-signal-engine
sudo cp deploy/delta-signal-engine.service /etc/systemd/system/
# If project is NOT in /root/delta-signal-engine, edit WorkingDirectory and ExecStart paths:
# sudo nano /etc/systemd/system/delta-signal-engine.service

sudo systemctl daemon-reload
sudo systemctl enable delta-signal-engine
sudo systemctl start delta-signal-engine
sudo systemctl status delta-signal-engine
```

---

## Every deploy after that

**On your PC:** commit + push

```bash
git push origin main
```

**On VPS:**

```bash
cd ~/delta-signal-engine
./scripts/vps_deploy.sh
```

Or manually:

```bash
git stash push -u -m "deploy" ; git pull origin main ; sudo systemctl restart delta-signal-engine
```

---

## Verify

```bash
curl http://127.0.0.1:8000/api/debug/system
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/chart/ETH?timeframe=5m&limit=50"
```

Browser: `http://YOUR_VPS_IP:8000/debug/system`

### Chart not loading

1. Check health: `curl http://127.0.0.1:8000/health` — `market_data` must not be `fail`
2. Check chart API: `curl "http://127.0.0.1:8000/chart/ETH?timeframe=5m"` — must return candles JSON, not 503
3. Restart after deploy: `./scripts/vps_deploy.sh`
4. View logs: `sudo journalctl -u delta-signal-engine -n 100 --no-pager`
5. Hard refresh browser: Ctrl+Shift+R (loads `/static/vendor/lightweight-charts...` from server)

---

## If service still fails

Check logs:

```bash
sudo journalctl -u delta-signal-engine -n 50 --no-pager
```

Common fixes:

- **No venv:** `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
- **No .env:** `cp .env.example .env` then edit Telegram/API keys on VPS
- **Port in use:** `sudo lsof -i :8000` then kill old uvicorn
