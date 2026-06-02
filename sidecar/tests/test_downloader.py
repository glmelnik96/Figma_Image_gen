"""Тесты downloader (с моком httpx)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.services.downloader import download_urls, DownloadError


async def test_download_single_url(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"hello-png-bytes", headers={"Content-Type": "image/png"})

    transport = httpx.MockTransport(handler)
    out_dir = tmp_path / "01HX"
    paths = await download_urls(
        urls=["https://example.com/img.png"],
        out_dir=out_dir,
        transport=transport,
    )
    assert len(paths) == 1
    assert paths[0].exists()
    assert paths[0].read_bytes() == b"hello-png-bytes"
    assert paths[0].parent == out_dir


async def test_download_multiple_urls(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if "img1" in str(request.url):
            return httpx.Response(200, content=b"A", headers={"Content-Type": "image/png"})
        return httpx.Response(200, content=b"B", headers={"Content-Type": "image/png"})

    transport = httpx.MockTransport(handler)
    paths = await download_urls(
        urls=["https://x/img1.png", "https://x/img2.png"],
        out_dir=tmp_path / "01HX",
        transport=transport,
    )
    assert len(paths) == 2
    assert {p.read_bytes() for p in paths} == {b"A", b"B"}


async def test_download_retries_on_5xx(tmp_path: Path):
    attempts = {"n": 0}
    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, content=b"ok", headers={"Content-Type": "image/png"})

    transport = httpx.MockTransport(handler)
    paths = await download_urls(
        urls=["https://x/img.png"],
        out_dir=tmp_path / "01HX",
        transport=transport,
        retries=3,
        retry_delay=0.01,
    )
    assert len(paths) == 1
    assert attempts["n"] == 3


async def test_download_fails_after_max_retries(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    with pytest.raises(DownloadError):
        await download_urls(
            urls=["https://x/img.png"],
            out_dir=tmp_path / "01HX",
            transport=transport,
            retries=2,
            retry_delay=0.01,
        )


async def test_extension_from_url(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x", headers={"Content-Type": "video/mp4"})

    transport = httpx.MockTransport(handler)
    paths = await download_urls(
        urls=["https://x/clip.mp4?sig=abc"],
        out_dir=tmp_path / "01HX",
        transport=transport,
    )
    assert paths[0].suffix == ".mp4"
