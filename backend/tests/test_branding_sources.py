import pytest
from fastapi.testclient import TestClient

from backend.app.api.health import health_check
from backend.app.core.config import get_settings
from backend.app.core.schemas import BatchTaskCreateRequest, BatchTaskItem, TaskCreateRequest
from backend.app.crawler.sources import (
    get_source_adapter,
    list_source_names,
    normalize_jmcomic_input,
)
from backend.app.main import app


def test_jmcomic_normalization_accepts_numeric_id():
    assert normalize_jmcomic_input("123456") == "123456"


def test_jmcomic_normalization_accepts_album_url_without_network():
    assert normalize_jmcomic_input("https://jmcomic.me/album/123456") == "123456"


def test_jmcomic_input_parse_uses_jmcomic_url_rules():
    response = TestClient(app).post(
        "/api/inputs/parse",
        json={"text": "https://jmcomic.me/album/123456", "source": "jmcomic"},
    )
    assert response.status_code == 200
    item = response.json()["data"]["items"][0]
    assert item["manga_id"] == "123456"
    assert item["source"] == "jmcomic"


def test_jmcomic_normalization_rejects_unknown_url_shape():
    with pytest.raises(ValueError, match="JMComic"):
        normalize_jmcomic_input("https://jmcomic.me/search/123456")


def test_public_brand_is_comic_crawler():
    assert get_settings().app_name == "Comic Crawler"


@pytest.mark.asyncio
async def test_health_uses_public_brand():
    response = await health_check()
    assert response["data"]["service"] == "Comic Crawler"


def test_source_registry_exposes_wnacg_and_future_adapter_contract():
    assert "wnacg" in list_source_names()
    adapter = get_source_adapter("wnacg")
    assert adapter.name == "wnacg"
    assert hasattr(adapter, "fetch_manga")


def test_unknown_source_is_rejected_before_download():
    with pytest.raises(ValueError, match="Unsupported source"):
        get_source_adapter("unknown")


def test_jmcomic_registry_has_download_adapter():
    assert "jmcomic" in list_source_names()
    assert get_source_adapter("JMCOMIC").name == "jmcomic"


def test_jmcomic_source_can_be_registered_without_enabling_download():
    assert TaskCreateRequest(manga_id="123456", source="JMCOMIC").source == "jmcomic"


def test_task_payload_defaults_to_wnacg_and_rejects_unknown_source():
    assert TaskCreateRequest(manga_id="123").source == "wnacg"
    assert BatchTaskCreateRequest(items=[BatchTaskItem(manga_id="123")]).source == "wnacg"
    with pytest.raises(ValueError):
        TaskCreateRequest(manga_id="123", source="unknown")


def test_source_names_are_case_normalized():
    assert TaskCreateRequest(manga_id="123", source="WNACG").source == "wnacg"


def test_jmcomic_task_submission_can_be_pending():
    response = TestClient(app).post(
        "/api/tasks", json={"manga_id": "123", "source": "jmcomic", "start_immediately": False}
    )
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending"
