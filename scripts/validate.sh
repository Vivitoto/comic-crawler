#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_ENV="${WNACG_PYTHON_ENV:-.venv312}"
if ! "$PYTHON_ENV/bin/python" -c 'import pytest' >/dev/null 2>&1; then
  PYTHON_ENV=".venv312-new"
fi
if ! "$PYTHON_ENV/bin/python" -c 'import pytest' >/dev/null 2>&1; then
  echo "Python environment is missing pytest: $PYTHON_ENV" >&2
  exit 1
fi

TMP_ALEMBIC_DB="${WNACG_VALIDATE_DB_PATH:-/tmp/wnacg-validate-alembic.sqlite}"
TMP_CONFIG="${WNACG_VALIDATE_CONFIG_PATH:-/tmp/wnacg-validate-missing-config.json}"
TMP_TEST_ROOT="${WNACG_VALIDATE_TEST_ROOT:-/tmp/wnacg-validate-tests}"

rm -f "$TMP_ALEMBIC_DB"
rm -rf "$TMP_TEST_ROOT"

"$PYTHON_ENV/bin/ruff" check backend
"$PYTHON_ENV/bin/mypy" backend
WNACG_CONFIG_PATH="$TMP_TEST_ROOT/config.local.json" \
  WNACG_DB_PATH="$TMP_TEST_ROOT/data.sqlite" \
  WNACG_DOWNLOAD_PATH="$TMP_TEST_ROOT/data" \
  "$PYTHON_ENV/bin/pytest" -q
"$PYTHON_ENV/bin/python" -m compileall backend
WNACG_CONFIG_PATH="$TMP_CONFIG" WNACG_DB_PATH="$TMP_ALEMBIC_DB" "$PYTHON_ENV/bin/alembic" upgrade head
npm run lint -w frontend
npm run build:frontend
npm run build:extension
npm run package:extension
git diff --check
