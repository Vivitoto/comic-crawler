from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import NoReturn, Protocol
from urllib.parse import urlparse

from backend.app.crawler.jm_source import JmcomicSourceAdapter, JmMetadata


class SourceName(StrEnum):
    """Sources with a registered adapter are valid task sources."""

    WNACG = "wnacg"
    JMCOMIC = "jmcomic"


class SourceAdapter(Protocol):
    """Contract implemented by a comic source without performing network I/O here."""

    @property
    def name(self) -> str: ...

    async def fetch_manga(self, manga_id: str) -> JmMetadata:
        """Fetch and return normalized manga metadata for a source."""
        raise NotImplementedError


@dataclass(frozen=True)
class WnacgSourceAdapter:
    """Placeholder for the existing WNACG crawler integration."""

    name: str = "wnacg"

    async def fetch_manga(self, manga_id: str) -> NoReturn:
        raise NotImplementedError("WNACG fetching remains owned by the existing task runner")


@dataclass(frozen=True)
class InternalSourceAdapter:
    """Adapter marker for local task flows that do not fetch a remote source."""

    name: str

    async def fetch_manga(self, manga_id: str) -> NoReturn:
        raise NotImplementedError(f"{self.name} does not support remote fetching")


_SOURCE_ADAPTERS: dict[str, SourceAdapter] = {
    "jmcomic": JmcomicSourceAdapter(),
    "wnacg": WnacgSourceAdapter(),
}


def manga_key(source: str, item_id: str) -> str:
    # Legacy WNACG keys remain unchanged; new sources cannot collide with them.
    return (
        f"jmcomic-{item_id}"
        if source == "jmcomic" and not item_id.startswith("jmcomic-")
        else item_id
    )


def source_identity(manga_id: str) -> dict[str, str]:
    source = "jmcomic" if manga_id.startswith("jmcomic-") else "wnacg"
    item_id = manga_id.removeprefix("jmcomic-") if source == "jmcomic" else manga_id
    url = (
        f"https://jmcomic.me/album/{item_id}"
        if source == "jmcomic"
        else f"https://www.wnacg.com/photos-index-aid-{item_id}.html"
    )
    return {"source": source, "source_item_id": item_id, "source_url": url}


def list_source_names() -> tuple[str, ...]:
    return tuple(_SOURCE_ADAPTERS)


def normalize_jmcomic_input(value: str) -> str:
    """Normalize a JMComic numeric ID or album URL without network access."""
    candidate = value.strip()
    if candidate.isdigit():
        return candidate
    parsed = urlparse(candidate)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "jmcomic.me",
        "www.jmcomic.me",
    }:
        raise ValueError("JMComic input must be a numeric ID or jmcomic.me album URL")
    match = re.fullmatch(r"/album/(\d+)/?", parsed.path)
    if match is None:
        raise ValueError("JMComic input must be a numeric ID or jmcomic.me album URL")
    return match.group(1)


def get_source_adapter(source: str) -> SourceAdapter:
    try:
        return _SOURCE_ADAPTERS[source.lower()]
    except (KeyError, AttributeError):
        raise ValueError(f"Unsupported source: {source}") from None


def validate_source(source: str) -> str:
    """Validate and normalize a source name before a task is persisted."""
    try:
        normalized = SourceName(source.lower()).value
    except (AttributeError, ValueError):
        raise ValueError(f"Unsupported source: {source}") from None
    get_source_adapter(normalized)
    return normalized
