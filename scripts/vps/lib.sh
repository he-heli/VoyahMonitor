# Shared helpers for scripts/vps/install*.sh — source, do not execute directly.
set -euo pipefail

VOYAH_REPO_URL="${VOYAH_REPO_URL:-https://github.com/he-heli/VoyahMonitor.git}"
VOYAH_GIT_BRANCH="${VOYAH_GIT_BRANCH:-main}"

voyah_vps_log() { echo "==> $*"; }
voyah_vps_die() { echo "Error: $*" >&2; exit 1; }

voyah_vps_command_exists() { command -v "$1" >/dev/null 2>&1; }

voyah_vps_docker_ready() {
  voyah_vps_command_exists docker && docker info >/dev/null 2>&1
}

voyah_vps_clone_or_update_repo() {
  local install_dir="$1"
  voyah_vps_command_exists git || voyah_vps_die "git is not installed."

  local parent
  parent="$(dirname "${install_dir}")"
  mkdir -p "${parent}"

  if [[ -d "${install_dir}/.git" ]]; then
    voyah_vps_log "Updating existing clone in ${install_dir} ..."
    git -C "${install_dir}" fetch origin
    git -C "${install_dir}" checkout "${VOYAH_GIT_BRANCH}"
    git -C "${install_dir}" pull --ff-only origin "${VOYAH_GIT_BRANCH}" || true
  elif [[ -f "${install_dir}/pyproject.toml" ]]; then
    voyah_vps_log "Directory ${install_dir} exists but is not a git repo — skipping clone."
  else
    voyah_vps_log "Cloning ${VOYAH_REPO_URL} → ${install_dir} ..."
    git clone --branch "${VOYAH_GIT_BRANCH}" --depth 1 "${VOYAH_REPO_URL}" "${install_dir}"
  fi

  [[ -f "${install_dir}/pyproject.toml" ]] || voyah_vps_die "Repository not found at ${install_dir}"
}

voyah_vps_prepare_project_tree() {
  local install_dir="$1"
  cd "${install_dir}"
  mkdir -p data
  touch data/.gitkeep

  if [[ ! -f .env ]]; then
    cp .env.example .env
    voyah_vps_log "Created .env from .env.example (replace with your production .env)."
  fi

  chmod +x scripts/local-login.sh 2>/dev/null || true
  chmod +x scripts/prod/*.sh 2>/dev/null || true
  chmod +x scripts/vps/*.sh 2>/dev/null || true
  chmod +x first_start.sh 2>/dev/null || true
  chmod 700 data 2>/dev/null || true
}

voyah_vps_print_next_steps() {
  local install_dir="$1"
  cat <<EOF

================================================================================
  VoyahMonitor: server preparation complete
================================================================================
  Install path: ${install_dir}

  Next steps:

  1) On your PC:
       ./scripts/local-login.sh
       voyah-monitor inspect    # copy API paths into .env

  2) Copy secrets to this server (from your PC):
       scp .env ${USER}@$(hostname -f 2>/dev/null || hostname):${install_dir}/.env
       scp data/session.json ${USER}@$(hostname -f 2>/dev/null || hostname):${install_dir}/data/session.json
       ssh ${USER}@$(hostname -f 2>/dev/null || hostname) \\
         "chmod 600 ${install_dir}/.env ${install_dir}/data/session.json"

  3) On this server:
       cd ${install_dir}
       ./first_start.sh

  Logs later:  ./scripts/prod/logs.sh
  Docs:        docs/DEPLOY.md
================================================================================
EOF
}
