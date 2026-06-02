"""Unit-тесты AssetCache (sha256-based dedup + jsonl-persistence)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.services.asset_cache import AssetCache, AssetEntry


def _make_file(p: Path, content: bytes = b"abc") -> Path:
    p.write_bytes(content)
    return p


@pytest.fixture
def jsonl(tmp_path: Path) -> Path:
    return tmp_path / "asset_cache.jsonl"


@pytest.mark.anyio
async def test_add_uploads_first_time(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    f = _make_file(tmp_path / "a.png", b"hello")
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=1234)

    entry = await cache.add(f, client)

    assert isinstance(entry, AssetEntry)
    assert entry.file_obj_id == 1234
    assert entry.size == 5
    assert entry.mime.startswith("image/")
    assert entry.sha256 == hashlib.sha256(b"hello").hexdigest()
    client.upload_file.assert_awaited_once()


@pytest.mark.anyio
async def test_add_dedupes_on_sha256(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    f = _make_file(tmp_path / "a.png", b"hello")
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=42)

    e1 = await cache.add(f, client)
    e2 = await cache.add(f, client)

    assert e1.sha256 == e2.sha256
    assert e1.file_obj_id == e2.file_obj_id == 42
    # upload вызван только один раз — второй вызов hit'нул кэш
    client.upload_file.assert_awaited_once()


@pytest.mark.anyio
async def test_persistence_via_restore(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    f = _make_file(tmp_path / "a.bin", b"xxx")
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=7)
    await cache.add(f, client)

    # Новый инстанс — должен подтянуть запись из jsonl
    cache2 = AssetCache(jsonl_path=jsonl)
    await cache2.restore()
    assert len(cache2.list()) == 1
    assert cache2.list()[0].file_obj_id == 7

    # И повторный add не дёрнет upload
    client2 = AsyncMock()
    client2.upload_file = AsyncMock(return_value=99)
    e = await cache2.add(f, client2)
    assert e.file_obj_id == 7
    client2.upload_file.assert_not_awaited()


@pytest.mark.anyio
async def test_delete_removes_in_memory_only(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    f = _make_file(tmp_path / "a", b"q")
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=1)
    e = await cache.add(f, client)

    ok = await cache.delete(e.sha256)
    assert ok is True
    assert cache.get(e.sha256) is None

    # jsonl содержит и added, и deleted
    lines = jsonl.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["added", "deleted"]


@pytest.mark.anyio
async def test_delete_unknown_returns_false(jsonl):
    cache = AssetCache(jsonl_path=jsonl)
    assert await cache.delete("deadbeef") is False


@pytest.mark.anyio
async def test_clear_drops_everything(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    client = AsyncMock()
    client.upload_file = AsyncMock(side_effect=[10, 20])
    await cache.add(_make_file(tmp_path / "x", b"1"), client)
    await cache.add(_make_file(tmp_path / "y", b"2"), client)
    assert len(cache.list()) == 2

    await cache.clear()
    assert cache.list() == []


@pytest.mark.anyio
async def test_add_missing_file_raises(jsonl, tmp_path):
    cache = AssetCache(jsonl_path=jsonl)
    client = AsyncMock()
    with pytest.raises(FileNotFoundError):
        await cache.add(tmp_path / "missing", client)


@pytest.mark.anyio
async def test_add_real_image_captures_dimensions(jsonl, tmp_path):
    """Для image/* mime AssetCache должен прогнать _prepare_for_upload
    и сохранить height/width в записи — это нужно для img2img payload."""
    from io import BytesIO
    from PIL import Image as PILImage

    img = PILImage.new("RGB", (320, 240), color=(255, 0, 0))
    buf = BytesIO()
    img.save(buf, format="PNG")
    f = tmp_path / "real.png"
    f.write_bytes(buf.getvalue())

    cache = AssetCache(jsonl_path=jsonl)
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=999)

    entry = await cache.add(f, client)

    assert entry.height == 240
    assert entry.width == 320


@pytest.mark.anyio
async def test_add_corrupt_image_falls_back_to_no_dimensions(jsonl, tmp_path):
    """Если файл с image/* mime не парсится Pillow — не блокируем,
    заливаем как есть, dimensions=None."""
    f = tmp_path / "fake.png"
    f.write_bytes(b"not a real png")

    cache = AssetCache(jsonl_path=jsonl)
    client = AsyncMock()
    client.upload_file = AsyncMock(return_value=1)

    entry = await cache.add(f, client)

    assert entry.height is None
    assert entry.width is None
    assert entry.file_obj_id == 1


@pytest.mark.anyio
async def test_old_entries_load_with_none_dimensions(jsonl, tmp_path):
    """Back-compat: запись в jsonl без height/width (старая версия) грузится с None."""
    import json
    old = {
        "event": "added",
        "ts": "2026-01-01T00:00:00Z",
        "entry": {
            "sha256": "deadbeef",
            "file_obj_id": 555,
            "local_path": "/x",
            "mime": "image/png",
            "size": 100,
            "uploaded_at": "2026-01-01T00:00:00Z",
        },
    }
    jsonl.write_text(json.dumps(old) + "\n", encoding="utf-8")

    cache = AssetCache(jsonl_path=jsonl)
    await cache.restore()

    entries = cache.list()
    assert len(entries) == 1
    assert entries[0].file_obj_id == 555
    assert entries[0].height is None
    assert entries[0].width is None
