#!/usr/bin/env bash
# Build and start the bot — run after uploading .env and data/session.json.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

require_prod_ready

if ! docker info >/dev/null 2>&1; then
  echo "Error: cannot run 'docker info'. Try:" >&2
  echo "  newgrp docker" >&2
  echo "  # or log out and SSH in again after install.sh added you to group docker" >&2
  exit 1
fi

chmod 600 "${VOYAH_ROOT}/.env" 2>/dev/null || true
chmod 600 "${VOYAH_ROOT}/data/session.json" 2>/dev/null || true

log_msg() { echo "==> $*"; }

log_msg "Building production image (no Playwright) ..."
docker compose build voyah-monitor

log_msg "Starting bot ..."
docker compose up -d voyah-monitor

echo ""
docker compose ps
echo ""
echo "First start complete. Open Telegram and send /start to your bot."
echo "Logs: cd ${VOYAH_ROOT} && ./scripts/prod/logs.sh"
