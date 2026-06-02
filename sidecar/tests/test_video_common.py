"""Тесты video_common: enum, схема слотов, validate_slots, describe_video_nodes."""
from __future__ import annotations

import pytest

from app.workflows.video_common import (
    NODE_DEFAULT_PARAMS,
    NODE_MODEL_LABEL,
    NODE_SLOTS,
    SCENARIO_SLOTS,
    VideoScenario,
    describe_video_nodes,
    validate_slots,
)


def test_all_nodes_have_defaults_and_label():
    for node_id in NODE_SLOTS:
        assert node_id in NODE_DEFAULT_PARAMS
        assert node_id in NODE_MODEL_LABEL


def test_scenario_slots_reference_existing_slots():
    for (node_id, scenario), required in SCENARIO_SLOTS.items():
        schema = NODE_SLOTS[node_id]
        for slot in required:
            assert slot in schema, f"{scenario} requires {slot!r} but node {node_id} has no such slot"


def test_describe_returns_all_nodes():
    out = describe_video_nodes()
    ids = {n["node_id"] for n in out}
    assert ids == {74, 100, 121, 124}
    for node in out:
        assert node["scenarios"], f"node {node['node_id']} has no scenarios"


# ── validate_slots ────────────────────────────────────────────────────────


@pytest.mark.parametrize("node_id,scenario,init_files", [
    (74, VideoScenario.START_PROMPT, {"init_img": ["/a.png"]}),
    (74, VideoScenario.START_END_PROMPT, {"init_img": ["/a.png"], "image_tail": "/b.png"}),
    (74, VideoScenario.ELEMENTS_PROMPT, {"element_1": ["/a.png"]}),
    (100, VideoScenario.START_PROMPT, {"start_img": "/a.png"}),
    (100, VideoScenario.START_END_PROMPT, {"start_img": "/a.png", "end_frame": "/b.png"}),
    (100, VideoScenario.REF_PROMPT, {"ref_img": ["/a.png"]}),
    (100, VideoScenario.REF_PROMPT_VIDEO, {"ref_img": ["/a.png"], "ref_vid": ["/v.mp4"]}),
    (121, VideoScenario.START_PROMPT, {"first_frame": "/a.png"}),
    (121, VideoScenario.ELEMENTS_PROMPT_VIDEO, {"element_1": ["/a.png"], "video": "/v.mp4"}),
    (124, VideoScenario.CHAR_VIDEO_PROMPT, {"char_ref": "/a.png", "video": "/v.mp4"}),
])
def test_validate_slots_accepts_valid(node_id, scenario, init_files):
    validate_slots(node_id, scenario, init_files)  # should not raise


def test_validate_unknown_node_raises():
    with pytest.raises(ValueError, match="unknown video node_id"):
        validate_slots(999, VideoScenario.START_PROMPT, {})


def test_validate_unsupported_scenario_raises():
    # node 124 (Motion) — поддерживает только CHAR_VIDEO_PROMPT
    with pytest.raises(ValueError, match="not supported"):
        validate_slots(124, VideoScenario.START_PROMPT, {})


def test_validate_missing_required_slot_raises():
    with pytest.raises(ValueError, match="missing required slot"):
        validate_slots(74, VideoScenario.START_END_PROMPT, {"init_img": ["/a"]})


def test_validate_empty_slot_treated_as_missing():
    with pytest.raises(ValueError, match="missing required slot"):
        validate_slots(74, VideoScenario.START_PROMPT, {"init_img": []})


def test_validate_unknown_slot_raises():
    with pytest.raises(ValueError, match="unknown slot"):
        validate_slots(
            74,
            VideoScenario.START_PROMPT,
            {"init_img": ["/a"], "nope": "/x"},
        )


def test_validate_array_must_be_list():
    with pytest.raises(ValueError, match="must be array"):
        # init_img на ноде 74 — array, передаём scalar
        validate_slots(74, VideoScenario.START_PROMPT, {"init_img": "/a"})


def test_validate_scalar_must_not_be_list():
    with pytest.raises(ValueError, match="must be scalar"):
        # start_img на ноде 100 — scalar, передаём list
        validate_slots(100, VideoScenario.START_PROMPT, {"start_img": ["/a"]})
