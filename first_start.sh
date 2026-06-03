#!/usr/bin/env bash
# First production start after .env and data/session.json are on the server.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "${ROOT}/scripts/prod/first_start.sh" "$@"
