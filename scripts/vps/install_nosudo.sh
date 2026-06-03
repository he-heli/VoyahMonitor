#!/usr/bin/env bash
# VoyahMonitor install_nosudo.sh v2 (self-contained, no lib.sh)
# VoyahMonitor — bootstrap without sudo (self-contained single file).
# Requires: git, curl, docker (current user), docker compose.
#
#   curl -fsSL .../install_nosudo.sh -o install_nosudo.sh
#   chmod +x install_nosudo.sh && ./install_nosudo.sh
#
# Default path: ~/voyah-monitor
#
set -euo pipefail

VOYAH_REPO_URL="${VOYAH_REPO_URL:-https://github.com/he-heli/VoyahMonitor.git}"
VOYAH_INSTALL_DIR="${VOYAH_INSTALL_DIR:-${HOME}/voyah-monitor}"
VOYAH_GIT_BRANCH="${VOYAH_GIT_BRANCH:-main}"

log() { echo "==> $*"; }
die() { echo "Error: $*" >&2; exit 1; }
command_exists() { command -v "$1" >/dev/null 2>&1; }
docker_ready() { command_exists docker && docker info >/dev/null 2>&1; }

clone_or_update_repo() {
  local install_dir="$1"
  command_exists git || die "git is not installed."

  local parent
  parent="$(dirname "${install_dir}")"
  mkdir -p "${parent}"

  if [[ -d "${install_dir}/.git" ]]; then
    log "Updating existing clone in ${install_dir} ..."
    git -C "${install_dir}" fetch origin
    git -C "${install_dir}" checkout "${VOYAH_GIT_BRANCH}"
    git -C "${install_dir}" pull --ff-only origin "${VOYAH_GIT_BRANCH}" || true
  elif [[ -f "${install_dir}/pyproject.toml" ]]; then
    log "Directory ${install_dir} exists but is not a git repo — skipping clone."
  else
    log "Cloning ${VOYAH_REPO_URL} → ${install_dir} ..."
    git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${install_dir}"
  fi

  [[ -f "${install_dir}/pyproject.toml" ]] || die "Repository not found at ${install_dir}"
}

prepare_project_tree() {
  local install_dir="$1"
  cd "${install_dir}"
  mkdir -p data
  touch data/.gitkeep

  if [[ ! -f .env ]]; then
    cp .env.example .env
    log "Created .env from .env.example (replace with your production .env)."
  fi

  chmod +x scripts/local-login.sh 2>/dev/null || true
  chmod +x scripts/prod/*.sh 2>/dev/null || true
  chmod +x scripts/vps/*.sh 2>/dev/null || true
  chmod +x first_start.sh 2>/dev/null || true
  chmod 700 data 2>/dev/null || true
}

print_next_steps() {
  local install_dir="$1"
  cat <<EOF

================================================================================
  VoyahMonitor: server preparation complete
================================================================================
  Install path: ${install_dir}

  Next steps:

  1) On your PC:
       ./scripts/local-login.sh
       voyah-monitor inspect

  2) Copy secrets (from your PC):
       scp .env ${USER}@$(hostname -f 2>/dev/null || hostname):${install_dir}/.env
       scp data/session.json ${USER}@$(hostname -f 2>/dev/null || hostname):${install_dir}/data/session.json
       ssh ${USER}@$(hostname -f 2>/dev/null || hostname) \\
         "chmod 600 ${install_dir}/.env ${install_dir}/data/session.json"

  3) On this server:
       cd ${install_dir}
       ./first_start.sh

  Logs: ./scripts/prod/logs.sh
================================================================================
EOF
}

require_prerequisites() {
  local missing=()

  command_exists git || missing+=("git")
  command_exists curl || missing+=("curl")

  if ! docker_ready; then
    missing+=("docker (try: docker info)")
  elif ! docker compose version >/dev/null 2>&1; then
    missing+=("docker compose plugin")
  fi

  if [[ ${#missing[@]} -gt 0 ]]; then
    die "Missing: ${missing[*]}. Use sudo ./install.sh on a fresh server."
  fi

  local parent
  parent="$(dirname "${VOYAH_INSTALL_DIR}")"
  if [[ ! -d "${parent}" ]] && ! mkdir -p "${parent}" 2>/dev/null; then
    die "Cannot create ${parent}. Set VOYAH_INSTALL_DIR to a writable path."
  fi
  if [[ -e "${VOYAH_INSTALL_DIR}" ]] && [[ ! -w "${VOYAH_INSTALL_DIR}" ]]; then
    die "${VOYAH_INSTALL_DIR} is not writable."
  fi
}

main() {
  log "VoyahMonitor VPS install (no sudo, standalone)"
  log "  Repo:   ${VOYAH_REPO_URL}"
  log "  Path:   ${VOYAH_INSTALL_DIR}"
  log "  Branch: ${VOYAH_GIT_BRANCH}"
  log "  User:   $(whoami)"

  require_prerequisites
  clone_or_update_repo "${VOYAH_INSTALL_DIR}"
  prepare_project_tree "${VOYAH_INSTALL_DIR}"
  print_next_steps "${VOYAH_INSTALL_DIR}"
}

main "$@"
