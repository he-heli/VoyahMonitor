#!/usr/bin/env bash
# VoyahMonitor — one-shot VPS bootstrap (copy this file to a fresh server and run).
#
#   chmod +x install.sh
#   sudo ./install.sh
#   # or: VOYAH_REPO_URL=https://github.com/you/VoyahMonitor.git ./install.sh
#
# After it finishes: upload .env and data/session.json, then:
#   cd /opt/voyah-monitor && ./first_start.sh
#
set -euo pipefail

VOYAH_REPO_URL="${VOYAH_REPO_URL:-https://github.com/he-heli/VoyahMonitor.git}"
VOYAH_INSTALL_DIR="${VOYAH_INSTALL_DIR:-/opt/voyah-monitor}"
VOYAH_GIT_BRANCH="${VOYAH_GIT_BRANCH:-main}"

if [[ "${EUID}" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

log() { echo "==> $*"; }
die() { echo "Error: $*" >&2; exit 1; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

install_apt_packages() {
  if ! command_exists apt-get; then
    return 0
  fi
  log "Installing system packages (git, curl, ca-certificates) ..."
  ${SUDO} apt-get update -qq
  ${SUDO} DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl ca-certificates gnupg lsb-release
}

docker_ready() {
  command_exists docker && docker info >/dev/null 2>&1
}

install_docker() {
  if docker_ready; then
    log "Docker is already installed."
    return 0
  fi

  log "Installing Docker (get.docker.com) ..."
  if ! command_exists curl; then
    install_apt_packages
  fi
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  ${SUDO} sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh

  if ! docker_ready; then
    die "Docker install finished but 'docker info' failed. Log out and in, or run: sudo usermod -aG docker \$USER"
  fi

  if ! docker compose version >/dev/null 2>&1; then
    die "Docker Compose plugin not found after install."
  fi

  log "Docker installed successfully."
}

ensure_git() {
  if command_exists git; then
    return 0
  fi
  install_apt_packages
  command_exists git || die "git is required but could not be installed."
}

clone_or_update_repo() {
  ensure_git
  local parent dir_owner
  parent="$(dirname "${VOYAH_INSTALL_DIR}")"
  ${SUDO} mkdir -p "${parent}"

  if [[ -d "${VOYAH_INSTALL_DIR}/.git" ]]; then
    log "Updating existing clone in ${VOYAH_INSTALL_DIR} ..."
    git -C "${VOYAH_INSTALL_DIR}" fetch origin
    git -C "${VOYAH_INSTALL_DIR}" checkout "${VOYAH_GIT_BRANCH}"
    git -C "${VOYAH_INSTALL_DIR}" pull --ff-only origin "${VOYAH_GIT_BRANCH}" || true
  elif [[ -f "${VOYAH_INSTALL_DIR}/pyproject.toml" ]]; then
    log "Directory ${VOYAH_INSTALL_DIR} exists but is not a git repo — skipping clone."
  else
    log "Cloning ${VOYAH_REPO_URL} → ${VOYAH_INSTALL_DIR} ..."
    if [[ -n "${SUDO}" ]]; then
      ${SUDO} git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${VOYAH_INSTALL_DIR}"
    else
      git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${VOYAH_INSTALL_DIR}"
    fi
  fi

  if [[ ! -f "${VOYAH_INSTALL_DIR}/pyproject.toml" ]]; then
    die "Repository not found at ${VOYAH_INSTALL_DIR}"
  fi

  # Run docker/build as the invoking user when install was started with sudo
  if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    dir_owner="${SUDO_USER}"
    log "Setting owner of ${VOYAH_INSTALL_DIR} to ${dir_owner} ..."
    ${SUDO} chown -R "${dir_owner}:${dir_owner}" "${VOYAH_INSTALL_DIR}"
    if ! groups "${dir_owner}" | grep -q '\bdocker\b'; then
      log "Adding ${dir_owner} to group docker ..."
      ${SUDO} usermod -aG docker "${dir_owner}" || true
    fi
  elif [[ "${EUID}" -eq 0 ]] && [[ -n "${SUDO_USER:-}" ]]; then
    :
  fi
}

prepare_project_tree() {
  cd "${VOYAH_INSTALL_DIR}"
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
  cat <<EOF

================================================================================
  VoyahMonitor: server preparation complete
================================================================================
  Install path: ${VOYAH_INSTALL_DIR}

  Next steps:

  1) On your PC:
       ./scripts/local-login.sh
       voyah-monitor inspect    # copy API paths into .env

  2) Copy secrets to this server (from your PC):
       scp .env ${USER}@$(hostname -f 2>/dev/null || hostname):${VOYAH_INSTALL_DIR}/.env
       scp data/session.json ${USER}@$(hostname -f 2>/dev/null || hostname):${VOYAH_INSTALL_DIR}/data/session.json
       ssh ${USER}@$(hostname -f 2>/dev/null || hostname) \\
         "chmod 600 ${VOYAH_INSTALL_DIR}/.env ${VOYAH_INSTALL_DIR}/data/session.json"

  3) On this server:
       cd ${VOYAH_INSTALL_DIR}
       ./first_start.sh

  Logs later:  ./scripts/prod/logs.sh
  Docs:        docs/DEPLOY.md
================================================================================
EOF
  if [[ -n "${SUDO_USER:-}" ]] && ! groups "${SUDO_USER}" 2>/dev/null | grep -q '\bdocker\b'; then
    echo "Note: user ${SUDO_USER} was added to group 'docker'."
    echo "      Log out and SSH in again before ./first_start.sh if 'docker' permission is denied."
    echo ""
  fi
}

main() {
  log "VoyahMonitor VPS install"
  log "  Repo:   ${VOYAH_REPO_URL}"
  log "  Path:   ${VOYAH_INSTALL_DIR}"
  log "  Branch: ${VOYAH_GIT_BRANCH}"

  if [[ "${EUID}" -ne 0 ]] && [[ -n "${SUDO}" ]] && ! docker_ready; then
    log "Docker not found — will install using sudo."
  elif [[ "${EUID}" -ne 0 ]] && ! docker_ready && [[ "${VOYAH_INSTALL_DIR}" == /opt/* ]]; then
    die "Run as root or with sudo, e.g.: sudo ./install.sh"
  fi

  install_apt_packages
  install_docker
  clone_or_update_repo
  prepare_project_tree
  print_next_steps
}

main "$@"
