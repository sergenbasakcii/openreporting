#!/usr/bin/env bash
# Backward-compatible Ubuntu/Debian entry point; Oracle Linux uses install-oracle-linux.sh.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "$SCRIPT_DIR/install-linux.sh" --expect-os debian "$@"
