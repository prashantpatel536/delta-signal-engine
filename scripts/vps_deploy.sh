#!/usr/bin/env bash
# Run ON THE VPS from the project root: ./scripts/vps_deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Delta Signal Engine — VPS deploy ==="

if [[ -d .git ]]; then
  echo "Git status before pull:"
  git status -sb || true
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Stashing local changes (e.g. logs) before pull..."
    git stash push -u -m "vps-pre-deploy-$(date -u +%Y%m%d-%H%M%S)" || true
  fi
  git pull origin main
else
  echo "Not a git repo — skip pull"
fi

if [[ ! -d .venv ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt
echo "Ensuring CA certificates (certifi)..."
.venv/bin/pip install -q --force-reinstall certifi
.venv/bin/python -c "import certifi; from pathlib import Path; p=certifi.where(); assert Path(p).is_file(), p; print('CA bundle OK:', p)"

if [[ ! -f .env ]]; then
  echo "WARNING: .env missing — copy .env.example and configure on VPS"
fi

stop_port_8000() {
  echo "Stopping any process bound to port 8000..."
  sudo systemctl stop "$SERVICE_NAME" 2>/dev/null || true
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  if command -v fuser >/dev/null 2>&1; then
    sudo fuser -k 8000/tcp 2>/dev/null || true
  elif command -v lsof >/dev/null 2>&1; then
    stale_pids="$(sudo lsof -t -i :8000 2>/dev/null || true)"
    if [[ -n "${stale_pids:-}" ]]; then
      sudo kill -9 $stale_pids 2>/dev/null || true
    fi
  fi
  sleep 2
  if command -v ss >/dev/null 2>&1 && ss -ltn | grep -q ':8000'; then
    echo "ERROR: port 8000 is still in use. Run: sudo lsof -i :8000"
    exit 1
  fi
  echo "Port 8000 is free."
}

SERVICE_NAME="delta-signal-engine.service"
SERVICE_SRC="$ROOT/deploy/delta-signal-engine.service"
SERVICE_DST="/etc/systemd/system/$SERVICE_NAME"

if [[ -f "$SERVICE_SRC" ]]; then
  echo "Installing systemd unit..."
  sed "s|/root/delta-signal-engine|$ROOT|g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" > /dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable "$SERVICE_NAME"
  stop_port_8000
  sudo systemctl start "$SERVICE_NAME"
  sleep 3
  sudo systemctl status "$SERVICE_NAME" --no-pager -l || true
else
  echo "No systemd unit — restarting uvicorn manually..."
  stop_port_8000
  nohup .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> logs/app.log 2>&1 &
  echo "Started uvicorn in background (no systemd)."
fi

echo ""
echo "Verify:"
curl -s http://127.0.0.1:8000/health | .venv/bin/python -m json.tool 2>/dev/null || curl -s http://127.0.0.1:8000/health
echo ""
curl -s http://127.0.0.1:8000/trade-history | .venv/bin/python -m json.tool 2>/dev/null | head -c 400 || curl -s http://127.0.0.1:8000/trade-history | head -c 400
echo ""
