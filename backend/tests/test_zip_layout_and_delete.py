import asyncio
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.core.paths import legacy_zip_paths, manga_dir, zip_path
from backend.app.db.database import SessionLocal
from backend.app.db.repository import FileRepository, MangaRepository, TaskRepository
from backend.app.main import app
from backend.app.services import task_service as task_service_module
from backend.app.services.archive_service import ArchivePathCollisionError
from backend.app.services.library_service import library_service
from backend.app.services.log_service import log_service
from backend.app.services.task_runner import TaskRunner
from backend.app.services.task_service import task_service
from backend.tests.image_fixtures import image_bytes


def test_zip_is_written_in_title_folder():
    target = zip_path(Path("/data"), "123", "My Manga")
    assert target == Path("/data") / "My Manga" / "My Manga.zip"
    assert "Zip" not in target.parts
    assert "[123]" not in target.name


@pytest.mark.asyncio
async def test_completed_zip_lands_at_download_root(monkeypatch):
    monkeypatch.setattr(get_settings(), "is_zip", True)
    manga_id = "ziproot001"
    title = "Root Zip"
    base = Path(get_settings().download_path)
    directory = base / "Manga" / f"[{manga_id}] {title}"
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "0001_1.jpg"
    image.write_bytes(image_bytes())
    async with SessionLocal() as session:
        repo = MangaRepository(session)
        await repo.upsert_info(manga_id, title, "", 1, "partial")
        await repo.update_info_status(manga_id, "partial", pic_count=1)
        await repo.upsert_pic_page(
            manga_id, 1, "https://example.test/page/1",
            f"id_{manga_id}_pic_1", "1", "https://example.test/1.jpg", status="resolved",
        )
        await FileRepository(session).upsert_file(
            manga_id, 1, str(image), image.name, image.stat().st_size, "valid",
        )

    result = await library_service.zip(manga_id)
    archive = zip_path(base, manga_id, title)
    assert result is not None
    assert archive == base / title / f"{title}.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as zipped:
        assert image.name in zipped.namelist()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    ["pending", "queued", "running", "paused", "cancelled", "partial", "failed", "completed"],
)
async def test_delete_task_isolates_selected_task_for_all_statuses(status):
    suffix = uuid4().hex
    manga_id = f"delete{suffix}"
    other_manga_id = f"other{suffix}"
    title = f"Delete Isolation {suffix}"
    base = Path(get_settings().download_path)
    directory = manga_dir(base, manga_id, title)
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "keep.jpg"
    marker.write_bytes(image_bytes())
    archive = zip_path(base, manga_id, title)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"keep archive")

    async with SessionLocal() as session:
        manga_repo = MangaRepository(session)
        await manga_repo.upsert_info(manga_id, title, "", 1, "partial")
        await manga_repo.upsert_page(manga_id, 1, "https://example.test/page", "context")
        await manga_repo.upsert_pic_page(
            manga_id, 1, "https://example.test/pic-page", "pic", "1",
            "https://example.test/image.jpg",
        )
        await FileRepository(session).upsert_file(
            manga_id, 1, str(marker), marker.name, marker.stat().st_size, "valid",
        )
        await manga_repo.upsert_info(other_manga_id, f"Other {suffix}", "", 1, "partial")
        repo = TaskRepository(session)
        selected = await repo.create(manga_id, "wnacg", status)
        same_manga = await repo.create(manga_id, "wnacg", "failed")
        other_manga = await repo.create(other_manga_id, "wnacg", "failed")

    await log_service.write("error", "selected-task-log", "selected", manga_id, selected.id)
    await log_service.write("error", "same-manga-log", "same manga", manga_id, same_manga.id)
    await log_service.write("error", "other-task-log", "other", other_manga_id, other_manga.id)

    response = TestClient(app).delete(f"/api/tasks/{selected.id}")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "task_id": selected.id,
        "manga_id": manga_id,
        "deleted": True,
        "files_deleted": False,
    }
    async with SessionLocal() as session:
        assert await TaskRepository(session).get(selected.id) is None
        assert await TaskRepository(session).get(same_manga.id) is not None
        assert await TaskRepository(session).get(other_manga.id) is not None
        assert await MangaRepository(session).get_info(manga_id) is not None
        assert await MangaRepository(session).get_info(other_manga_id) is not None
    assert marker.exists()
    assert archive.exists()
    assert (await log_service.list(task_id=selected.id))["total"] == 0
    assert (await log_service.list(task_id=same_manga.id))["total"] == 1
    assert (await log_service.list(task_id=other_manga.id))["total"] == 1


@pytest.mark.asyncio
async def test_delete_task_can_remove_owned_files_without_removing_manga():
    suffix = uuid4().hex
    manga_id = f"deletefiles{suffix}"
    title = f"Delete Files {suffix}"
    base = Path(get_settings().download_path)
    directory = manga_dir(base, manga_id, title)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "0001.jpg").write_bytes(image_bytes())
    archive = zip_path(base, manga_id, title)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"zip")
    unrelated = archive.parent / "unrelated.txt"
    unrelated.write_text("preserve", encoding="utf-8")

    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info(manga_id, title, "", 1, "completed")
        task = await TaskRepository(session).create(manga_id, "wnacg", "completed")

    response = TestClient(app).delete(f"/api/tasks/{task.id}?delete_files=true")

    assert response.status_code == 200
    assert response.json()["data"]["files_deleted"] is True
    async with SessionLocal() as session:
        assert await TaskRepository(session).get(task.id) is None
        assert await MangaRepository(session).get_info(manga_id) is not None
    assert not directory.exists()
    assert not archive.exists()
    assert archive.parent.exists()
    assert unrelated.read_text(encoding="utf-8") == "preserve"


@pytest.mark.asyncio
async def test_delete_running_task_waits_for_worker_before_removing_files(monkeypatch):
    suffix = uuid4().hex
    manga_id = f"active{suffix}"
    title = f"Active Delete {suffix}"
    base = Path(get_settings().download_path)
    directory = manga_dir(base, manga_id, title)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "partial.jpg").write_bytes(image_bytes())
    archive = zip_path(base, manga_id, title)
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"zip")
    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info(manga_id, title, "", 1, "ready")
        task = await TaskRepository(session).create(manga_id, "wnacg", "queued")

    runner = TaskRunner()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_source(_task_id: str):
        return SimpleNamespace(name="wnacg")

    async def blocked_fetch(_task_id: str, _manga_id: str) -> dict:
        started.set()
        await release.wait()
        return {"title": title, "cover_url": "", "page_count": 1}

    monkeypatch.setattr(task_service_module, "task_runner", runner)
    monkeypatch.setattr(runner, "_source_adapter", fake_source)
    monkeypatch.setattr(runner, "_fetch_info", blocked_fetch)
    worker = asyncio.create_task(runner.run(task.id))
    await started.wait()

    deletion = asyncio.create_task(task_service.delete(task.id, delete_files=True))
    await asyncio.sleep(0)
    assert not deletion.done()
    assert directory.exists()
    assert archive.exists()

    release.set()
    result = await deletion
    await worker

    assert result["files_deleted"] is True
    async with SessionLocal() as session:
        assert await TaskRepository(session).get(task.id) is None
        assert await MangaRepository(session).get_info(manga_id) is not None
    assert not directory.exists()
    assert not archive.exists()


@pytest.mark.asyncio
async def test_delete_files_handles_unsafe_title_and_legacy_archives():
    suffix = uuid4().hex
    manga_id = f"unsafe{suffix}"
    title = "../unsafe/title/.."
    base = Path(get_settings().download_path)
    target = zip_path(base, manga_id, title)
    manga = manga_dir(base, manga_id, title)
    manga.mkdir(parents=True, exist_ok=True)
    (manga / "image.jpg").write_bytes(image_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"zip")
    legacy_paths = legacy_zip_paths(base, manga_id, title)
    for legacy in legacy_paths:
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(b"legacy")
    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info(manga_id, title, "", 1, "completed")
        task = await TaskRepository(session).create(manga_id, "wnacg", "completed")

    assert target.resolve().is_relative_to(base.resolve())
    response = TestClient(app).delete(f"/api/tasks/{task.id}?delete_files=true")

    assert response.status_code == 200
    assert not manga.exists()
    assert not target.exists()
    assert all(not legacy.exists() for legacy in legacy_paths)


@pytest.mark.asyncio
async def test_manual_zip_rejects_same_title_other_manga():
    suffix = uuid4().hex
    title = f"Collision {suffix}"
    first = await _seed_complete_item(f"first{suffix}", title)
    second = await _seed_complete_item(f"second{suffix}", title)

    with pytest.raises(ArchivePathCollisionError, match="归档路径"):
        await library_service.zip(second)
    assert not zip_path(Path(get_settings().download_path), second, title).exists()
    assert zip_path(Path(get_settings().download_path), first, title).exists() is False


@pytest.mark.asyncio
async def test_automatic_zip_rejects_collision_without_overwriting_archive():
    suffix = uuid4().hex
    title = f"Automatic Collision {suffix}"
    first = f"firstauto{suffix}"
    second = f"secondauto{suffix}"
    await _seed_complete_item(first, title)
    await _seed_complete_item(second, title)
    target = zip_path(Path(get_settings().download_path), first, title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"owned by another manga")

    with pytest.raises(ArchivePathCollisionError, match="归档路径"):
        await TaskRunner()._zip_manga(second)
    assert target.read_bytes() == b"owned by another manga"


@pytest.mark.asyncio
async def test_task_delete_rejects_archive_collision_without_deleting_task():
    suffix = uuid4().hex
    title = f"Delete Collision {suffix}"
    first = f"firstdelete{suffix}"
    second = f"seconddelete{suffix}"
    await _seed_complete_item(first, title)
    await _seed_complete_item(second, title)
    target = zip_path(Path(get_settings().download_path), first, title)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"preserve collision archive")
    async with SessionLocal() as session:
        task = await TaskRepository(session).create(first, "wnacg", "completed")

    with pytest.raises(ArchivePathCollisionError, match="归档路径"):
        await task_service.delete(task.id, delete_files=True)
    async with SessionLocal() as session:
        assert await TaskRepository(session).get(task.id) is not None
    assert target.read_bytes() == b"preserve collision archive"


@pytest.mark.asyncio
async def test_delete_library_can_keep_local_files():
    manga_id = "keeplib001"
    title = "Keep Library"
    base = Path(get_settings().download_path)
    directory = base / "Manga" / f"[{manga_id}] {title}"
    archive = base / title / f"{title}.zip"
    directory.mkdir(parents=True, exist_ok=True)
    archive.parent.mkdir(parents=True, exist_ok=True)
    (directory / "0001_1.jpg").write_bytes(image_bytes())
    archive.write_bytes(b"zip")
    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info(manga_id, title, "", 1, "completed")

    client = TestClient(app)
    response = client.delete(f"/api/library/{manga_id}")
    assert response.status_code == 200
    assert response.json()["data"]["files_deleted"] is False

    async with SessionLocal() as session:
        assert await MangaRepository(session).get_info(manga_id) is None
    assert directory.exists()
    assert archive.exists()


@pytest.mark.asyncio
async def test_delete_failed_library_item():
    manga_id = "failedlib001"
    title = "Failed Library"
    base = Path(get_settings().download_path)
    directory = base / "Manga" / f"[{manga_id}] {title}"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "broken.jpg").write_bytes(b"not-an-image")
    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info(manga_id, title, "", 1, "failed")

    client = TestClient(app)
    response = client.delete(f"/api/library/{manga_id}?delete_files=true")
    assert response.status_code == 200
    assert response.json()["data"]["manga_id"] == manga_id

    async with SessionLocal() as session:
        assert await MangaRepository(session).get_info(manga_id) is None
    assert not directory.exists()


async def _seed_complete_item(manga_id: str, title: str) -> str:
    base = Path(get_settings().download_path)
    directory = manga_dir(base, manga_id, title)
    directory.mkdir(parents=True, exist_ok=True)
    image = directory / "0001_1.jpg"
    image.write_bytes(image_bytes())
    async with SessionLocal() as session:
        repo = MangaRepository(session)
        await repo.upsert_info(manga_id, title, "", 1, "partial")
        await repo.update_info_status(manga_id, "partial", pic_count=1)
        await repo.upsert_pic_page(
            manga_id, 1, "https://example.test/page/1",
            f"id_{manga_id}_pic_1", "1", "https://example.test/1.jpg",
        )
        await FileRepository(session).upsert_file(
            manga_id, 1, str(image), image.name, image.stat().st_size, "valid",
        )
    return manga_id
