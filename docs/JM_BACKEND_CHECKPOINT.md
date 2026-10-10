# JMComic backend checkpoint

## Implemented

- Pinned maintained `jmcomic==2.7.8` (MIT); installed only into project `.venv312` with `uv pip --python` (venv has no pip module).
- API single/batch submissions accept `source=jmcomic`. Input remains numeric; response `manga_id` is the opaque storage key `jmcomic-<id>`, with `source_item_id`, `source_url`, `source`. Existing WNACG numeric keys and paths are unchanged. Repository creation also qualifies JM keys idempotently. Do not strip the prefix when invoking library endpoints.
- Real JM API client fetches album and every chapter, enumerates library image entities, preserves title/authors/tags/description/chapter count and per-image chapter/index/scramble metadata. Metadata JSON is persisted in MangaPage.page_context; image decode metadata in MangaPicPage.page_name (existing text fields; no schema expansion needed).
- Runner dispatches JM metadata/image/refresh operations rather than WNACG HTML paths. Maintained library descrambles image strips before host validation, optional compression, original backup and atomic publication. GIF skips descrambling like upstream downloader.
- Shared progress, logs, completed/partial/failed status, image verification, ZIP, resume/reuse and library failed-image repair work with isolated JM keys. Repair derives source from durable storage identity rather than the old `library_retry_failed` pseudo-source.
- Source registry has only `wnacg` and `jmcomic`; test-only source strings corrected in fixtures. Legacy source migration now preserves JM tasks.
- Source-scoped configuration: file `jmcomic` object or env `WNACG_JMCOMIC__PROXY_URL`, `__TIMEOUT_SECONDS`, `__RETRY_COUNT`, `__REQUEST_DELAY_MS`. Defaults direct / 30s / 2 / 1200ms. Operations serialized and paced within the JM adapter; WNACG cookies/proxy config not reused. Upstream internal request retries remain owned by the pinned library.

## Research / protocol grounding

Inspected installed jmcomic implementation: JmApiAdaptTool, JmAlbumDetail/JmPhotoDetail/JmImageDetail, JmApiClient get_album_detail/get_photo_detail/download_image, JmImageResp.transfer_to and JmImageTool.decode_and_save. API shapes in tests come from that implementation, not speculative HTML. API handles metadata encryption internally. Chapters require scramble ID and ordered image list; images need descrambling before ordinary validation.

Compared https://github.com/hect0x7/JMComic-Crawler-Python (MIT, GitHub pushed_at 2026-10-08) with https://github.com/tonquer/JMComic-qt (LGPL-3.0, pushed_at 2026-10-07), inspecting latter's src/task/task_download.py. Both require album -> chapter -> scramble -> image sequence, and separate cache/retry stages. No LGPL implementation copied. Documentation: https://jmcomic.readthedocs.io . No credentials, login bypass, CAPTCHA handling or remote album requests added/performed. No published server rate limit was established; conservative adapter-level serialization/delay used.

Important upstream pitfall found and regression-tested: JmOption.construct deep-merges dicts, so `proxies={}` DOES NOT clear inherited global proxies. Explicit None clears the inherited mapping.

## Actual evidence

Sequential test execution only (conftest deletes shared test root). Full exact RED/GREEN output files: `backend/test-evidence/jm-01-{red,green}.log` through `jm-10-{red,green}.log`.

1. Registry cleanup: failed extra pseudo-source set -> pass.
2. API/storage isolation: failed HTTP 400 -> pass; same-ID WN/JM tasks distinct and batch dedupe source-specific.
3. Real library metadata: failed NotImplementedError -> pass, two chapters enumerated. Initial green attempt revealed /setting cookie initialization; fixture corrected to actual upstream response boundary.
4. Runner integration: failed WNACG fallback -> pass; real library image decode, database/files, ZIP CRC, same-ID WN metadata unchanged, file reuse, corruption/repair.
5. Refresh routing: failed partial after WNACG parser fallback -> pass; expired JM image refreshed from JM chapter.
6. Source config: failed hardcoded timeout -> pass.
7. Request pacing: failed missing gate -> pass.
8. Proxy isolation: failed inherited global proxy -> pass.
9. Repository identity: failed bare key -> pass.
10. Migration: failed rewrote JM source -> pass using real SQLite migration SQL.

Additional acceptance tests exercise existing behavior without production changes: pause/cancel prevents fetch, resume leads to partial on blocked transport, failed metadata logged durably, real curl-cffi/JM HTTP image transport against loopback ThreadingHTTPServer serving owned synthetic PNG. Loopback result is in `jm-http-local.log`; no real-site content downloaded.

Final executed commands/results:
- `.venv312/bin/pytest -q`: **177 passed, 1 warning in 8.67s** (`jm-final-pytest.log`). Includes 14 JM-specific tests.
- `.venv312/bin/ruff check backend`: **All checks passed!**
- `.venv312/bin/mypy backend/app`: **Success: no issues found in 43 source files**.
- `.venv312/bin/python -m compileall -q backend`: exit 0.

Only warning: existing Starlette/httpx TestClient deprecation, not a failing test. Initial full regression found a remaining compression-test pseudo-source; fixture corrected, not production whitelist expanded.

## Boundaries / remaining acceptance

No user-authorized real album ID was supplied: live JM availability/authentication/CDN compatibility is NOT claimed. Tests use real maintained client entity/decoder code with protocol-boundary fixtures, plus real localhost image HTTP. Parent owns Docker/frontend acceptance and should present the distinction. Install pyproject dependency in image. No frontend or scripts edited by backend subagent; no commits/push/global installs.

Existing WNACG adapter marker still delegates to the established WNACG runner; JM has no download stub. JM proxy config is available via environment/config file, not new web settings fields. Metadata fetch runs in a worker thread; pause is honored before persistence/publication and between runner stages, not an abort of an in-flight upstream call. Retry/restart re-fetches metadata and reuses verified local image files.
