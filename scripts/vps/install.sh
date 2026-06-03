#!/usr/bin/env bash
# VoyahMonitor — one-shot VPS bootstrap (installs Docker via sudo if needed).
#
#   chmod +x install.sh
#   sudo ./install.sh
#   # or: VOYAH_REPO_URL=https://github.com/you/VoyahMonitor.git ./install.sh
#
# If Docker/git are already set up and you have no sudo, use install_nosudo.sh instead.
#
# After it finishes: upload .env and data/session.json, then:
#   cd /opt/voyah-monitor && ./first_start.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "${SCRIPT_DIR}/lib.sh"

VOYAH_INSTALL_DIR="${VOYAH_INSTALL_DIR:-/opt/voyah-monitor}"

if [[ "${EUID}" -ne 0 ]]; then
  SUDO="sudo"
else
  SUDO=""
fi

install_apt_packages() {
  if ! voyah_vps_command_exists apt-get; then
    return 0
  fi
  voyah_vps_log "Installing system packages (git, curl, ca-certificates) ..."
  ${SUDO} apt-get update -qq
  ${SUDO} DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl ca-certificates gnupg lsb-release
}

install_docker() {
  if voyah_vps_docker_ready; then
    voyah_vps_log "Docker is already installed."
    return 0
  fi

  voyah_vps_log "Installing Docker (get.docker.com) ..."
  if ! voyah_vps_command_exists curl; then
    install_apt_packages
  fi
  curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
  ${SUDO} sh /tmp/get-docker.sh
  rm -f /tmp/get-docker.sh

  if ! voyah_vps_docker_ready; then
    voyah_vps_die "Docker install finished but 'docker info' failed. Log out and in, or run: sudo usermod -aG docker \$USER"
  fi

  if ! docker compose version >/dev/null 2>&1; then
    voyah_vps_die "Docker Compose plugin not found after install."
  fi

  voyah_vps_log "Docker installed successfully."
}

clone_or_update_repo_sudo() {
  voyah_vps_command_exists git || install_apt_packages
  voyah_vps_command_exists git || voyah_vps_die "git is required but could not be installed."

  local parent
  parent="$(dirname "${VOYAH_INSTALL_DIR}")"
  ${SUDO} mkdir -p "${parent}"

  if [[ -d "${VOYAH_INSTALL_DIR}/.git" ]]; then
    voyah_vps_log "Updating existing clone in ${VOYAH_INSTALL_DIR} ..."
    git -C "${VOYAH_INSTALL_DIR}" fetch origin
    git -C "${VOYAH_INSTALL_DIR}" checkout "${VOYAH_GIT_BRANCH}"
    git -C "${VOYAH_INSTALL_DIR}" pull --ff-only origin "${VOYAH_GIT_BRANCH}" || true
  elif [[ -f "${VOYAH_INSTALL_DIR}/pyproject.toml" ]]; then
    voyah_vps_log "Directory ${VOYAH_INSTALL_DIR} exists but is not a git repo — skipping clone."
  else
    voyah_vps_log "Cloning ${VOYAH_REPO_URL} → ${VOYAH_INSTALL_DIR} ..."
    if [[ -n "${SUDO}" ]]; then
      ${SUDO} git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${VOYAH_INSTALL_DIR}"
    else
      git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${VOYAH_INSTALL_DIR}"
    fi
  fi

  [[ -f "${VOYAH_INSTALL_DIR}/pyproject.toml" ]] || voyah_vps_die "Repository not found at ${VOYAH_INSTALL_DIR}"

  if [[ -n "${SUDO_USER:-}" ]] && [[ "${SUDO_USER}" != "root" ]]; then
    voyah_vps_log "Setting owner of ${VOYAH_INSTALL_DIR} to ${SUDO_USER} ..."
    ${SUDO} chown -R "${SUDO_USER}:${SUDO_USER}" "${VOYAH_INSTALL_DIR}"
    if ! groups "${SUDO_USER}" | grep -q '\bdocker\b'; then
      voyah_vps_log "Adding ${SUDO_USER} to group docker ..."
      ${SUDO} usermod -aG docker "${SUDO_USER}" || true
    fi
  fi
}

print_docker_group_note() {
  if [[ -n "${SUDO_USER:-}" ]] && ! groups "${SUDO_USER}" 2>/dev/null | grep -q '\bdocker\b'; then
    echo "Note: user ${SUDO_USER} was added to group 'docker'."
    echo "      Log out and SSH in again before ./first_start.sh if 'docker' permission is denied."
    echo ""
  fi
}

main() {
  voyah_vps_log "VoyahMonitor VPS install (with sudo for Docker/system packages)"
  voyah_vps_log "  Repo:   ${VOYAH_REPO_URL}"
  voyah_vps_log "  Path:   ${VOYAH_INSTALL_DIR}"
  voyah_vps_log "  Branch: ${VOYAH_GIT_BRANCH}"

  if [[ "${EUID}" -ne 0 ]] && [[ -n "${SUDO}" ]] && ! voyah_vps_docker_ready; then
    voyah_vps_log "Docker not found — will install using sudo."
  elif [[ "${EUID}" -ne 0 ]] && ! voyah_vps_docker_ready && [[ "${VOYAH_INSTALL_DIR}" == /opt/* ]]; then
    voyah_vps_die "Run as root or with sudo, e.g.: sudo ./install.sh — or use ./install_nosudo.sh with VOYAH_INSTALL_DIR=\$HOME/voyah-monitor"
  fi

  install_apt_packages
  install_docker
  clone_or_update_repo_sudo
  voyah_vps_prepare_project_tree "${VOYAH_INSTALL_DIR}"
  voyah_vps_print_next_steps "${VOYAH_INSTALL_DIR}"
  print_docker_group_note
}

main "$@"
