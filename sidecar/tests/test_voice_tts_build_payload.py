"""Тесты VoiceTTSWorkflow.build_payload — бит-в-бит соответствие HAR.

Источник истины — recon-captures/20260602-060123-voice-manual/parsed/
submit_node89_taskorphan{0..5}.json (6 живых submit'ов на ноду 89).

Главное, что должны проверить:
  * `id == 89`
  * `inputs[0]` = text/text/null/false/value
  * `outputs` = [{name:'audio', type:'audio', value:''}]
  * params 9 шт. в правильном порядке и со связкой
    (custom_voice_id → voice_id, seed) как в HAR
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.workflows.voice_tts import (
    DEFAULT_VOICE,
    VOICE_PRESETS,
    WORKFLOW_SCHEMA_ID,
    UnknownVoiceError,
    VoiceTTSWorkflow,
)

HAR_DIR = (
    Path(__file__).resolve().parent.parent
    / "recon-captures"
    / "20260602-060123-voice-manual"
    / "parsed"
)


def _load_har(idx: int) -> dict:
    return json.loads(
        (HAR_DIR / f"submit_node89_taskorphan{idx}.json").read_text(encoding="utf-8")
    )["request_body"]


# ── Базовые инварианты ─────────────────────────────────────────────────────

def test_workflow_schema_id_matches_har():
    assert WORKFLOW_SCHEMA_ID == 89


def test_default_voice_is_known():
    assert DEFAULT_VOICE in VOICE_PRESETS


def test_six_presets_three_male_three_female():
    males = [v for v in VOICE_PRESETS.values() if v["gender"] == "male"]
    females = [v for v in VOICE_PRESETS.values() if v["gender"] == "female"]
    assert len(males) == 3
    assert len(females) == 3


def test_unknown_voice_raises():
    with pytest.raises(UnknownVoiceError):
        VoiceTTSWorkflow(client=MagicMock(), voice="nope")


# ── build_payload против каждого HAR-submit'а ──────────────────────────────

@pytest.mark.parametrize("idx", list(range(6)))
def test_build_payload_matches_har(idx: int):
    har = _load_har(idx)

    # Достаём voice (custom_voice_id) и text из HAR — это то, что UI меняет.
    custom_voice_id = next(
        p["value"] for p in har["params"] if p["name"] == "custom_voice_id"
    )
    text = har["inputs"][0]["value"]

    wf = VoiceTTSWorkflow(client=MagicMock(), voice=custom_voice_id)
    payload = wf.build_payload(text=text)

    # Top-level shape
    assert payload["id"] == har["id"] == 89
    assert payload["outputs"] == har["outputs"]

    # text-input — точная репликация
    assert payload["inputs"] == har["inputs"]

    # params — порядок и значения совпадают с HAR полностью
    assert payload["params"] == har["params"]


@pytest.mark.parametrize("voice_id", list(VOICE_PRESETS))
def test_each_preset_locks_voice_id_and_seed(voice_id: str):
    """Связка custom_voice_id ↔ (voice_id, seed) должна быть жёсткой."""
    wf = VoiceTTSWorkflow(client=MagicMock(), voice=voice_id)
    payload = wf.build_payload(text="hi")

    params = {p["name"]: p["value"] for p in payload["params"]}
    preset = VOICE_PRESETS[voice_id]

    assert params["custom_voice_id"] == voice_id
    assert params["voice_id"] == preset["voice_id"]
    assert params["seed"] == preset["seed"]
    # Постоянные поля
    assert params["task_type"] == "text_to_speech"
    assert params["model_id"] == "eleven_v3"
    assert params["duration"] == 1
    assert params["previous_text"] is None
    assert params["next_text"] is None
    assert params["language_code"] is None


def test_voice_override_via_build_payload_kwarg():
    """UI может прислать `voice` в params — он должен переопределить дефолт."""
    wf = VoiceTTSWorkflow(client=MagicMock())  # default voice
    assert wf.voice == DEFAULT_VOICE

    other = next(v for v in VOICE_PRESETS if v != DEFAULT_VOICE)
    payload = wf.build_payload(text="x", voice=other)

    assert wf.voice == other
    custom = next(p for p in payload["params"] if p["name"] == "custom_voice_id")
    assert custom["value"] == other


def test_build_payload_ignores_extra_kwargs():
    """JobRunner может прислать лишние ключи — не должны падать."""
    wf = VoiceTTSWorkflow(client=MagicMock())
    payload = wf.build_payload(text="hi", foo="bar", baz=123)
    assert payload["inputs"][0]["value"] == "hi"
