import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend.app.core.paths import legacy_zip_paths, manga_dir, zip_path


@contextmanager
def atomic_output_path(target: Path) -> Iterator[Path]:
    """Keep the old file until a same-directory temporary file is fully written."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        yield temporary
        with temporary.open("rb") as stream:
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_bytes(target: Path, data: bytes) -> None:
    with atomic_output_path(target) as temporary:
        temporary.write_bytes(data)


def remove_download_files(base: Path, manga_id: str, title: str) -> None:
    """Remove only this manga's image directory and known archive files."""
    image_dir = manga_dir(base, manga_id, title)
    archive = zip_path(base, manga_id, title)
    legacy_archives = legacy_zip_paths(base, manga_id, title)

    if image_dir.is_symlink():
        image_dir.unlink()
    elif image_dir.is_dir():
        shutil.rmtree(image_dir)
    elif image_dir.is_file():
        image_dir.unlink()

    if archive.is_symlink() or archive.is_file():
        archive.unlink()
        parent = archive.parent
        if parent.is_dir() and not parent.is_symlink():
            try:
                parent.rmdir()
            except OSError:
                pass

    for legacy_archive in legacy_archives:
        if legacy_archive.is_symlink() or legacy_archive.is_file():
            legacy_archive.unlink()
