#!/bin/bash
set -e

cd "$(dirname "$0")"

echo "=== Your Guitar Chronicle WebUI ==="
echo "Repository: $(pwd)"
echo "Branch: $(git branch --show-current)"

echo
echo "[1/4] Checking automatic update..."
if ! git rev-parse --verify '@{upstream}' >/dev/null 2>&1; then
  echo "No upstream branch. Starting with local code."
elif [ -n "$(git status --porcelain)" ]; then
  echo "Uncommitted changes found. Starting with local code."
else
  git pull --ff-only
fi

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
python ../scripts/install_dependencies.py

echo
echo "[4/4] Starting WebUI..."
echo "Close this Terminal window or press Ctrl+C to stop."
echo

ygc-web
