"""Kling v3 pro (node 74) — text-to-video с input image (init_img) + optional image_tail + elements.

Сценарии:
  START_PROMPT           — только init_img
  START_END_PROMPT       — init_img + image_tail
  ELEMENTS_PROMPT        — element_1 (опц. _2, _3)
  ELEMENTS_PROMPT_VIDEO  — не отдельный subnode, тот же payload что ELEMENTS_PROMPT
                            (отличается только тем что один из элементов — video; recon
                             такого не показал; оставлено для совместимости).
"""
from __future__ import annotations

import uuid
from typing import Any

from app.workflows.video_base import VideoWorkflow
from app.workflows.video_common import VideoScenario


class KlingWorkflow(VideoWorkflow):
    WORKFLOW_SCHEMA_ID = 74
    NODE_GLOBAL_ID = "Phygital Creator/phygc-rnd-api-kling"
    NODE_NAME = "Kling v3 pro"
    SERVICE_VERSION = "0.0.63"
    OUTPUT_NAME = "out_video"

    def build_payload(
        self,
        *,
        prompt: str,
        scenario: str | VideoScenario = VideoScenario.START_PROMPT,
        init_img: list[int] | None = None,
        image_tail: int | str | None = None,
        element_1: list[int] | None = None,
        element_2: list[int] | None = None,
        element_3: list[int] | None = None,
        negative_prompt: str = "",
        model_name: str = "kling_v3",
        ratio: str = "r_16_9",
        duration: str = "sec_5",
        mode: str = "pro",
        sound: str = "off",
        cfg_scale: float = 0.5,
        element_1_name: str | None = None,
        element_2_name: str | None = None,
        element_3_name: str | None = None,
        multi_shot: bool = False,
        shot_type: str = "customize",
        multi_prompt_1: str | None = None, multi_duration_1: int = 1,
        multi_prompt_2: str | None = None, multi_duration_2: int = 1,
        multi_prompt_3: str | None = None, multi_duration_3: int = 1,
        multi_prompt_4: str | None = None, multi_duration_4: int = 1,
        **_extra: Any,
    ) -> dict[str, Any]:
        self._last_args = dict(
            prompt=prompt,
            scenario=str(scenario),
            init_img=init_img,
            image_tail=image_tail,
            element_1=element_1,
            element_2=element_2,
            element_3=element_3,
        )
        inputs = [
            self._text_input("text_prompt", prompt, optional=False, is_modified=False),
            self._text_input("negative_prompt", negative_prompt, optional=True, is_modified=False),
            self._array_slot("init_img", init_img, data_type="image",
                             meta_dimensions=[{} for _ in init_img] if init_img else None),
            # image_mask: всегда присутствует, isModified=true, value=null
            {
                "name": "image_mask",
                "type": "image",
                "optional": True,
                "isModified": True,
                "value": None,
                "meta": {},
            },
            self._scalar_slot("image_tail", image_tail, data_type="image", optional=True),
            self._array_slot("element_1", element_1, data_type="image",
                             meta_dimensions=[{} for _ in element_1] if element_1 else None),
            self._array_slot("element_2", element_2, data_type="image",
                             meta_dimensions=[{} for _ in element_2] if element_2 else None),
            self._array_slot("element_3", element_3, data_type="image",
                             meta_dimensions=[{} for _ in element_3] if element_3 else None),
        ]
        params = [
            self._param("model_name", "enum", model_name),
            self._param("ratio", "enum", ratio),
            self._param("duration", "enum", duration),
            self._param("mode", "enum", mode),
            self._param("sound", "enum", sound),
            self._param("cfg_scale", "number", cfg_scale),
            self._param("element_1_name", "text", element_1_name),
            self._param("element_2_name", "text", element_2_name),
            self._param("element_3_name", "text", element_3_name),
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
        # Минимальный config_history: один node с inputSocketGroup + outputSocketGroup.
        # Frontend дополнительно генерирует "Import Files" ноду — её мы не реплицируем,
        # т.к. серверу достаточно executed-ноды (см. image_gen.py).
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
