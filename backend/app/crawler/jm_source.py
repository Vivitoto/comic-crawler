"""JM protocol is owned by the maintained MIT-licensed jmcomic client."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from jmcomic import JmOption  # type: ignore[import-untyped]

from backend.app.core.config import get_settings


@dataclass(frozen=True)
class JmPage:
    chapter_id: str
    chapter_index: int
    image_index: int
    url: str
    scramble_id: int


@dataclass(frozen=True)
class JmMetadata:
    title: str
    authors: list[str]
    tags: list[str]
    description: str
    pages: list[JmPage]
    chapter_count: int


_request_lock = threading.RLock()
_last_request_end = 0.0


@contextmanager
def request_gate():
    global _last_request_end
    with _request_lock:
        delay = get_settings().jmcomic.request_delay_ms / 1000
        time.sleep(max(0, delay - (time.monotonic() - _last_request_end)))
        try:
            yield
        finally:
            _last_request_end = time.monotonic()


def new_client():
    settings = get_settings()
    config = settings.jmcomic
    proxy_url = config.proxy_url or os.getenv("COMIC_CRAWLER_PROXY")
    if not proxy_url and settings.proxy.is_proxy:
        proxy_url = f"http://{settings.proxy.address}:{settings.proxy.port}"
    return JmOption.construct(
        {
            "log": False,
            "client": {
                "impl": "api",
                "retry_times": config.retry_count,
                "postman": {
                    "type": "curl_cffi",
                    "meta_data": {
                        "proxies": (
                            {"http": proxy_url, "https": proxy_url}
                            if proxy_url
                            else None
                        ),
                        "timeout": config.timeout_seconds,
                        "impersonate": "chrome",
                        "cookies": {},
                    },
                },
            },
        }
    ).new_jm_client()


def _fetch_manga(item_id: str) -> JmMetadata:
    with request_gate():
        client = new_client()
        album = client.get_album_detail(item_id)
    pages = []
    for chapter_index, chapter in enumerate(album, 1):
        with request_gate():
            photo = client.get_photo_detail(chapter.photo_id, fetch_album=False)
        for image_index, image in enumerate(photo, 1):
            pages.append(
                JmPage(
                    str(photo.photo_id),
                    chapter_index,
                    image_index,
                    image.download_url,
                    int(image.scramble_id),
                )
            )
    if not pages:
        raise RuntimeError("JMComic album contains no images")
    return JmMetadata(album.name, album.authors, album.tags, album.description, pages, len(album))


async def refresh_page(page: JmPage) -> JmPage:
    def fetch() -> JmPage:
        with request_gate():
            photo = new_client().get_photo_detail(page.chapter_id, fetch_album=False)
        image = photo[page.image_index - 1]
        return JmPage(
            page.chapter_id,
            page.chapter_index,
            page.image_index,
            image.download_url,
            int(image.scramble_id),
        )

    return await asyncio.to_thread(fetch)


async def download_image(url: str, scramble_id: int) -> bytes:
    def fetch() -> bytes:
        # Library decoding writes only a private temporary file. The host owns atomic publication.
        with request_gate(), TemporaryDirectory(prefix="jm-image-") as directory:
            path = Path(directory) / (
                "image.gif" if url.split("?")[0].endswith(".gif") else "image.png"
            )
            new_client().download_image(
                url, str(path), scramble_id, decode_image=path.suffix != ".gif"
            )
            return path.read_bytes()

    return await asyncio.to_thread(fetch)


@dataclass(frozen=True)
class JmcomicSourceAdapter:
    name: str = "jmcomic"

    async def fetch_manga(self, manga_id: str) -> JmMetadata:
        return await asyncio.to_thread(_fetch_manga, manga_id)
