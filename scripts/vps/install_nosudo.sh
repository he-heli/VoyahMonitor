#!/usr/bin/env bash
# VoyahMonitor — bootstrap without sudo (Docker, git, compose must already work).
#
#   chmod +x install_nosudo.sh
#   ./install_nosudo.sh
#
# Default install path: ~/voyah-monitor (override with VOYAH_INSTALL_DIR).
# After it finishes: upload .env and data/session.json, then ./first_start.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_VOYAH_LIB="${SCRIPT_DIR}/lib.sh"
if [[ ! -f "${_VOYAH_LIB}" ]]; then
  _VOYAH_RAW="${VOYAH_RAW_BASE:-https://raw.githubusercontent.com/he-heli/VoyahMonitor/main/scripts/vps}"
  command -v curl >/dev/null 2>&1 || {
    echo "Error: lib.sh not found next to this script and curl is unavailable." >&2
    echo "Clone the repo or download lib.sh into ${SCRIPT_DIR}/" >&2
    exit 1
  }
  echo "==> Downloading lib.sh ..."
  curl -fsSL "${_VOYAH_RAW}/lib.sh" -o "${_VOYAH_LIB}"
fi
# shellcheck source=lib.sh
source "${_VOYAH_LIB}"

VOYAH_INSTALL_DIR="${VOYAH_INSTALL_DIR:-${HOME}/voyah-monitor}"

require_prerequisites() {
  local missing=()

  voyah_vps_command_exists git || missing+=("git")
  voyah_vps_command_exists curl || missing+=("curl")

  if ! voyah_vps_docker_ready; then
    missing+=("docker (running, accessible to current user — try: docker info)")
  elif ! docker compose version >/dev/null 2>&1; then
    missing+=("docker compose plugin (docker compose version)")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    voyah_vps_die "Missing prerequisites (install system packages or use sudo ./install.sh): ${missing[*]}"
  fi

  local parent
  parent="$(dirname "${VOYAH_INSTALL_DIR}")"
  if [[ ! -d "${parent}" ]] && ! mkdir -p "${parent}" 2>/dev/null; then
    voyah_vps_die "Cannot create ${parent}. Choose a writable VOYAH_INSTALL_DIR."
  fi
  if [[ -e "${VOYAH_INSTALL_DIR}" ]] && [[ ! -w "${VOYAH_INSTALL_DIR}" ]]; then
    voyah_vps_die "${VOYAH_INSTALL_DIR} is not writable. Use e.g. VOYAH_INSTALL_DIR=\$HOME/voyah-monitor"
  fi
}

main() {
  voyah_vps_log "VoyahMonitor VPS install (no sudo)"
  voyah_vps_log "  Repo:   ${VOYAH_REPO_URL}"
  voyah_vps_log "  Path:   ${VOYAH_INSTALL_DIR}"
  voyah_vps_log "  Branch: ${VOYAH_GIT_BRANCH}"
  voyah_vps_log "  User:   $(whoami)"

  require_prerequisites
  voyah_vps_clone_or_update_repo "${VOYAH_INSTALL_DIR}"
  voyah_vps_prepare_project_tree "${VOYAH_INSTALL_DIR}"
  voyah_vps_print_next_steps "${VOYAH_INSTALL_DIR}"
}

main "$@"
