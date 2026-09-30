#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${ROOT_DIR}/.venv313/bin/python"
PYINSTALLER_BIN="${ROOT_DIR}/.venv313/bin/pyinstaller"
APP_NAME="PortfolioAnalyzer"
PYI_CONFIG_DIR="${ROOT_DIR}/.pyinstaller-config"
MPL_CONFIG_DIR="${ROOT_DIR}/.matplotlib"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Missing Python environment at .venv313"
  echo "Create it with: python3.13 -m venv .venv313"
  exit 1
fi

if [[ ! -x "$PYINSTALLER_BIN" ]]; then
  echo "Missing PyInstaller in .venv313"
  echo "Install it with: .venv313/bin/pip install pyinstaller"
  exit 1
fi

echo "Building ${APP_NAME}.app ..."
rm -rf build dist "${APP_NAME}.spec"
mkdir -p "$PYI_CONFIG_DIR" "$MPL_CONFIG_DIR"

export PYINSTALLER_CONFIG_DIR="$PYI_CONFIG_DIR"
export MPLCONFIGDIR="$MPL_CONFIG_DIR"

"$PYINSTALLER_BIN" \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "com.carpion.portfolioanalyzer" \
  portfolio_analyzer.py

APP_PATH="dist/${APP_NAME}.app"
ZIP_PATH="dist/${APP_NAME}-macOS.zip"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Build failed: ${APP_PATH} not found."
  exit 1
fi

echo "Creating zip for email distribution ..."
rm -f "$ZIP_PATH"
(
  cd dist
  ditto -c -k --sequesterRsrc --keepParent "${APP_NAME}.app" "${APP_NAME}-macOS.zip"
)

echo "Done."
echo "App: ${ROOT_DIR}/${APP_PATH}"
echo "Zip: ${ROOT_DIR}/${ZIP_PATH}"
