"""/assets endpoints — sha256-cached file uploads to Phygital+."""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, Response, UploadFile

from app import paths

router = APIRouter()


@router.post("/assets")
async def upload_asset(request: Request, file: UploadFile = File(...)) -> dict:
    cache = request.app.state.asset_cache
    get_client = request.app.state.get_client

    paths.asset_uploads_dir().mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload").suffix
    tmp_path = paths.asset_uploads_dir() / f"_incoming_{uuid.uuid4().hex}{suffix}"
    with tmp_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        client = await get_client()
        try:
            entry = await cache.add(tmp_path, client)
        finally:
            await client.__aexit__(None, None, None)
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass

    return entry.model_dump()


@router.post("/assets/stage")
async def stage_asset(file: UploadFile = File(...)) -> dict:
    """Persist raw image bytes to the local staging dir and return their path.

    Unlike POST /assets (which uploads to Phygital immediately and deletes the
    temp file), this keeps the file on disk so it can be referenced by path in a
    subsequent POST /jobs `init_files`. JobRunner then resolves it through the
    AssetCache (sha256 dedup + dimension probe + Phygital upload).

    This exists because the Figma plugin has no filesystem access: it exports a
    selected layer to PNG bytes in-process and POSTs them here to obtain a path.
    Staged files are cleaned up by DELETE /assets/disk-cache.
    """
    paths.asset_uploads_dir().mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload.png").suffix or ".png"
    dst = paths.asset_uploads_dir() / f"stage_{uuid.uuid4().hex}{suffix}"
    with dst.open("wb") as out:
        shutil.copyfileobj(file.file, out)
    return {"path": str(dst), "filename": dst.name}


@router.get("/assets")
async def list_assets(request: Request) -> dict:
    cache = request.app.state.asset_cache
    return {"assets": [e.model_dump() for e in cache.list()]}


# ── Disk-cache management ───────────────────────────────────────────────
# ВАЖНО: эти роуты должны быть объявлены ДО `/assets/{sha256}`, иначе
# FastAPI матчит DELETE /assets/disk-cache как DELETE /assets/{sha256}
# с sha256="disk-cache" и возвращает 404 "unknown_asset".
# ────────────────────────────────────────────────────────────────────────

@router.get("/assets/disk-usage")
def disk_usage() -> dict:
    """Сколько файлов и байт занято в asset_uploads/.

    Туда складываются временные multipart-загрузки от CEP-панели и
    извлечённые кадры/клипы из /clips. Нужно для preview перед чисткой.
    """
    d = paths.asset_uploads_dir()
    if not d.exists():
        return {"count": 0, "total_bytes": 0}
    count = 0
    total = 0
    for p in d.iterdir():
        if p.is_file():
            try:
                total += p.stat().st_size
                count += 1
            except OSError:
                pass
    return {"count": count, "total_bytes": total}


@router.delete("/assets/disk-cache")
def clear_disk_cache() -> dict:
    """Удалить все временные файлы из asset_uploads/.

    Файлы накапливаются от /clips/extract_frame, /clips/clip_video и
    оборванных /assets uploads. sha256-cache (asset_cache.jsonl) НЕ трогаем —
    он не занимает места на диске и переживает чистку, давая нам дедуп
    после re-upload.

    Не рекурсивно: только файлы верхнего уровня, поддиректории не трогаем.
    """
    d = paths.asset_uploads_dir()
    if not d.exists():
        return {"cleared_count": 0, "freed_bytes": 0}
    cleared = 0
    freed = 0
    for p in d.iterdir():
        if p.is_file():
            try:
                sz = p.stat().st_size
                p.unlink()
                cleared += 1
                freed += sz
            except OSError:
                pass
    return {"cleared_count": cleared, "freed_bytes": freed}


@router.delete("/assets/{sha256}", status_code=204)
async def delete_asset(sha256: str, request: Request):
    cache = request.app.state.asset_cache
    ok = await cache.delete(sha256)
    if not ok:
        raise HTTPException(404, detail={"error": "unknown_asset", "sha256": sha256})
    return Response(status_code=204)


@router.delete("/assets", status_code=204)
async def clear_assets(request: Request, all: bool = False):
    if not all:
        raise HTTPException(400, detail={"error": "missing_all_param"})
    cache = request.app.state.asset_cache
    await cache.clear()
    return Response(status_code=204)
