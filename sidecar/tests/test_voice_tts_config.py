"""Тесты VoiceTTSWorkflow._build_config — структура config_history.

HAR-fixture: recon-captures/20260602-060123-voice-manual/parsed/
config_taskNone.json (один из 6 config_history-постов, схема одинаковая).

Главное в config_history (в отличие от submit-payload'а):
  * null'ы для previous_text/next_text/language_code превращаются в ""
  * у `seed` появляется `isFixedSeed: True`
  * есть meta.taskSchema, повторяющий submit-payload
  * node.outputSocketGroup[0].value = [] (а не "" как в submit.outputs)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.workflows.voice_tts import (
    NODE_GLOBAL_ID,
    NODE_NAME,
    SERVICE_VERSION,
    VOICE_PRESETS,
    WORKFLOW_SCHEMA_ID,
    VoiceTTSWorkflow,
)

HAR_CONFIG = (
    Path(__file__).resolve().parent.parent
    / "recon-captures"
    / "20260602-060123-voice-manual"
    / "parsed"
    / "config_taskNone.json"
)


def _voice_for_har() -> str:
    """В HAR-fixture'е config — мужской голос #3 (7yMNQpvLyzVR4bsoniZg, seed 425942874)."""
    return "7yMNQpvLyzVR4bsoniZg"


def test_build_config_node_metadata_matches_har():
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")

    assert len(cfg["nodes"]) == 1
    node = cfg["nodes"][0]
    assert node["globalId"] == NODE_GLOBAL_ID
    assert node["name"] == NODE_NAME
    assert node["serviceVersion"] == SERVICE_VERSION
    assert node["taskID"] == 0
    assert node["width"] == 350
    assert node["height"] == 808
    assert node["position"] == {"x": 545, "y": 232}
    assert node["connections"] == []
    assert cfg["executedNodeUuid"] == node["uuid"]


def test_text_input_socket_propagates_value():
    text = "Cloud ru — облако и AI."
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config(text)
    text_socket = cfg["nodes"][0]["inputSocketGroup"]["text"]
    assert text_socket["name"] == "text"
    assert text_socket["type"] == "text"
    assert text_socket["value"] == text
    assert text_socket["optionalInfo"]["originalWorkspaceIds"] == text


def test_audio_output_socket_is_empty_list_not_string():
    """В config_history outputSocketGroup.value=[]; в submit outputs.value=''."""
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    out = cfg["nodes"][0]["outputSocketGroup"]
    assert len(out) == 1
    assert out[0]["name"] == "audio"
    assert out[0]["dataType"] == "audio"
    assert out[0]["value"] == []


def test_seed_has_is_fixed_seed_in_params_block():
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    seed_p = cfg["nodes"][0]["params"]["seed"]
    assert seed_p["isFixedSeed"] is True
    assert seed_p["value"] == VOICE_PRESETS[_voice_for_har()]["seed"]


def test_nullable_text_params_become_empty_string_in_config():
    """previous_text/next_text/language_code: None → '' только в config_history."""
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    params = cfg["nodes"][0]["params"]
    for key in ("previous_text", "next_text", "language_code"):
        assert params[key]["value"] == ""


def test_task_schema_uses_null_not_empty_string():
    """meta.taskSchema повторяет submit-payload, где value=None (не "")."""
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    ts = cfg["nodes"][0]["meta"]["taskSchema"]
    assert ts["id"] == WORKFLOW_SCHEMA_ID
    for p in ts["params"]:
        if p["name"] in {"previous_text", "next_text", "language_code"}:
            assert p["value"] is None


def test_meta_text_selectors_present():
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    meta = cfg["nodes"][0]["meta"]
    for key in (
        "texttextSelector",
        "custom_voice_idtextSelector",
        "previous_texttextSelector",
        "next_texttextSelector",
        "language_codetextSelector",
    ):
        assert meta[key] == {"highlights": []}


def test_task_price_attached_when_set():
    wf = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())
    wf._last_price = {"price": 20, "details": {}}
    cfg = wf._build_config("hi")
    assert cfg["nodes"][0]["meta"]["taskPrice"] == {"price": 20, "details": {}}


def test_task_price_omitted_when_unset():
    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    assert "taskPrice" not in cfg["nodes"][0]["meta"]


# ── Cross-check против реального HAR ───────────────────────────────────────

def test_config_shape_matches_har_top_level():
    """Сравниваем ключевые поля node с HAR (UUID и текст не сверяем — они
    рандомные/контекстные, всё остальное должно совпадать дословно)."""
    har_req = json.loads(HAR_CONFIG.read_text(encoding="utf-8"))["request_body"]
    har_node = har_req["config"]["nodes"][0]

    cfg = VoiceTTSWorkflow(client=MagicMock(), voice=_voice_for_har())._build_config("hi")
    our_node = cfg["nodes"][0]

    # Идентификация
    assert our_node["globalId"] == har_node["globalId"]
    assert our_node["name"] == har_node["name"]
    assert our_node["serviceVersion"] == har_node["serviceVersion"]
    assert our_node["width"] == har_node["width"]
    assert our_node["height"] == har_node["height"]
    assert our_node["position"] == har_node["position"]
    assert our_node["connections"] == har_node["connections"]

    # Outputs
    assert our_node["outputSocketGroup"] == har_node["outputSocketGroup"]

    # Структура params (ключи и shape, значения проверяем отдельно)
    assert set(our_node["params"].keys()) == set(har_node["params"].keys())
    for key, our_p in our_node["params"].items():
        har_p = har_node["params"][key]
        assert our_p["name"] == har_p["name"]
        assert our_p["type"] == har_p["type"]
        assert our_p["optionalInfo"] == har_p["optionalInfo"]
        if key == "seed":
            assert our_p["isFixedSeed"] is True
            assert har_p["isFixedSeed"] is True
