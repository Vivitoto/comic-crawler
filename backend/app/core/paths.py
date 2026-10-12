import re
from pathlib import Path

ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]')


class UnsafePathError(ValueError):
    """Raised when a derived download path would leave the configured root."""


def safe_filename(value: str, fallback: str = "untitled") -> str:
    cleaned = ILLEGAL_FILENAME_CHARS.sub("_", value).strip()
    if cleaned and cleaned not in {".", ".."}:
        return cleaned
    safe_fallback = ILLEGAL_FILENAME_CHARS.sub("_", fallback).strip()
    return safe_fallback if safe_fallback and safe_fallback not in {".", ".."} else "untitled"


def archive_name(title: str) -> str:
    """Return the ID-free directory/file stem used for ZIP output."""
    return safe_filename(title, "untitled")


def _within_root(base: Path, candidate: Path) -> Path:
    root = base.expanduser().resolve()
    try:
        candidate.resolve().relative_to(root)
    except ValueError as exc:
        raise UnsafePathError(
            f"派生路径超出下载目录：{candidate}（根目录：{base}）"
        ) from exc
    return candidate


def manga_dir(base: Path, manga_id: str, title: str) -> Path:
    safe_id = safe_filename(manga_id, "unknown-id")
    return _within_root(
        base,
        base / "Manga" / f"[{safe_id}] {safe_filename(title, safe_id)}",
    )


def original_dir(base: Path, manga_id: str, title: str) -> Path:
    safe_id = safe_filename(manga_id, "unknown-id")
    return _within_root(
        base,
        base / "Original" / f"[{safe_id}] {safe_filename(title, safe_id)}",
    )


def zip_path(base: Path, manga_id: str, title: str) -> Path:
    del manga_id
    name = archive_name(title)
    return _within_root(base, base / name / f"{name}.zip")


def legacy_zip_paths(base: Path, manga_id: str, title: str) -> tuple[Path, Path]:
    """Return the two pre-title-folder archive locations, safely normalized."""
    safe_id = safe_filename(manga_id, "unknown-id")
    legacy_title = safe_filename(title, safe_id)
    return (
        _within_root(base, base / "Zip" / f"[{safe_id}] {legacy_title}.zip"),
        _within_root(base, base / f"[{safe_id}] {legacy_title}.zip"),
    )
