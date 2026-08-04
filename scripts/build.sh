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
.venv/bin/pip install -q fastmcp grpcio pillow
echo "[find-object/build] done"
