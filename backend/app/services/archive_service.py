import zipfile
import zlib
from collections.abc import Iterable, Sequence
from pathlib import Path

from backend.app.core.files import atomic_output_path
from backend.app.core.paths import archive_name
from backend.app.crawler.images import SUPPORTED_EXTENSIONS, is_valid_image_file


class ArchivePathCollisionError(ValueError):
    """Raised when two manga would share the ID-free ZIP output path."""

    def __init__(self, title: str, manga_id: str, conflicting_ids: Sequence[str]) -> None:
        self.title = title
        self.manga_id = manga_id
        self.conflicting_ids = tuple(conflicting_ids)
        conflict_text = ", ".join(self.conflicting_ids)
        super().__init__(
            f"归档路径“{archive_name(title)}”已被其他漫画占用（ID: {conflict_text}），"
            "为避免覆盖，请修改其中一个标题后再打包"
        )


def ensure_archive_path_available(
    manga_id: str,
    title: str,
    manga_infos: Iterable[tuple[str, str]],
) -> None:
    name = archive_name(title)
    conflicting_ids = [
        other_id
        for other_id, other_title in manga_infos
        if other_id != manga_id and archive_name(other_title) == name
    ]
    if conflicting_ids:
        raise ArchivePathCollisionError(title, manga_id, conflicting_ids)


def is_complete_zip(target: Path, files: Sequence[Path]) -> bool:
    try:
        expected = {path.name: path.stat().st_size for path in files}
        if not expected or len(expected) != len(files):
            return False
        with zipfile.ZipFile(target) as archive:
            entries = archive.infolist()
            if len(entries) != len(expected) or any(
                entry.filename not in expected
                or entry.file_size != expected[entry.filename]
                for entry in entries
            ):
                return False
            if len({entry.filename for entry in entries}) != len(expected):
                return False
            for path in files:
                checksum = 0
                with path.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        checksum = zlib.crc32(block, checksum)
                if archive.getinfo(path.name).CRC != checksum:
                    return False
            return archive.testzip() is None
    except (OSError, zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error):
        return False


def create_zip(source: Path, target: Path, files: Sequence[Path] | None = None) -> None:
    selected = (
        list(files)
        if files is not None
        else [
            path
            for path in sorted(source.iterdir())
            if path.is_file()
            and not path.name.startswith(".")
            and path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
    )
    if not selected or any(not is_valid_image_file(path) for path in selected):
        raise ValueError("图片不完整或校验失败，无法打包")
    with atomic_output_path(target) as temporary:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in selected:
                archive.write(path, path.name)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP 校验失败")
