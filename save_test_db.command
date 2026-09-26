#!/bin/bash
set -e

cd "$(dirname "$0")"

SOURCE="app/data/chronicle.db"
TARGET="app/tests/data/ygc_test_snapshot.db"

if [ ! -f "$SOURCE" ]; then
  echo "Source DB not found: $SOURCE"
  exit 1
fi

mkdir -p "app/tests/data"

PYTHON="app/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

echo "Creating consistent SQLite test snapshot..."
"$PYTHON" - "$SOURCE" "$TARGET" <<'PY'
import sqlite3
import sys

source_path, target_path = sys.argv[1], sys.argv[2]
with sqlite3.connect(source_path) as source:
    with sqlite3.connect(target_path) as destination:
        source.backup(destination)
PY

echo
echo "Test DB updated:"
echo "$TARGET"
echo
echo "The file is intentionally Git-managed."
git status --short "$TARGET"
