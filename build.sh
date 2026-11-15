#!/bin/bash
# Build "Cairn.app" into dist/. Only ./static is bundled, never ./config (it can hold credentials).
set -euo pipefail
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements-dev.txt
[ -n "${SKIP_TESTS:-}" ] || .venv/bin/python -m pytest -q tests --ignore=tests/e2e     # the release workflow tests first
.venv/bin/python -m PyInstaller --noconfirm --clean --windowed \
    --name "Cairn" \
    --icon packaging/cairn.icns \
    --osx-bundle-identifier io.github.s-himansh.cairn \
    --add-data "static:static" \
    --collect-submodules db_connectors \
    --collect-all cassandra \
    --collect-all pymssql \
    --collect-submodules keyring \
    --collect-submodules anthropic \
    --copy-metadata keyring \
    db.py
echo "Built: dist/Cairn.app"
echo "Unsigned. To distribute: codesign --deep --options runtime --sign \"Developer ID Application: …\" and notarize."
