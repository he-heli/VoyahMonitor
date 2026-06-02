#!/usr/bin/env bash
# Interactive SMS login on your computer (browser + captcha). Not for headless VPS.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Error: python3 is required." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment in .venv ..."
  python3 -m venv .venv
fi

# shellcheck source=/dev/null
source .venv/bin/activate

python -m pip install -q -U pip
python -m pip install -q -e ".[login]"
playwright install chromium

mkdir -p data

echo "Starting VOYAH login (session → data/session.json) ..."
python scripts/local_login.py

echo ""
echo "Next steps:"
echo "  1. voyah-monitor inspect   # copy API paths into .env"
echo "  2. Copy .env and data/session.json to your VPS (see docs/DEPLOY.md)"
