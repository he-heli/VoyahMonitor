# Shared helpers for scripts/prod/*.sh — source, do not execute directly.
set -euo pipefail

_voyah_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VOYAH_ROOT="$(cd "${_voyah_lib_dir}/../.." && pwd)"

voyah_cd_root() {
  cd "${VOYAH_ROOT}"
}

require_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    echo "Error: Docker is not installed." >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    echo "Error: docker compose plugin is not available." >&2
    exit 1
  fi
}

require_env_file() {
  if [[ ! -f "${VOYAH_ROOT}/.env" ]]; then
    echo "Error: .env not found. Copy .env.example and fill in values." >&2
    exit 1
  fi
}

require_session_file() {
  if [[ ! -f "${VOYAH_ROOT}/data/session.json" ]]; then
    echo "Error: data/session.json not found." >&2
    echo "Run scripts/local-login.sh on your PC, then copy session.json to the server." >&2
    exit 1
  fi
}

require_telegram_token() {
  require_env_file
  if ! grep -qE '^TELEGRAM_BOT_TOKEN=[^[:space:]]' "${VOYAH_ROOT}/.env"; then
    echo "Error: TELEGRAM_BOT_TOKEN is not set in .env" >&2
    exit 1
  fi
}

require_prod_ready() {
  voyah_cd_root
  require_docker
  require_env_file
  require_session_file
  require_telegram_token
  mkdir -p data
}
