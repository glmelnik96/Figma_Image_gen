"""Сверка build_payload() с реальными submit-фикстурами из recon-сессии 2026-05-21.

Источник истины: `sidecar/recon-captures/20260521-133657/extracted/submit_NN_*.json`.

Не сравниваем 1-в-1 (есть детали типа `meta.dimensions` с реальными размерами и
`taskPrice`, недостижимые без живых файлов). Вместо этого нормализуем оба объекта:
убираем `meta.dimensions`, `isModified`, `optional`, `taskPrice` — и сравниваем
оставшийся «скелет» (id, inputs[name/type/value], params, outputs).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.workflows.video_kling import KlingWorkflow
from app.workflows.video_kling_motion import KlingMotionWorkflow
from app.workflows.video_kling_omni import KlingOmniWorkflow
from app.workflows.video_seedance import SeedanceWorkflow
from app.workflows.video_common import VideoScenario


FIXTURES_DIR = (
    Path(__file__).resolve().parents[1]
    / "recon-captures" / "20260521-133657" / "extracted"
)


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _strip_meta(d: dict[str, Any]) -> dict[str, Any]:
    """Нормализация: убираем поля, зависящие от реальных файлов/прайсинга."""
    out: dict[str, Any] = {"id": d["id"]}
    out["inputs"] = [
        {
            "name": i["name"],
            "type": i["type"],
            "value": i["value"],
        }
        for i in d["inputs"]
    ]
    out["params"] = [
        {"name": p["name"], "type": p["type"], "value": p["value"]}
        for p in d["params"]
    ]
    out["outputs"] = [
        {"name": o["name"], "type": o["type"], "value": o.get("value", "")}
        for o in d["outputs"]
    ]
    return out


# ── Kling 74 ──────────────────────────────────────────────────────────────


def test_kling_start_prompt_matches_fixture_01():
    fixture = _load("submit_01_schema74_task7083558.json")
    wf = KlingWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.START_PROMPT,
        init_img=[15380010],
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_kling_start_end_prompt_matches_fixture_04():
    fixture = _load("submit_04_schema74_task7083579.json")
    wf = KlingWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.START_END_PROMPT,
        init_img=[15380020],
        image_tail=15380016,
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


# ── Seedance 100 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("fixture_name,start_img,end_frame,seed", [
    ("submit_02_schema100_task7083561.json", 15380008, None,     63950175),
    ("submit_03_schema100_task7083578.json", 15380020, 15380016, 88245854),
    ("submit_05_schema100_task7083601.json", None,     None,     None),  # filled below
    ("submit_12_schema100_task7083703.json", None,     None,     None),
])
def test_seedance_start_variants(fixture_name, start_img, end_frame, seed):
    fixture = _load(fixture_name)
    # Подтянем seed/start_img/end_frame из самой фикстуры (для гибкости): тест проверяет
    # что *структура* payload'а матчится при правильном наборе аргументов.
    inputs_by_name = {i["name"]: i for i in fixture["inputs"]}
    params_by_name = {p["name"]: p for p in fixture["params"]}
    si = inputs_by_name["start_img"]["value"] or None
    ef = inputs_by_name["end_frame"]["value"] or None
    ri = inputs_by_name["ref_img"]["value"] or None
    sd = params_by_name["seed"]["value"]

    wf = SeedanceWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.START_END_PROMPT if ef else VideoScenario.START_PROMPT,
        start_img=si,
        end_frame=ef,
        ref_img=ri if isinstance(ri, list) and ri else None,
        seed=sd,
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_seedance_ref_prompt_matches_fixture_07():
    fixture = _load("submit_07_schema100_task7083626.json")
    params = {p["name"]: p["value"] for p in fixture["params"]}
    wf = SeedanceWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.REF_PROMPT,
        ref_img=[15380008, 15380010, 15380016],
        seed=params["seed"],
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_seedance_ref_prompt_video_matches_fixture_08():
    fixture = _load("submit_08_schema100_task7083661.json")
    params = {p["name"]: p["value"] for p in fixture["params"]}
    wf = SeedanceWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.REF_PROMPT_VIDEO,
        ref_img=[15380020, 15380020, 15380020],
        ref_vid=[15380272],
        seed=params["seed"],
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


# ── Кросс-проверка: id/output matches ─────────────────────────────────────


def test_kling_payload_has_correct_schema_id():
    wf = KlingWorkflow(client=None)
    p = wf.build_payload(prompt="x", init_img=[1])
    assert p["id"] == 74
    assert p["outputs"][0]["name"] == "out_video"


def test_seedance_payload_has_correct_schema_id():
    wf = SeedanceWorkflow(client=None)
    p = wf.build_payload(prompt="x", start_img=1)
    assert p["id"] == 100
    assert p["outputs"][0]["name"] == "video"


# ── Kling Omni 121 ────────────────────────────────────────────────────────


def test_omni_elements_prompt_matches_fixture_06():
    fixture = _load("submit_06_schema121_task7083624.json")
    wf = KlingOmniWorkflow(client=None)
    # duration=3 — фикстура старого recon; build_payload-дефолт теперь 5 (см.
    # NODE_DEFAULT_PARAMS[121]), так что явно передаём чтобы матчить fixture.
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.ELEMENTS_PROMPT,
        element_1=[15380008, 15380010, 15380016],
        duration=3,
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_omni_elements_prompt_video_matches_fixture_09():
    fixture = _load("submit_09_schema121_task7083663.json")
    wf = KlingOmniWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.ELEMENTS_PROMPT_VIDEO,
        element_1=[15380020, 15380020, 15380020],
        video=15380272,
        duration=3,
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_omni_payload_has_correct_schema_id():
    wf = KlingOmniWorkflow(client=None)
    p = wf.build_payload(prompt="x", first_frame=1)
    assert p["id"] == 121
    assert p["outputs"][0]["name"] == "out_video"


# ── Kling Motion 124 ──────────────────────────────────────────────────────


def test_motion_char_video_orientation_video_fixture_10():
    fixture = _load("submit_10_schema124_task7083686.json")
    wf = KlingMotionWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.CHAR_VIDEO_PROMPT,
        char_ref=15379954,
        video=15379948,
        character_orientation="video",
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_motion_char_video_orientation_image_fixture_11():
    fixture = _load("submit_11_schema124_task7083688.json")
    wf = KlingMotionWorkflow(client=None)
    actual = wf.build_payload(
        prompt="test",
        scenario=VideoScenario.CHAR_VIDEO_PROMPT,
        char_ref=15379954,
        video=15379948,
        character_orientation="image",
    )
    assert _strip_meta(actual) == _strip_meta(fixture)


def test_motion_payload_has_correct_schema_id():
    wf = KlingMotionWorkflow(client=None)
    p = wf.build_payload(prompt="x", char_ref=1, video=2)
    assert p["id"] == 124
    assert p["outputs"][0]["name"] == "out_video"
