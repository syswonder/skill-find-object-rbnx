#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Run the native skill with generated contracts and Robonix API on PYTHONPATH.
set -euo pipefail
PKG="${RBNX_PACKAGE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PKG"

export PYTHONPATH="$PKG:$PKG/rbnx-build/codegen/proto_gen:$PKG/rbnx-build/codegen/robonix_mcp_types:${PYTHONPATH:-}"
if ROBONIX_API_PATH="$(rbnx path robonix-api 2>/dev/null)"; then
    export PYTHONPATH="$ROBONIX_API_PATH:$PYTHONPATH"
fi

exec "$PKG/.venv/bin/python" -u -m find_object_skill.atlas_bridge
