"""Seedance 2.0 p720 (node 100) — image-to-video с reference image/video.

Сценарии:
  START_PROMPT          — только start_img
  START_END_PROMPT      — start_img + end_frame
  REF_PROMPT            — ref_img (list)
  REF_PROMPT_VIDEO      — ref_img + ref_vid (list)
"""
from __future__ import annotations

import uuid
from typing import Any

from app.workflows.video_base import VideoWorkflow
from app.workflows.video_common import VideoScenario


class SeedanceWorkflow(VideoWorkflow):
    WORKFLOW_SCHEMA_ID = 100
    NODE_GLOBAL_ID = "Phygital Creator/phygc-rnd-seedance-api"
    NODE_NAME = "Seedance 2.0 p720"
    SERVICE_VERSION = "0.0.24"
    OUTPUT_NAME = "video"

    def build_payload(
        self,
        *,
        prompt: str,
        scenario: str | VideoScenario = VideoScenario.START_PROMPT,
        start_img: int | str | None = None,
        end_frame: int | str | None = None,
        ref_img: list[int] | None = None,
        ref_vid: list[int] | None = None,
        ref_audio: list[int] | None = None,
        model: str = "v_2_0",
        aspect_ratio: str = "adaptive",
        resolution: str = "p720",
        duration: int = 5,
        seed: int = -1,  # совпадает с NODE_DEFAULT_PARAMS[100] (random)
        camerafixed: bool = False,
        generate_audio: bool = False,
        **_extra: Any,
    ) -> dict[str, Any]:
        self._last_args = dict(
            prompt=prompt,
            scenario=str(scenario),
            start_img=start_img,
            end_frame=end_frame,
            ref_img=ref_img,
            ref_vid=ref_vid,
            ref_audio=ref_audio,
        )
        inputs = [
            self._text_input("prompt", prompt, optional=False, is_modified=False),
            self._scalar_slot("start_img", start_img, data_type="image", optional=True),
            self._scalar_slot("end_frame", end_frame, data_type="image", optional=True),
            self._array_slot("ref_img", ref_img, data_type="image",
                             meta_dimensions=[{} for _ in ref_img] if ref_img else None),
            self._array_slot("ref_vid", ref_vid, data_type="video",
                             meta_dimensions=None),
            self._array_slot("ref_audio", ref_audio, data_type="audio",
                             meta_dimensions=None),
        ]
        params = [
            self._param("model", "enum", model),
            self._param("aspect_ratio", "enum", aspect_ratio),
            self._param("resolution", "enum", resolution),
            self._param("duration", "number", duration),
            self._param("seed", "number", seed),
            self._param("camerafixed", "bool", camerafixed),
            self._param("generate_audio", "bool", generate_audio),
        ]
        outputs = [{"name": "video", "type": "video", "value": ""}]
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
                    {"name": "video", "dataType": "video",
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
