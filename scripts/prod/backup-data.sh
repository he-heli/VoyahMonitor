#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

voyah_cd_root

BACKUP_DIR="${VOYAH_ROOT}/backups"
STAMP="$(date +%Y%m%d_%H%M%S)"
ARCHIVE="${BACKUP_DIR}/voyah-data_${STAMP}.tar.gz"

mkdir -p "${BACKUP_DIR}"

shopt -s nullglob
files=(data/session.json data/voyah_monitor.db data/bot_settings.json data/network_capture.json)
existing=()
for f in "${files[@]}"; do
  [[ -f "${f}" ]] && existing+=("${f}")
done

if [[ ${#existing[@]} -eq 0 ]]; then
  echo "Nothing to backup under data/." >&2
  exit 1
fi

tar -czf "${ARCHIVE}" "${existing[@]}"
echo "Backup saved: ${ARCHIVE}"
