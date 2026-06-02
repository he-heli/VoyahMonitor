#!/usr/bin/env bash
# One-time VPS setup: clone repo, prepare data dir and .env template.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

INSTALL_DIR="${1:-${VOYAH_ROOT}}"
REPO_URL="${VOYAH_REPO_URL:-}"

require_docker

if [[ -n "${REPO_URL}" ]] && [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "Cloning ${REPO_URL} into ${INSTALL_DIR} ..."
  mkdir -p "$(dirname "${INSTALL_DIR}")"
  git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

if [[ ! -f "${INSTALL_DIR}/pyproject.toml" ]]; then
  echo "Error: run from the project directory or set VOYAH_REPO_URL and install path." >&2
  echo "  Example: VOYAH_REPO_URL=https://github.com/you/VoyahMonitor.git ./scripts/prod/bootstrap.sh /opt/voyah-monitor" >&2
  exit 1
fi

cd "${INSTALL_DIR}"
mkdir -p data
touch data/.gitkeep

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — edit it before starting the bot."
else
  echo ".env already exists — left unchanged."
fi

chmod 700 data 2>/dev/null || true

echo ""
echo "Bootstrap done in ${INSTALL_DIR}"
echo ""
echo "Before ./scripts/prod/up.sh:"
echo "  1. On your PC: scripts/local-login.sh"
echo "  2. voyah-monitor inspect → paste VOYAH_ALLOWED_* into .env here"
echo "  3. scp .env and data/session.json to this server"
echo "  4. chmod 600 .env data/session.json"
