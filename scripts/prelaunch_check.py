"""Pre-launch verification script."""
from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parents[1]


def get(path: str, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(f"{BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def post(path: str, payload: dict, timeout: int = 15) -> tuple[int, dict]:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


def main() -> None:
    print("=== HEALTH ===")
    code, body = get("/health")
    health = json.loads(body)
    print("status code", code, "status field", health.get("status"))
    for key in ("market_data", "database", "signal_engine", "paper_trading"):
        print(f"  {key}:", health.get(key))

    print("\n=== DELTA DATA ===")
    for sym in ("BTC", "ETH", "SOL"):
        for tf in ("1m", "5m", "15m", "1h"):
            c, b = get(f"/chart/{sym}?timeframe={tf}&limit=3")
            ok = c == 200 and json.loads(b).get("candles")
            print(f"  {sym}/{tf}: {'OK' if ok else 'FAIL'} ({c})")

    print("\n=== PAPER PREVIEW ===")
    for lev in (10, 20, 50):
        for side in ("BUY", "SELL"):
            _, d = post(
                "/paper/preview",
                {
                    "symbol": "ETHUSDT",
                    "side": side,
                    "entry": 1750.0,
                    "margin_percent": 25,
                    "leverage": lev,
                    "stop_loss": 1700.0,
                    "take_profit": 1800.0,
                },
            )
            print(f"  {side} {lev}x margin={d['margin_used']} qty={d['quantity']:.4f}")

    print("\n=== DATABASE ===")
    db = ROOT / "data" / "signals.db"
    print("  exists:", db.exists(), db)
    if db.exists():
        conn = sqlite3.connect(db)
        sig = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        closed = conn.execute("SELECT COUNT(*) FROM positions WHERE status='CLOSED'").fetchone()[0]
        open_ = conn.execute("SELECT COUNT(*) FROM positions WHERE status='OPEN'").fetchone()[0]
        bal = conn.execute("SELECT balance FROM paper_account WHERE id=1").fetchone()[0]
        conn.close()
        print(f"  signals={sig} closed={closed} open={open_} balance={bal}")

    print("\n=== LOG FILE ===")
    log = ROOT / "logs" / "app.log"
    print("  exists:", log.exists())
    if log.exists():
        text = log.read_text(encoding="utf-8", errors="ignore")
        for token in (
            "Signal Generated",
            "Signal Approved",
            "Trade Opened",
            "Trade Closed",
            "TP Hit",
            "SL Hit",
            "ERROR",
        ):
            print(f"  '{token}' in log:", token in text)

    print("\n=== STATIC ASSETS ===")
    for f in ("signal.mp3", "tp.mp3", "sl.mp3"):
        p = ROOT / "app" / "static" / "sounds" / f
        print(f"  {f}:", p.exists())


if __name__ == "__main__":
    main()
