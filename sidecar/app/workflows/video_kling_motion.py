"""Kling Motion v3 pro (node 124) — character motion transfer (char + video → out_video).

Сценарий:
  CHAR_VIDEO_PROMPT — char_ref + video + prompt
                       param `character_orientation` ∈ {"video", "image"}.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.workflows.video_base import VideoWorkflow
from app.workflows.video_common import VideoScenario


class KlingMotionWorkflow(VideoWorkflow):
    WORKFLOW_SCHEMA_ID = 124
    NODE_GLOBAL_ID = "Phygital Creator/phygc-rnd-api-kling-motion"
    NODE_NAME = "Kling Motion v3 pro"
    SERVICE_VERSION = "0.0.1"  # точный узнаем при live
    OUTPUT_NAME = "out_video"

    def build_payload(
        self,
        *,
        prompt: str,
        scenario: str | VideoScenario = VideoScenario.CHAR_VIDEO_PROMPT,
        char_ref: int | str | None = None,
        video: int | str | None = None,
        mode: str = "pro",
        keep_original_sound: bool = True,
        character_orientation: str = "video",  # ∈ {"video", "image"}
        model: str = "kling_v3",
        **_extra: Any,
    ) -> dict[str, Any]:
        self._last_args = dict(
            prompt=prompt,
            scenario=str(scenario),
            char_ref=char_ref,
            video=video,
        )
        inputs = [
            # char_ref и video — required (optional=None)
            self._scalar_slot("char_ref", char_ref, data_type="image", optional=False),
            self._scalar_slot("video", video, data_type="video", optional=False),
            self._text_input("prompt", prompt, optional=True, is_modified=False),
        ]
        params = [
            self._param("mode", "enum", mode),
            self._param("keep_original_sound", "bool", keep_original_sound),
            self._param("character_orientation", "enum", character_orientation),
            self._param("model", "enum", model),
        ]
        outputs = [{"name": "out_video", "type": "video", "value": ""}]
        return {
            "id": self.WORKFLOW_SCHEMA_ID,
            "inputs": inputs,
            "params": params,
            "outputs": outputs,
        }

    def _build_config(self, **inputs: Any) -> dict[str, Any]:
        node_uuid = str(uuid.uuid4())
        payload = self.build_payload(**inputs)
        return {
            "nodes": [{
                "globalId": self.NODE_GLOBAL_ID,
                "name": self.NODE_NAME,
                "uuid": node_uuid,
                "taskID": 0,
                "serviceVersion": self.SERVICE_VERSION,
                "inputSocketGroup": {},
                "outputSocketGroup": [
                    {"name": "out_video", "dataType": "video",
                     "optionalInfo": {}, "optional": None, "displayName": None, "value": ""}
                ],
                "meta": {
                    **({"taskPrice": self._last_price} if self._last_price else {}),
                    "taskSchema": payload,
                },
                "params": {p["name"]: {"name": p["name"], "type": p["type"], "value": p["value"]}
                           for p in payload["params"]},
                "width": 350,
                "position": {"x": 600, "y": 200},
                "connections": [],
                "height": 617,
            }],
            "executedNodeUuid": node_uuid,
        }
