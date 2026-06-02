#!/usr/bin/env bash
# Example: copy secrets from your PC to VPS (edit host and paths, then run locally).
set -euo pipefail

VPS_USER="${VPS_USER:-root}"
VPS_HOST="${VPS_HOST:-your.vps.example}"
REMOTE_DIR="${REMOTE_DIR:-/opt/voyah-monitor}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

scp "${ROOT}/.env" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/.env"
scp "${ROOT}/data/session.json" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/session.json"

# Optional: migrate history and bot settings
# scp "${ROOT}/data/voyah_monitor.db" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/"
# scp "${ROOT}/data/bot_settings.json" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/data/"

ssh "${VPS_USER}@${VPS_HOST}" "chmod 600 ${REMOTE_DIR}/.env ${REMOTE_DIR}/data/session.json"

echo "Secrets uploaded to ${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}"
