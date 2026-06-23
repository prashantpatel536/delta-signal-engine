#!/usr/bin/env bash
# Pull production SQLite from VPS (canonical 24/7 source) to local machine.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VPS_HOST="${VPS_HOST:-vmi3381775}"
VPS_USER="${VPS_USER:-root}"
REMOTE_DB="${VPS_DATABASE_PATH:-/root/delta-signal-engine/data/signals.db}"
LOCAL_DB="${DATABASE_PATH:-$ROOT/data/signals.db}"

if [[ "$LOCAL_DB" != /* ]]; then
  LOCAL_DB="$ROOT/$LOCAL_DB"
fi

mkdir -p "$(dirname "$LOCAL_DB")"
TS="$(date -u +%Y%m%d-%H%M%S)"
BACKUP="${LOCAL_DB}.local-backup-${TS}"

if [[ -f "$LOCAL_DB" ]]; then
  cp "$LOCAL_DB" "$BACKUP"
  echo "Backed up local DB -> $BACKUP"
fi

echo "Pulling ${VPS_USER}@${VPS_HOST}:${REMOTE_DB} ..."
scp "${VPS_USER}@${VPS_HOST}:${REMOTE_DB}" "${LOCAL_DB}.download"
mv -f "${LOCAL_DB}.download" "$LOCAL_DB"

cat > "$(dirname "$LOCAL_DB")/production_sync.json" <<EOF
{
  "synced_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "source": "vps",
  "vps_host": "$VPS_HOST",
  "vps_user": "$VPS_USER",
  "remote_path": "$REMOTE_DB",
  "local_path": "$LOCAL_DB",
  "backup_path": "$BACKUP"
}
EOF

echo "OK — local database replaced with VPS copy: $LOCAL_DB"
