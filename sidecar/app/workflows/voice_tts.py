"""
Voice TTS workflow для backend-ноды 89 (ElevenLabs API TTS).

Workflow id = 89, node global id = "Phygital Creator/phygc-rnd-elevenlabs-api-tts".

V1.2: жёстко 6 пресетов голосов (3F + 3M), модель `eleven_v3`. Меняется
только текст озвучки. Каждый пресет = {voice_id_enum, custom_voice_id,
seed} — связка зафиксирована в HAR и не должна расходиться (seed залочен
на голос для воспроизводимости тембра).

Полный flow совпадает с image_gen.py:
  1. POST /api/v2/tasks/                 → {task_id}
  2. POST /api/v2/tasks/config_history   → null
  3. GET  /api/v2/tasks/<id>/             → polling до status='done'
  4. POST /api/v2/storage-object/.../download-links → S3 mp3
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from loguru import logger

from app.phygital_client.api import PhygitalClient
from app.phygital_client.models import GenerationJob
from app.workflows.base import Workflow, _normalize_progress

NODE_GLOBAL_ID = "Phygital Creator/phygc-rnd-elevenlabs-api-tts"
NODE_NAME = "Sound Creation"
SERVICE_VERSION = "0.0.43"
WORKFLOW_SCHEMA_ID = 89

MODEL_ID = "eleven_v3"
TASK_TYPE = "text_to_speech"

PENDING_STATUSES = {"new", "pending", "running", "queued", "in_progress", "waiting_for_launch"}
DONE_STATUSES = {"done", "completed", "success"}
FAIL_STATUSES = {"failed", "error", "canceled", "cancelled", "error_params"}


# Связка voice_id (enum gender-bucket) + custom_voice_id (ElevenLabs ID) +
# seed — все три значения залочены на конкретный голос. См.
# recon-captures/20260602-060123-voice-manual/parsed/submit_node89_*.json.
VOICE_PRESETS: dict[str, dict[str, Any]] = {
    # Female (calm_female_narration)
    "rv5jQF81clh7R2mBDAEQ": {
        "voice_id": "calm_female_narration", "seed": 245088556, "gender": "female",
    },
    "VywPjF0ZYksZDGdTC7uq": {
        "voice_id": "calm_female_narration", "seed": 428554748, "gender": "female",
    },
    "5XtIMNJwnXd6fKINOwVx": {
        "voice_id": "calm_female_narration", "seed": 326058312, "gender": "female",
    },
    # Male (well_rounded_male_news)
    "ZCDuYlmjTQwFnocCyTs2": {
        "voice_id": "well_rounded_male_news", "seed": 421433566, "gender": "male",
    },
    "JThzojXplQThwzu1NRgA": {
        "voice_id": "well_rounded_male_news", "seed": 362421143, "gender": "male",
    },
    "7yMNQpvLyzVR4bsoniZg": {
        "voice_id": "well_rounded_male_news", "seed": 425942874, "gender": "male",
    },
}

DEFAULT_VOICE = "rv5jQF81clh7R2mBDAEQ"  # female #1


class UnknownVoiceError(ValueError):
    """Поднимается если `voice` (custom_voice_id) не из VOICE_PRESETS."""


def _resolve_voice(voice: str) -> dict[str, Any]:
    preset = VOICE_PRESETS.get(voice)
    if preset is None:
        raise UnknownVoiceError(
            f"unknown voice '{voice}'; expected one of {sorted(VOICE_PRESETS)}"
        )
    return preset


class VoiceTTSWorkflow(Workflow):
    """Text-to-speech через ElevenLabs, 6 захардкоженных голосов."""

    workflow_id = str(WORKFLOW_SCHEMA_ID)
    EXPECTED_DURATION_S: float = 10.0  # TTS быстрее image/video

    def __init__(self, client: PhygitalClient, *, voice: str = DEFAULT_VOICE) -> None:
        super().__init__(client)
        _resolve_voice(voice)  # fail-fast если default переехал
        self.voice = voice
        self._last_text: str = ""
        self._last_price: dict[str, Any] | None = None

    # ── Payload для POST /api/v2/tasks/ ───────────────────────────────────
    def build_payload(
        self,
        *,
        text: str,
        voice: str | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        # См. image_gen.build_payload: JobRunner создаёт workflow_class(client)
        # без UI-params, реальные params приходят сюда из run(**params).
        if voice is not None:
            _resolve_voice(voice)
            self.voice = voice
        self._last_text = text
        return {
            "id": WORKFLOW_SCHEMA_ID,
            "inputs": [
                {"name": "text", "type": "text", "optional": None,
                 "isModified": False, "value": text, "meta": {}},
            ],
            "params": self._params_list(),
            "outputs": [{"name": "audio", "type": "audio", "value": ""}],
        }

    def _params_list(self) -> list[dict[str, Any]]:
        preset = _resolve_voice(self.voice)
        return [
            {"name": "task_type", "type": "enum", "value": TASK_TYPE, "meta": {}},
            {"name": "model_id", "type": "enum", "value": MODEL_ID, "meta": {}},
            {"name": "voice_id", "type": "enum", "value": preset["voice_id"], "meta": {}},
            {"name": "seed", "type": "number", "value": preset["seed"], "meta": {}},
            {"name": "duration", "type": "number", "value": 1, "meta": {}},
            {"name": "custom_voice_id", "type": "text", "value": self.voice, "meta": {}},
            {"name": "previous_text", "type": "text", "value": None, "meta": {}},
            {"name": "next_text", "type": "text", "value": None, "meta": {}},
            {"name": "language_code", "type": "text", "value": None, "meta": {}},
        ]

    # ── Payload для config_history (полный node-graph) ────────────────────
    def _build_config(self, text: str) -> dict[str, Any]:
        node_uuid = str(uuid.uuid4())
        # В config_history null'ы для previous_text/next_text/language_code
        # сериализуются как пустые строки (см. recon).
        params_for_config = []
        for p in self._params_list():
            v = p["value"]
            if p["name"] in {"previous_text", "next_text", "language_code"}:
                v = "" if v is None else v
            entry = {
                "name": p["name"],
                "type": p["type"],
                "optionalInfo": {"isEnabled": True, "mapOfEnabylity": {}},
                "value": v,
            }
            if p["name"] == "seed":
                entry["isFixedSeed"] = True
            params_for_config.append(entry)

        node = {
            "globalId": NODE_GLOBAL_ID,
            "name": NODE_NAME,
            "uuid": node_uuid,
            "taskID": 0,
            "serviceVersion": SERVICE_VERSION,
            "inputSocketGroup": {
                "text": {
                    "name": "text",
                    "type": "text",
                    "value": text,
                    "optionalInfo": {
                        "isEnabled": True,
                        "mapOfEnabylity": {},
                        "originalWorkspaceIds": text,
                    },
                },
            },
            "outputSocketGroup": [
                {
                    "name": "audio",
                    "dataType": "audio",
                    "optionalInfo": {"description": "Generated audio"},
                    "optional": None,
                    "displayName": "Audio",
                    "value": [],
                }
            ],
            "meta": {
                "texttextSelector": {"highlights": []},
                "custom_voice_idtextSelector": {"highlights": []},
                "previous_texttextSelector": {"highlights": []},
                "next_texttextSelector": {"highlights": []},
                "language_codetextSelector": {"highlights": []},
                **({"taskPrice": self._last_price} if self._last_price else {}),
                "taskSchema": {
                    "id": WORKFLOW_SCHEMA_ID,
                    "inputs": [
                        {"name": "text", "type": "text", "optional": None,
                         "isModified": False, "value": text, "meta": {}},
                    ],
                    "params": self._params_list(),
                    "outputs": [{"name": "audio", "type": "audio", "value": ""}],
                },
            },
            "params": {p["name"]: p for p in params_for_config},
            "width": 350,
            "position": {"x": 545, "y": 232},
            "connections": [],
            "height": 808,
        }
        return {"nodes": [node], "executedNodeUuid": node_uuid}

    # ── API calls ─────────────────────────────────────────────────────────
    async def submit(self, payload: dict[str, Any]) -> str:
        try:
            price_payload = {
                "id": WORKFLOW_SCHEMA_ID,
                "inputs": [{"name": "text", "value": "", "type": "text", "meta": {}}],
                "params": self._params_list(),
                "outputs": [],
            }
            self._last_price = await self.client.get_credits_price(price_payload)
            logger.debug(f"price: {self._last_price.get('price')}")
        except Exception as e:
            logger.warning(f"price lookup failed (non-fatal): {e}")

        task_id = await self.client.submit_task(payload)
        logger.info(f"Submitted task_id={task_id}")

        config = self._build_config(self._last_text)
        await self.client.post_config_history(task_id, config)
        logger.info(f"Posted config_history for task {task_id}")

        return str(task_id)

    async def wait(
        self,
        job_id: str,
        timeout: float = 180.0,
        poll_interval: float = 1.5,
    ) -> GenerationJob:
        task_id = int(job_id)
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        last_status: str | None = None
        last_progress: float | None = None
        running_started_at: float | None = None
        logged_first = False

        while loop.time() < deadline:
            data = await self.client.task_status(task_id)
            status = (data.get("status") or "").lower()
            if not logged_first:
                logger.info(
                    f"voice task {task_id} first poll: keys={list(data.keys())} "
                    f"progress={data.get('progress')!r} percent={data.get('percent')!r}"
                )
                logged_first = True
            if status != last_status:
                logger.info(
                    f"task {task_id}: {status} "
                    f"(position={data.get('position')}, progress={data.get('progress')})"
                )
                last_status = status
                if status in {"running", "in_progress"} and running_started_at is None:
                    running_started_at = loop.time()

            real_norm = _normalize_progress(data.get("progress"))
            value: float | None
            if real_norm is not None:
                value = real_norm
            elif status in {"running", "in_progress"}:
                value = self._synth_progress(running_started_at, loop.time())
            else:
                value = None
            last_progress = await self._push_progress(value, last_progress)

            if status in DONE_STATUSES:
                link_ids = self._extract_link_ids(data.get("outputs") or [])
                if not link_ids:
                    return GenerationJob(
                        job_id=job_id, status="failed",
                        error="task done but no output link_ids", raw=data,
                    )
                links = await self.client.get_download_links(link_ids)
                urls = [lnk["download_link"] for lnk in links if lnk.get("download_link")]
                return GenerationJob(
                    job_id=job_id, status="completed",
                    result_urls=urls, raw={"task": data, "links": links},
                )

            if status in FAIL_STATUSES:
                return GenerationJob(
                    job_id=job_id, status="failed",
                    error=data.get("error_message") or f"status={status}", raw=data,
                )

            if status and status not in PENDING_STATUSES:
                logger.warning(f"Unknown status '{status}', treating as pending")

            await asyncio.sleep(poll_interval)

        return GenerationJob(job_id=job_id, status="failed", error="timeout")

    @staticmethod
    def _extract_link_ids(outputs: list[dict[str, Any]]) -> list[int]:
        """outputs: [{name:'audio', type:'audio', value:'', id:[15854640]}]"""
        ids: list[int] = []
        for out in outputs:
            raw = out.get("id")
            if isinstance(raw, list):
                ids.extend(int(x) for x in raw)
            elif isinstance(raw, int):
                ids.append(raw)
        return ids
