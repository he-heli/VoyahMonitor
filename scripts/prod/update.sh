#!/usr/bin/env bash
# Pull latest code from git (does not restart containers).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"

voyah_cd_root

if [[ ! -d .git ]]; then
  echo "Error: not a git repository." >&2
  exit 1
fi

git pull --ff-only
echo "Repository updated. Run ./scripts/prod/rebuild.sh to apply changes in Docker."
