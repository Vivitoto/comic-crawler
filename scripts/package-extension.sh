#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/dist"
ZIP_PATH="$OUT_DIR/wnacg-downloader-extension.zip"

cd "$ROOT_DIR"
npm run build:extension
mkdir -p "$OUT_DIR"
rm -f "$ZIP_PATH"

if command -v zip >/dev/null 2>&1; then
  (
    cd "$ROOT_DIR/extension"
    zip -qr "$ZIP_PATH" manifest.json popup.html options.html dist
  )
else
PYTHON_BIN="${WNACG_PYTHON_ENV:-.venv312}/bin/python"
if ! "$PYTHON_BIN" -c 'import zipfile' >/dev/null 2>&1; then
  PYTHON_BIN=".venv312-new/bin/python"
fi
  "$ROOT_DIR/$PYTHON_BIN" - "$ROOT_DIR" "$ZIP_PATH" <<'PY'
from pathlib import Path
from sys import argv
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(argv[1])
extension = root / "extension"
with ZipFile(argv[2], "w", ZIP_DEFLATED) as archive:
    for relative in ("manifest.json", "popup.html", "options.html"):
        archive.write(extension / relative, relative)
    for path in (extension / "dist").rglob("*"):
        if path.is_file():
            archive.write(path, path.relative_to(extension).as_posix())
PY
fi

echo "Created $ZIP_PATH"
