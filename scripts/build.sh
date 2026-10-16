#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Build code-generated contracts and an isolated native Python environment.
set -euo pipefail
PKG="${RBNX_PACKAGE_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$PKG"

if ! command -v rbnx >/dev/null 2>&1; then
    echo "[find-object/build] error: rbnx not found on PATH" >&2
    exit 1
fi

rbnx codegen -p "$PKG" --mcp
if [[ ! -d .venv ]]; then
    python3 -m venv --system-site-packages .venv
fi
.venv/bin/pip install -q --upgrade pip
# mcp 2.x removes mcp.server.fastmcp, which robonix-api v1 imports at runtime;
# same v1-compatible pin set as skill-explore-rbnx.
.venv/bin/pip install -q "fastmcp>=3,<4" "mcp>=1.28.1,<2" grpcio pillow
echo "[find-object/build] done"
