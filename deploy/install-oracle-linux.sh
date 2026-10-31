#!/usr/bin/env bash
# Native Oracle Linux 8.10 / 9 / 10 installer. See docs/ORACLE_LINUX.md for acceptance boundaries.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install-linux.sh" --expect-os oracle "$@"
