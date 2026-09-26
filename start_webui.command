#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Your Guitar Chronicle WebUI ==="
echo "Repository: $(pwd)"
echo "Branch: $(git branch --show-current)"

echo
echo "[1/4] Pulling latest changes..."
git pull --ff-only

echo
echo "[2/4] Preparing Python environment..."
cd app

if [ ! -d ".venv" ]; then
  echo "Creating .venv with python3.12..."
  python3.12 -m venv .venv
fi

source .venv/bin/activate

echo
echo "[3/4] Updating editable install..."
python -m pip install -e ".[dev]"

echo
echo "[4/4] Starting WebUI..."
echo "Close this Terminal window or press Ctrl+C to stop."
echo

ygc-web
