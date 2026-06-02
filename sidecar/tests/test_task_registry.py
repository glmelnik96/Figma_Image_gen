"""Тесты TaskRegistry."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.services.task_registry import (
    JobState,
    TaskRegistry,
    JobStatus,
)


@pytest.fixture
def reg(tmp_path: Path) -> TaskRegistry:
    return TaskRegistry(jsonl_path=tmp_path / "jobs.jsonl")


async def test_create_assigns_ulid(reg: TaskRegistry):
    job_id = await reg.create(node_id=94, params={"prompt": "hi"})
    assert isinstance(job_id, str)
    assert len(job_id) == 26  # ULID

    state = reg.get(job_id)
    assert state.status == "queued"
    assert state.node_id == 94
    assert state.params == {"prompt": "hi"}
    assert state.error is None


async def test_create_persists_to_jsonl(reg: TaskRegistry, tmp_path: Path):
    job_id = await reg.create(node_id=94, params={"prompt": "hi"})
    jsonl = (tmp_path / "jobs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(jsonl) == 1
    rec = json.loads(jsonl[0])
    assert rec["event"] == "created"
    assert rec["job_id"] == job_id
    assert rec["node_id"] == 94


async def test_update_status_appends_event(reg: TaskRegistry, tmp_path: Path):
    job_id = await reg.create(node_id=94, params={})
    await reg.update_status(job_id, status="submitted", task_id="phygital-abc")
    await reg.update_status(job_id, status="completed", result_paths=["/tmp/x.png"])

    state = reg.get(job_id)
    assert state.status == "completed"
    assert state.task_id == "phygital-abc"
    assert state.result_paths == ["/tmp/x.png"]

    jsonl = (tmp_path / "jobs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(jsonl) == 3  # created + 2 updates


async def test_restore_replays_events(tmp_path: Path):
    jsonl = tmp_path / "jobs.jsonl"
    jsonl.write_text(
        json.dumps({"ts": "2026-05-21T10:00:00Z", "job_id": "01HX", "event": "created", "node_id": 94, "params": {}}) + "\n"
        + json.dumps({"ts": "2026-05-21T10:00:01Z", "job_id": "01HX", "event": "status", "status": "submitted", "task_id": "abc"}) + "\n"
        + json.dumps({"ts": "2026-05-21T10:00:02Z", "job_id": "01HX", "event": "status", "status": "completed", "result_paths": ["/tmp/x.png"]}) + "\n",
        encoding="utf-8",
    )
    reg = TaskRegistry(jsonl_path=jsonl)
    await reg.restore()

    state = reg.get("01HX")
    assert state.status == "completed"
    assert state.task_id == "abc"
    assert state.result_paths == ["/tmp/x.png"]


async def test_restore_marks_orphans_without_task_id(tmp_path: Path):
    jsonl = tmp_path / "jobs.jsonl"
    jsonl.write_text(
        json.dumps({"ts": "2026-05-21T10:00:00Z", "job_id": "01ORPH", "event": "created", "node_id": 94, "params": {}}) + "\n"
        # никакого status submit/task_id — sidecar упал между create и submit
        ,
        encoding="utf-8",
    )
    reg = TaskRegistry(jsonl_path=jsonl)
    await reg.restore()

    state = reg.get("01ORPH")
    assert state.status == "failed"
    assert state.error == "orphaned_on_restart"


async def test_restore_keeps_running_with_task_id(tmp_path: Path):
    jsonl = tmp_path / "jobs.jsonl"
    jsonl.write_text(
        json.dumps({"ts": "2026-05-21T10:00:00Z", "job_id": "01R", "event": "created", "node_id": 94, "params": {}}) + "\n"
        + json.dumps({"ts": "2026-05-21T10:00:01Z", "job_id": "01R", "event": "status", "status": "running", "task_id": "abc"}) + "\n",
        encoding="utf-8",
    )
    reg = TaskRegistry(jsonl_path=jsonl)
    await reg.restore()

    state = reg.get("01R")
    assert state.status == "running"  # будет resync через Phygital в job_runner
    assert state.task_id == "abc"


async def test_concurrent_create_unique_ids(reg: TaskRegistry):
    job_ids = await asyncio.gather(*[reg.create(node_id=94, params={}) for _ in range(50)])
    assert len(set(job_ids)) == 50


async def test_list_filter_by_status(reg: TaskRegistry):
    j1 = await reg.create(node_id=94, params={})
    j2 = await reg.create(node_id=94, params={})
    j3 = await reg.create(node_id=94, params={})
    await reg.update_status(j1, status="completed")
    await reg.update_status(j2, status="running")
    # j3 остаётся queued

    running = reg.list(status="running")
    assert {s.job_id for s in running} == {j2}
    completed = reg.list(status="completed")
    assert {s.job_id for s in completed} == {j1}
    all_jobs = reg.list()
    assert {s.job_id for s in all_jobs} == {j1, j2, j3}
