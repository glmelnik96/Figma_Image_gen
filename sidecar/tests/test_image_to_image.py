"""Тесты ImageToImageWorkflow (Nano Banana с init_img).

Источник истины для шейпа — `workflows/image_to_image.py` в Phygital-bot
(vendor copy). Корневой баг, который этот воркфлоу закрывает: text-to-image
shape (`type="array"`, `meta.dimensions=[]`) при заполненном `init_img.value`
вызывает у Phygital молчаливый кэнсел через ~30s валидации. Img2img шейп —
`type="image"`, `meta.dimensions=[{height, width}]` — Phygital валидирует ок.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.workflows.image_gen import WORKFLOW_SCHEMA_ID
from app.workflows.image_to_image import ImageToImageWorkflow


def _wf_with_state(ids: list[int], dims: list[dict[str, int]]) -> ImageToImageWorkflow:
    wf = ImageToImageWorkflow(client=MagicMock())
    wf._init_img_ids = ids
    wf._init_img_dims = dims
    return wf


def test_build_payload_uses_image_type_and_dimensions():
    wf = _wf_with_state([15386958], [{"height": 1024, "width": 1024}])
    payload = wf.build_payload(prompt="make it cyberpunk")

    assert payload["id"] == WORKFLOW_SCHEMA_ID == 94

    init_img = next(i for i in payload["inputs"] if i["name"] == "init_img")
    assert init_img["type"] == "image", "img2img требует type=image, не array"
    assert init_img["value"] == [15386958]
    assert init_img["meta"]["dimensions"] == [{"height": 1024, "width": 1024}]
    assert init_img["isModified"] is False

    text_prompt = next(i for i in payload["inputs"] if i["name"] == "text_prompt")
    assert text_prompt["type"] == "text"
    assert text_prompt["value"] == "make it cyberpunk"
    assert text_prompt["isModified"] is False


def test_build_payload_multi_image():
    """value и dimensions должны быть параллельными списками одинаковой длины."""
    wf = _wf_with_state(
        [100, 200, 300],
        [{"height": 512, "width": 512}, {"height": 600, "width": 800}, {"height": 100, "width": 100}],
    )
    payload = wf.build_payload(prompt="multi")
    init_img = next(i for i in payload["inputs"] if i["name"] == "init_img")
    assert len(init_img["value"]) == 3
    assert len(init_img["meta"]["dimensions"]) == 3
    assert init_img["meta"]["dimensions"][1] == {"height": 600, "width": 800}


def test_build_config_patches_task_schema_init_img():
    """_build_config должен в meta.taskSchema.inputs тоже подменить init_img на img2img-форму."""
    wf = _wf_with_state([42], [{"height": 768, "width": 1024}])
    wf._last_prompt = "p"
    wf._last_price = None
    cfg = wf._build_config("p")

    task_schema_inputs = cfg["nodes"][0]["meta"]["taskSchema"]["inputs"]
    init_img = next(i for i in task_schema_inputs if i["name"] == "init_img")
    assert init_img["type"] == "image"
    assert init_img["value"] == [42]
    assert init_img["meta"]["dimensions"] == [{"height": 768, "width": 1024}]


def test_defaults_align_with_ui_meta():
    """img2img defaults должны совпадать с NANO_BANANA_META.default_params
    в slot_schema.js: v3_1 / default / k1. Раньше img2img ставил r_3_4/k2 —
    это создавало силенс-несоответствие UI vs back."""
    wf = ImageToImageWorkflow(client=MagicMock())
    assert wf.model_name == "v3_1"
    assert wf.ratio == "default"
    assert wf.resolution == "k1"
