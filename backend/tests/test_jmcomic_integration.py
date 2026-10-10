from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jmcomic  # type: ignore[import-untyped]
import pytest
from fastapi.testclient import TestClient

from backend.app.crawler.sources import list_source_names
from backend.app.main import app

REAL_JM_GET_IMAGE = jmcomic.JmApiClient.get_jm_image


def test_source_migration_preserves_jm_tasks(monkeypatch):
    import importlib.util
    import sqlite3
    from pathlib import Path

    path = Path(__file__).parents[1] / "alembic/versions/20261010_0003_task_source.py"
    spec = importlib.util.spec_from_file_location("source_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE download_task (source TEXT)")
    db.executemany("INSERT INTO download_task VALUES (?)", [("jmcomic",), ("web",), (None,)])
    monkeypatch.setattr(module.op, "execute", db.execute)
    module.upgrade()
    assert db.execute("SELECT source FROM download_task").fetchall() == [
        ("jmcomic",),
        ("wnacg",),
        ("wnacg",),
    ]
    db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("control", ["paused", "cancelled"])
async def test_jm_control_prevents_download(jm_protocol, control):
    from backend.app.core.schemas import TaskCreateRequest
    from backend.app.services.task_runner import TaskRunner
    from backend.app.services.task_service import task_service

    item_id = "991081" if control == "paused" else "991082"
    task = await task_service.create(TaskCreateRequest(manga_id=item_id, source="jmcomic"))
    await task_service.transition(task["task_id"], control)
    await TaskRunner().run(task["task_id"])
    assert (await task_service.get(task["task_id"]))["status"] == control
    assert jm_protocol == []
    if control == "paused":
        await task_service.transition(task["task_id"], "queued")
        await TaskRunner().run(task["task_id"])
        assert (await task_service.get(task["task_id"]))["status"] == "partial"
        assert len(jm_protocol) == 3


@pytest.mark.asyncio
async def test_jm_metadata_error_is_durable_and_logged(monkeypatch):
    from backend.app.core.schemas import TaskCreateRequest
    from backend.app.db.database import SessionLocal
    from backend.app.db.repository import LogRepository
    from backend.app.services.task_runner import TaskRunner
    from backend.app.services.task_service import task_service

    def denied(*args, **kwargs):
        raise RuntimeError("JM upstream unavailable")

    monkeypatch.setattr(jmcomic.JmApiClient, "get_album_detail", denied)
    task = await task_service.create(TaskCreateRequest(manga_id="991083", source="jmcomic"))
    await TaskRunner().run(task["task_id"])
    result = await task_service.get(task["task_id"])
    assert result["status"] == "failed"
    async with SessionLocal() as session:
        assert await LogRepository(session).exists("task_failed", task_id=task["task_id"])


@pytest.mark.asyncio
async def test_real_jm_http_transport_decodes_local_owned_image(jm_protocol, monkeypatch):
    import io
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from PIL import Image

    from backend.app.crawler.jm_source import download_image

    buffer = io.BytesIO()
    Image.new("RGB", (20, 240), "blue").save(buffer, "PNG")
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(buffer.getvalue())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(jmcomic.JmApiClient, "get_jm_image", REAL_JM_GET_IMAGE)
    try:
        url = f"http://127.0.0.1:{server.server_port}/media/photos/991011/00001.png"
        data = await download_image(url, 220980)
        with Image.open(io.BytesIO(data)) as image:
            assert image.size == (20, 240)
            assert image.getpixel((0, 0)) == (0, 0, 255)
        assert seen == ["/media/photos/991011/00001.png"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def jm_protocol(monkeypatch):
    # Shapes taken from jmcomic 2.7.8 JmApiAdaptTool, not an invented HTML parser.
    from backend.app.core.config import get_settings

    monkeypatch.setattr(get_settings().jmcomic, "request_delay_ms", 0)
    calls = []

    def req_api(self, url, **kwargs):
        if url == "/setting":
            return SimpleNamespace(
                model_data=SimpleNamespace(jm3_version="0"), resp=SimpleNamespace(cookies={})
            )
        calls.append(url)
        item_id = parse_qs(urlparse(url).query)["id"][0]
        if url.startswith(self.API_ALBUM):
            data = dict(
                id=item_id,
                name="Local authorized fixture",
                likes="0",
                tags=["test"],
                works=[],
                actors=[],
                related_list=[],
                description="fixture",
                author=["Tester"],
                total_views="0",
                comment_total="0",
                total_photos="2",
                addtime="1700000000",
                is_favorite=False,
                liked=False,
                series=[
                    dict(id="991011", sort="1", name="Chapter One"),
                    dict(id="991012", sort="2", name="Chapter Two"),
                ],
            )
        else:
            data = dict(
                id=item_id,
                name="Chapter",
                series_id="991010",
                tags="test",
                images=["00001.png"],
                series=[],
            )
        return SimpleNamespace(encoded_data=True, res_data=data)

    monkeypatch.setattr(jmcomic.JmApiClient, "req_api", req_api)
    monkeypatch.setattr(jmcomic.JmApiClient, "get_scramble_id", lambda *a: "220980")
    return calls


@pytest.mark.asyncio
async def test_jm_adapter_uses_real_library_to_enumerate_all_chapters(jm_protocol):
    from backend.app.crawler.sources import get_source_adapter

    metadata = await get_source_adapter("jmcomic").fetch_manga("991010")
    assert metadata.title == "Local authorized fixture"
    assert metadata.authors == ["Tester"]
    assert len(metadata.pages) == 2
    assert [p.chapter_id for p in metadata.pages] == ["991011", "991012"]
    assert all(p.scramble_id == 220980 for p in metadata.pages)
    assert len(jm_protocol) == 3


def test_jm_submission_isolated_from_same_wnacg_id():
    client = TestClient(app)
    payload = {"manga_id": "991001", "start_immediately": False}
    wn = client.post("/api/tasks", json={**payload, "source": "wnacg"}).json()["data"]
    response = client.post("/api/tasks", json={**payload, "source": "jmcomic"})
    assert response.status_code == 200
    jm = response.json()["data"]
    assert jm["task_id"] != wn["task_id"]
    assert jm["manga_id"] == "jmcomic-991001"
    assert jm["source_item_id"] == "991001"
    assert jm["source_url"] == "https://jmcomic.me/album/991001"
    batch = client.post(
        "/api/tasks/batch",
        json={
            "items": [{"manga_id": "991001"}, {"manga_id": "991002"}],
            "source": "jmcomic",
            "start_immediately": False,
        },
    ).json()["data"]
    assert len(batch["skipped"]) == 1
    assert batch["created"][0]["manga_id"] == "jmcomic-991002"


def test_registry_contains_only_real_sources():
    assert set(list_source_names()) == {"wnacg", "jmcomic"}


@pytest.mark.asyncio
async def test_repository_qualifies_jm_identity_even_without_api():
    from backend.app.db.database import SessionLocal
    from backend.app.db.repository import TaskRepository

    async with SessionLocal() as session:
        task = await TaskRepository(session).create("991090", "jmcomic", "pending")
        assert task.manga_id == "jmcomic-991090"
        qualified = await TaskRepository(session).create("jmcomic-991091", "jmcomic", "pending")
        assert qualified.manga_id == "jmcomic-991091"


def test_jm_client_never_inherits_global_proxy(jm_protocol, monkeypatch):
    from backend.app.crawler.jm_source import new_client

    monkeypatch.setattr(
        jmcomic.JmModuleConfig, "DEFAULT_PROXIES", {"https": "http://unexpected.invalid:9000"}
    )
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("COMIC_CRAWLER_PROXY", raising=False)
    client = new_client()
    assert not client.get_meta_data("proxies")


def test_jmcomic_uses_http_proxy_environment_when_no_source_proxy(monkeypatch):
    from backend.app.core.config import Settings
    from backend.app.crawler import jm_source

    settings = Settings()
    monkeypatch.setattr(jm_source, "get_settings", lambda: settings, raising=False)
    monkeypatch.setenv("COMIC_CRAWLER_PROXY", "http://env-proxy:7890")
    captured = {}

    class EnvOption:
        def new_jm_client(self):
            return self

    def capture_env(data):
        captured.update(data)
        return EnvOption()

    monkeypatch.setattr(jmcomic.JmOption, "construct", capture_env)
    jm_source.new_client()
    assert captured["client"]["postman"]["meta_data"]["proxies"]["https"] == "http://env-proxy:7890"


    monkeypatch.delenv("COMIC_CRAWLER_PROXY", raising=False)

    from backend.app.core.config import ProxySettings, Settings
    from backend.app.crawler import jm_source

    settings = Settings(proxy=ProxySettings(is_proxy=True, address="proxy.local", port=7890))
    monkeypatch.setattr(jm_source, "get_settings", lambda: settings, raising=False)
    captured = {}

    class SharedOption:
        def new_jm_client(self):
            return self

    def capture_construct(data):
        captured.update(data)
        return SharedOption()

    monkeypatch.setattr(jmcomic.JmOption, "construct", capture_construct)
    jm_source.new_client()
    metadata = captured["client"]["postman"]["meta_data"]
    assert metadata["proxies"]["https"] == "http://proxy.local:7890"


def test_jm_client_configuration_is_source_scoped(monkeypatch):
    from backend.app.core.config import Settings
    from backend.app.crawler import jm_source

    settings = Settings(
        jmcomic={
            "proxy_url": "http://127.0.0.1:7891",
            "timeout_seconds": 12,
            "retry_count": 1,
            "request_delay_ms": 0,
        }
    )
    monkeypatch.setattr(jm_source, "get_settings", lambda: settings, raising=False)
    captured = {}

    class ScopedOption:
        def new_jm_client(self):
            return self

    def capture_scoped(data):
        captured.update(data)
        return ScopedOption()

    monkeypatch.setattr(jmcomic.JmOption, "construct", capture_scoped)
    jm_source.new_client()
    metadata = captured["client"]["postman"]["meta_data"]
    assert metadata["timeout"] == 12
    assert metadata["proxies"]["https"] == "http://127.0.0.1:7891"
    assert captured["client"]["retry_times"] == 1


@pytest.mark.asyncio
async def test_jm_runner_downloads_decodes_verifies_and_zips(jm_protocol, monkeypatch):
    import io
    import zipfile
    from pathlib import Path

    from PIL import Image

    from backend.app.core.schemas import TaskCreateRequest
    from backend.app.db.database import SessionLocal
    from backend.app.db.repository import MangaRepository
    from backend.app.services.library_service import library_service
    from backend.app.services.task_runner import TaskRunner
    from backend.app.services.task_service import task_service

    # Owned synthetic pixels only. Real JmImageResp decoding is exercised.
    image = Image.new("RGB", (20, 240))
    for y in range(240):
        for x in range(20):
            image.putpixel((x, y), (y, 0, 0))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    downloads = []

    def get_image(self, url):
        downloads.append(url)
        return jmcomic.JmImageResp(
            SimpleNamespace(url=url, content=buffer.getvalue(), status_code=200, text="")
        )

    monkeypatch.setattr(jmcomic.JmApiClient, "get_jm_image", get_image)
    async with SessionLocal() as session:
        await MangaRepository(session).upsert_info("991010", "WN unchanged", "", 1)
    task = await task_service.create(TaskCreateRequest(manga_id="991010", source="jmcomic"))
    await TaskRunner().run(task["task_id"])
    result = await task_service.get(task["task_id"])
    assert result["status"] == "completed", result["last_error"]
    summary = await library_service.verify("jmcomic-991010")
    assert summary["source"] == "jmcomic"
    assert summary["source_item_id"] == "991010"
    assert summary["valid_files"] == summary["total_files"] == 2
    assert summary["zip_exists"]
    with zipfile.ZipFile(summary["zip_path"]) as archive:
        assert len(archive.namelist()) == 2
        assert archive.testzip() is None
    for file in summary["files"]:
        with Image.open(file["file_path"]) as decoded:
            assert decoded.getpixel((0, 0)) != image.getpixel((0, 0))
    async with SessionLocal() as session:
        assert (await MangaRepository(session).get_info("991010")).title == "WN unchanged"
    await task_service.retry(task["task_id"], "task")
    await TaskRunner().run(task["task_id"])
    assert len(downloads) == 2  # valid files reused on rerun
    Path(summary["files"][0]["file_path"]).write_bytes(b"corrupt")
    retry = await library_service.create_failed_retry_task("jmcomic-991010")
    assert retry["task"]["source"] == "jmcomic"
    await TaskRunner().run_failed_images(retry["task"]["task_id"])
    assert (await task_service.get(retry["task"]["task_id"]))["status"] == "completed"
    assert len(downloads) == 3


@pytest.mark.asyncio
async def test_jm_retry_refreshes_chapter_without_wnacg(jm_protocol, monkeypatch):
    import io

    from PIL import Image

    from backend.app.core.schemas import TaskCreateRequest
    from backend.app.db.database import SessionLocal
    from backend.app.db.repository import MangaRepository, TaskRepository
    from backend.app.services.task_runner import TaskRunner
    from backend.app.services.task_service import task_service

    task = await task_service.create(TaskCreateRequest(manga_id="991020", source="jmcomic"))
    runner = TaskRunner()
    await runner._fetch_jm(task["task_id"], task["manga_id"])
    async with SessionLocal() as session:
        pages = await MangaRepository(session).list_pic_pages(task["manga_id"])
        page = pages[0]
        await MangaRepository(session).upsert_pic_page(
            task["manga_id"],
            1,
            page.page_url,
            page.page_name,
            page.pic_num,
            "https://expired.example/media/photos/991011/00001.png",
        )
    attempts = []
    buffer = io.BytesIO()
    Image.new("RGB", (20, 240), "red").save(buffer, "PNG")

    def get_image(self, url):
        attempts.append(url)
        return jmcomic.JmImageResp(
            SimpleNamespace(
                url=url,
                content=b"denied" if "expired" in url else buffer.getvalue(),
                status_code=403 if "expired" in url else 200,
                text="denied",
            )
        )

    monkeypatch.setattr(jmcomic.JmApiClient, "get_jm_image", get_image)
    await runner.run_failed_images(task["task_id"])
    async with SessionLocal() as session:
        updated = await TaskRepository(session).get(task["task_id"])
        assert updated.status == "completed", updated.last_error
    assert len(attempts) == 3


def test_jm_requests_are_serialized_and_paced(monkeypatch):
    from backend.app.core.config import get_settings
    from backend.app.crawler import jm_source

    monkeypatch.setattr(get_settings().jmcomic, "request_delay_ms", 50)
    assert hasattr(jm_source, "request_gate")
    import time

    started = time.monotonic()
    with jm_source.request_gate():
        pass
    with jm_source.request_gate():
        pass
    assert time.monotonic() - started >= 0.05
