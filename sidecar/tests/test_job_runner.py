"""Тесты JobRunner (с моком воркфлоу)."""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.phygital_client.models import GenerationJob
from app.services.job_runner import JobRunner
from app.services.task_registry import TaskRegistry


@pytest.fixture
def reg(tmp_path: Path) -> TaskRegistry:
    return TaskRegistry(jsonl_path=tmp_path / "jobs.jsonl")


async def test_run_completes_successfully(reg: TaskRegistry, tmp_path: Path, monkeypatch):
    job_id = await reg.create(node_id=94, params={"prompt": "hi"})

    fake_workflow = MagicMock()
    fake_workflow.run = AsyncMock(return_value=GenerationJob(
        job_id="phygital-task-123",
        status="completed",
        result_urls=["https://x/img.png"],
    ))
    fake_workflow_class = MagicMock(return_value=fake_workflow)

    fake_download = AsyncMock(return_value=[tmp_path / "01HX" / "0001.png"])

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_workflow_class},
        get_client=AsyncMock(return_value=MagicMock()),
        download_urls_fn=fake_download,
    )

    await runner.run_job(job_id)

    state = reg.get(job_id)
    assert state.status == "completed"
    assert state.task_id == "phygital-task-123"
    assert state.result_paths == [str(tmp_path / "01HX" / "0001.png")]


async def test_run_records_failure(reg: TaskRegistry, tmp_path: Path):
    job_id = await reg.create(node_id=94, params={"prompt": "hi"})

    fake_workflow = MagicMock()
    fake_workflow.run = AsyncMock(return_value=GenerationJob(
        job_id="t-1", status="failed", error="bad prompt",
    ))
    fake_workflow_class = MagicMock(return_value=fake_workflow)

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_workflow_class},
        get_client=AsyncMock(return_value=MagicMock()),
        download_urls_fn=AsyncMock(),
    )
    await runner.run_job(job_id)

    state = reg.get(job_id)
    assert state.status == "failed"
    assert state.error == "bad prompt"


async def test_run_records_unexpected_exception(reg: TaskRegistry, tmp_path: Path):
    job_id = await reg.create(node_id=94, params={"prompt": "hi"})

    fake_workflow = MagicMock()
    fake_workflow.run = AsyncMock(side_effect=RuntimeError("boom"))
    fake_workflow_class = MagicMock(return_value=fake_workflow)

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_workflow_class},
        get_client=AsyncMock(return_value=MagicMock()),
        download_urls_fn=AsyncMock(),
    )
    await runner.run_job(job_id)

    state = reg.get(job_id)
    assert state.status == "failed"
    assert "boom" in (state.error or "")


async def test_init_files_resolved_to_file_obj_ids(reg: TaskRegistry, tmp_path: Path):
    """job_runner: _init_files (dict[slot, list[str]|str]) → params[slot]=[file_obj_id].

    Node 999 — фейковый, чтобы не триггерить img2img-диспатч для node 94.
    """
    f1 = tmp_path / "a.png"
    f1.write_bytes(b"AAA")
    f2 = tmp_path / "b.png"
    f2.write_bytes(b"BBB")

    job_id = await reg.create(
        node_id=999,
        params={
            "prompt": "hi",
            "_init_files": {
                "init_img": [str(f1), str(f2)],
                "image_tail": str(f1),
            },
        },
    )

    received_kwargs: dict = {}

    async def capture_run(**kwargs):
        received_kwargs.update(kwargs)
        return GenerationJob(job_id="t", status="completed", result_urls=[])

    fake_workflow = MagicMock()
    fake_workflow.run = capture_run
    fake_workflow_class = MagicMock(return_value=fake_workflow)

    from app.services.asset_cache import AssetCache

    cache = AssetCache(jsonl_path=tmp_path / "assets.jsonl")
    fake_client = MagicMock()
    counter = [0]

    async def fake_upload(path, **kwargs):
        counter[0] += 1
        return 1000 + counter[0]

    fake_client.upload_file = fake_upload

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={999: fake_workflow_class},
        get_client=AsyncMock(return_value=fake_client),
        download_urls_fn=AsyncMock(return_value=[]),
        asset_cache=cache,
    )
    await runner.run_job(job_id)

    assert "_init_files" not in received_kwargs
    # f1 и f2 — две разные sha256 → два upload; image_tail переиспользует f1 (hit)
    assert len(received_kwargs["init_img"]) == 2
    assert isinstance(received_kwargs["image_tail"], int)
    # image_tail равен первому file_obj_id (для f1)
    assert received_kwargs["image_tail"] == received_kwargs["init_img"][0]
    # Всего upload'ов = 2 (не 3): f1 переиспользован через cache
    assert counter[0] == 2


async def test_node_94_with_init_img_dispatches_to_img2img(reg: TaskRegistry, tmp_path: Path, monkeypatch):
    """Node 94 + init_img в init_files → JobRunner подменяет workflow на ImageToImageWorkflow.

    Без этого диспатча payload идёт в text-to-image форме (type=array,
    meta.dimensions=[]) и Phygital через ~30s валидации кэнселит таск.
    """
    from io import BytesIO
    from PIL import Image as PILImage

    # Реальный PNG — чтобы _prepare_for_upload в AssetCache прошёл и захватил dimensions.
    img = PILImage.new("RGB", (640, 480), color=(10, 20, 30))
    buf = BytesIO()
    img.save(buf, format="PNG")
    f = tmp_path / "src.png"
    f.write_bytes(buf.getvalue())

    job_id = await reg.create(
        node_id=94,
        params={"prompt": "make it cyberpunk", "_init_files": {"init_img": [str(f)]}},
    )

    # Ловим, какой class использовался для построения workflow.
    instantiated: dict = {}

    class FakeImg2Img:
        def __init__(self, client):
            instantiated["client"] = client
            instantiated["class"] = "ImageToImageWorkflow"
            self._init_img_ids: list[int] = []
            self._init_img_dims: list[dict] = []

        async def run(self, **kwargs):
            instantiated["run_kwargs"] = kwargs
            instantiated["ids"] = list(self._init_img_ids)
            instantiated["dims"] = list(self._init_img_dims)
            return GenerationJob(job_id="t-img2img", status="completed", result_urls=[])

    # Подменяем именно тот символ, который импортирует JobRunner (late import).
    import app.workflows.image_to_image as i2i_mod
    monkeypatch.setattr(i2i_mod, "ImageToImageWorkflow", FakeImg2Img)

    from app.services.asset_cache import AssetCache
    cache = AssetCache(jsonl_path=tmp_path / "assets.jsonl")
    fake_client = MagicMock()
    fake_client.upload_file = AsyncMock(return_value=15386958)

    # Дефолтный (text-to-image) workflow_class для node 94 — должен быть проигнорирован.
    fake_t2i_class = MagicMock()
    fake_t2i_class.side_effect = AssertionError("должен быть выбран ImageToImageWorkflow, не t2i")

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_t2i_class},
        get_client=AsyncMock(return_value=fake_client),
        download_urls_fn=AsyncMock(return_value=[]),
        asset_cache=cache,
    )
    await runner.run_job(job_id)

    assert instantiated.get("class") == "ImageToImageWorkflow"
    assert instantiated["ids"] == [15386958]
    assert instantiated["dims"] == [{"height": 480, "width": 640}]
    # prompt передан, init_img из kwargs убран (он уехал в workflow._init_img_ids)
    assert instantiated["run_kwargs"]["prompt"] == "make it cyberpunk"
    assert "init_img" not in instantiated["run_kwargs"]


async def test_node_94_without_init_img_uses_text_to_image(reg: TaskRegistry, tmp_path: Path):
    """Node 94 без init_files → стандартный ImageGenWorkflow (text-to-image)."""
    job_id = await reg.create(node_id=94, params={"prompt": "p"})

    fake_workflow = MagicMock()
    fake_workflow.run = AsyncMock(return_value=GenerationJob(
        job_id="t-t2i", status="completed", result_urls=[],
    ))
    fake_t2i_class = MagicMock(return_value=fake_workflow)

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_t2i_class},
        get_client=AsyncMock(return_value=MagicMock()),
        download_urls_fn=AsyncMock(return_value=[]),
    )
    await runner.run_job(job_id)

    fake_t2i_class.assert_called_once()  # именно зарегистрированный (t2i) класс
    state = reg.get(job_id)
    assert state.status == "completed"


async def test_semaphore_limits_concurrency(reg: TaskRegistry, tmp_path: Path):
    started = []
    release_event = asyncio.Event()

    async def slow_run(**kwargs):
        started.append(1)
        await release_event.wait()
        return GenerationJob(job_id="t", status="completed", result_urls=[])

    fake_workflow = MagicMock()
    fake_workflow.run = slow_run
    fake_workflow_class = MagicMock(return_value=fake_workflow)

    runner = JobRunner(
        registry=reg,
        downloads_root=tmp_path,
        max_concurrent=2,
        nodes={94: fake_workflow_class},
        get_client=AsyncMock(return_value=MagicMock()),
        download_urls_fn=AsyncMock(return_value=[]),
    )

    j1 = await reg.create(node_id=94, params={})
    j2 = await reg.create(node_id=94, params={})
    j3 = await reg.create(node_id=94, params={})

    tasks = [
        asyncio.create_task(runner.run_job(j1)),
        asyncio.create_task(runner.run_job(j2)),
        asyncio.create_task(runner.run_job(j3)),
    ]
    await asyncio.sleep(0.05)
    assert len(started) == 2  # третья ждёт семафор

    release_event.set()
    await asyncio.gather(*tasks)
    assert len(started) == 3
