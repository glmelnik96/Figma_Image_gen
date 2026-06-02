"""Kling Omni 3 pro (node 121) — multi-element video с first/last frame + optional video.

Сценарии:
  START_PROMPT           — только first_frame
  START_END_PROMPT       — first_frame + last_frame
  ELEMENTS_PROMPT        — element_1..4
  ELEMENTS_PROMPT_VIDEO  — element_1..4 + video (scalar)
"""
from __future__ import annotations

import uuid
from typing import Any

from app.workflows.video_base import VideoWorkflow
from app.workflows.video_common import VideoScenario


class KlingOmniWorkflow(VideoWorkflow):
    WORKFLOW_SCHEMA_ID = 121
    NODE_GLOBAL_ID = "Phygital Creator/phygc-rnd-api-kling-omni"
    NODE_NAME = "Kling Omni 3 pro"
    SERVICE_VERSION = "0.0.1"  # точный — узнаем при live, в recon его не было
    OUTPUT_NAME = "out_video"

    def build_payload(
        self,
        *,
        prompt: str,
        scenario: str | VideoScenario = VideoScenario.START_PROMPT,
        first_frame: int | str | None = None,
        last_frame: int | str | None = None,
        element_1: list[int] | None = None,
        element_2: list[int] | None = None,
        element_3: list[int] | None = None,
        element_4: list[int] | None = None,
        video: int | str | None = None,
        ratio: str = "r_16_9",
        model: str = "omni_3",
        mode: str = "pro",
        duration: int = 5,  # совпадает с NODE_DEFAULT_PARAMS[121] и UI-дефолтом
        sound: bool = False,
        element_1_name: str | None = None,
        element_2_name: str | None = None,
        element_3_name: str | None = None,
        element_4_name: str | None = None,
        multi_shot: bool = False,
        shot_type: str = "normal",
        multi_prompt_1: str | None = None, multi_duration_1: int = 1,
        multi_prompt_2: str | None = None, multi_duration_2: int = 1,
        multi_prompt_3: str | None = None, multi_duration_3: int = 1,
        multi_prompt_4: str | None = None, multi_duration_4: int = 1,
        **_extra: Any,
    ) -> dict[str, Any]:
        self._last_args = dict(
            prompt=prompt,
            scenario=str(scenario),
            first_frame=first_frame,
            last_frame=last_frame,
            element_1=element_1,
            element_2=element_2,
            element_3=element_3,
            element_4=element_4,
            video=video,
        )
        inputs = [
            self._text_input("text_prompt", prompt, optional=False, is_modified=False),
            self._scalar_slot("first_frame", first_frame, data_type="image", optional=True),
            self._scalar_slot("last_frame", last_frame, data_type="image", optional=True),
            self._array_slot("element_1", element_1, data_type="image",
                             meta_dimensions=[{} for _ in element_1] if element_1 else None),
            self._array_slot("element_2", element_2, data_type="image",
                             meta_dimensions=[{} for _ in element_2] if element_2 else None),
            self._array_slot("element_3", element_3, data_type="image",
                             meta_dimensions=[{} for _ in element_3] if element_3 else None),
            self._array_slot("element_4", element_4, data_type="image",
                             meta_dimensions=[{} for _ in element_4] if element_4 else None),
            self._scalar_slot("video", video, data_type="video", optional=True),
        ]
        params = [
            self._param("ratio", "enum", ratio),
            self._param("model", "enum", model),
            self._param("mode", "enum", mode),
            self._param("duration", "number", duration),
            self._param("sound", "bool", sound),
            self._param("element_1_name", "text", element_1_name),
            self._param("element_2_name", "text", element_2_name),
            self._param("element_3_name", "text", element_3_name),
            self._param("element_4_name", "text", element_4_name),
            self._param("multi_shot", "bool", multi_shot),
            self._param("shot_type", "enum", shot_type),
            self._param("multi_prompt_1", "text", multi_prompt_1),
            self._param("multi_duration_1", "number", multi_duration_1),
            self._param("multi_prompt_2", "text", multi_prompt_2),
            self._param("multi_duration_2", "number", multi_duration_2),
            self._param("multi_prompt_3", "text", multi_prompt_3),
            self._param("multi_duration_3", "number", multi_duration_3),
            self._param("multi_prompt_4", "text", multi_prompt_4),
            self._param("multi_duration_4", "number", multi_duration_4),
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
