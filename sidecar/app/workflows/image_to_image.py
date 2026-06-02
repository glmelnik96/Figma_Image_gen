"""
Image-to-image workflow поверх Nano Banana (Phygital workflow id = 94).

Отличия от text-to-image (`image_gen.py`):
  - в `inputs.init_img.type` поле меняется с "array" на "image"
  - `inputs.init_img.value` — это **список file_obj_id** (порядок важен)
  - `inputs.init_img.meta.dimensions` — параллельный список {height, width}
  - дефолтные params под Nano Banana Pro 3.1: v3_1 / r_3_4 / k2

Flow:
  1. upload каждой init-картинки → file_obj_id (POST /api/v2/storage-object/...)
  2. submit задачи с init_img.value=[ids] и meta.dimensions=[{h,w}, ...]
  3. config_history (как в text-to-image — обязателен)
  4. polling + download links (логика наследуется от ImageGenWorkflow)
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from loguru import logger

# Регистрируем HEIF/HEIC opener в Pillow (iPhone-фото).
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except ImportError:  # без HEIC всё ещё работаем на jpg/png/webp
    pass

from app.phygital_client.api import PhygitalClient
from app.workflows.image_gen import ImageGenWorkflow, WORKFLOW_SCHEMA_ID

# Phygital UI ресайзит большие входные картинки до ~2048 по длинной стороне.
# Заливаем в PNG (lossless, сохраняет альфу) — пользователь явно попросил
# не терять качество на img2img-шаге. Recon подтверждает, что Phygital+
# принимает PNG (download links на CDN отдают image/png).
MAX_DIM = 2048


def _prepare_for_upload(path: Path) -> tuple[Path, dict[str, int], bool]:
    """Нормализация любой картинки под Phygital upload:
      - HEIC/HEIF, CMYK, P-палетные PNG → конвертируем в RGB/RGBA PNG
      - RGBA/LA сохраняем как есть (PNG умеет alpha, в отличие от прошлой JPEG-схемы)
      - EXIF Orientation учитываем (иначе портретные фото с телефона уходят на бок)
      - ресайз до MAX_DIM по длинной стороне
    Если файл уже PNG, мал и не требует EXIF-поворота — отдаём оригинал.

    Возвращает (effective_path, dimensions, was_normalized).
    """
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im)  # применяет orientation и убирает тег
        w, h = im.size
        ext = path.suffix.lower()
        is_png_already = ext == ".png" and im.mode in {"RGB", "RGBA", "L", "LA"}
        too_big = max(w, h) > MAX_DIM or path.stat().st_size > 6 * 1024 * 1024

        # Если уже подходящий PNG, малого размера и orientation был тривиальный —
        # отдаём оригинал. Иначе — пересохраняем в PNG.
        if is_png_already and not too_big and im.size == (w, h):
            return path, {"height": h, "width": w}, False

        # ресайз при необходимости
        if max(w, h) > MAX_DIM:
            scale = MAX_DIM / max(w, h)
            new_w, new_h = int(w * scale), int(h * scale)
            im = im.resize((new_w, new_h), Image.LANCZOS)
        else:
            new_w, new_h = w, h

        # PNG умеет RGB, RGBA, L, LA; для остальных режимов конвертируем.
        # CMYK / P-палетные / 16-бит → RGB(A). Альфу сохраняем где была.
        if im.mode not in {"RGB", "RGBA", "L", "LA"}:
            if im.mode in {"P", "PA"}:
                # palette может содержать прозрачность — конвертим в RGBA
                im = im.convert("RGBA")
            elif im.mode == "CMYK":
                im = im.convert("RGB")
            else:
                im = im.convert("RGBA" if "A" in im.mode else "RGB")

        buf = io.BytesIO()
        # optimize=True даёт меньший файл за счёт CPU; для 2048x2048 PNG —
        # типично 2-5 MB, что в рамках Phygital-лимитов (см. 6MB threshold).
        im.save(buf, format="PNG", optimize=True)
        tmp = Path(tempfile.mkstemp(suffix=".png", prefix=f"{path.stem}_norm_")[1])
        tmp.write_bytes(buf.getvalue())
        return tmp, {"height": new_h, "width": new_w}, True


class ImageToImageWorkflow(ImageGenWorkflow):
    """Nano Banana с init-картинками (img2img / multi-image reference).

    Кроме промпта принимает список путей к локальным файлам — они загружаются
    на бэк и подставляются как `init_img`.
    """

    def __init__(
        self,
        client: PhygitalClient,
        *,
        model_name: str = "v3_1",
        ratio: str = "default",
        resolution: str = "k1",
    ) -> None:
        # Defaults align с NANO_BANANA_META.default_params в UI
        # (slot_schema.js: model_name=v3_1, ratio=default, resolution=k1).
        # Раньше img2img переопределял ratio=r_3_4/resolution=k2 — UI показывал
        # один пресет, бэк слал другой, если SubmitButton почему-либо не успел
        # подмержить дефолты.
        super().__init__(
            client,
            model_name=model_name,
            ratio=ratio,
            resolution=resolution,
        )
        # заполняется в submit_with_files(); используется build_payload/_build_config
        self._init_img_ids: list[int] = []
        self._init_img_dims: list[dict[str, int]] = []

    # ── payload (override) ────────────────────────────────────────────────
    def build_payload(
        self,
        *,
        prompt: str,
        init_img: list[Any] | None = None,
        model_name: str | None = None,
        ratio: str | None = None,
        resolution: str | None = None,
        **_extra: Any,
    ) -> dict[str, Any]:
        # См. ImageGenWorkflow.build_payload: kwargs из UI должны попасть в
        # self.X, иначе _params_list() / _build_config() пошлют init-defaults.
        self._last_prompt = prompt
        if model_name is not None:
            self.model_name = model_name
        if ratio is not None:
            self.ratio = ratio
        if resolution is not None:
            self.resolution = resolution
        # init_img-аргумент игнорируем: значения берём из state, заполненного upload-шагом.
        return {
            "id": WORKFLOW_SCHEMA_ID,
            "inputs": [
                {"name": "text_prompt", "type": "text", "optional": None,
                 "isModified": False, "value": prompt, "meta": {}},
                {"name": "init_img", "type": "image", "optional": None,
                 "isModified": False,
                 "value": list(self._init_img_ids),
                 "meta": {"dimensions": list(self._init_img_dims)}},
            ],
            "params": self._params_list(),
            "outputs": [{"name": "image", "type": "array", "value": ""}],
        }

    # ── config_history (override only the init_img piece in taskSchema) ───
    def _build_config(self, prompt: str) -> dict[str, Any]:
        cfg = super()._build_config(prompt)
        node = cfg["nodes"][0]
        # подменяем init_img внутри meta.taskSchema на img2img-форму
        task_inputs = node["meta"]["taskSchema"]["inputs"]
        for i, inp in enumerate(task_inputs):
            if inp.get("name") == "init_img":
                task_inputs[i] = {
                    "name": "init_img",
                    "type": "image",
                    "optional": None,
                    "isModified": False,
                    "value": list(self._init_img_ids),
                    "meta": {"dimensions": list(self._init_img_dims)},
                }
                break
        return cfg

    # ── high-level entrypoint ─────────────────────────────────────────────
    async def upload_images(self, paths: list[str | Path]) -> tuple[list[int], list[dict[str, int]]]:
        ids: list[int] = []
        dims: list[dict[str, int]] = []
        for p in paths:
            pp = Path(p).expanduser().resolve()
            if not pp.exists():
                raise FileNotFoundError(pp)
            effective, dim, normalized = _prepare_for_upload(pp)
            if normalized:
                logger.info(
                    f"normalized {pp.name} → {dim['width']}x{dim['height']} "
                    f"({effective.stat().st_size/1024:.0f}KB png)"
                )
            try:
                fid = await self.client.upload_file(effective)
            finally:
                if normalized and effective != pp:
                    try:
                        effective.unlink()
                    except OSError:
                        pass
            logger.info(f"uploaded {pp.name} → file_obj_id={fid}  ({dim['width']}x{dim['height']})")
            ids.append(fid)
            dims.append(dim)
        return ids, dims

    async def run_with_files(
        self,
        *,
        prompt: str,
        init_paths: list[str | Path],
    ):
        """Загружает картинки, затем стандартный submit/wait."""
        self._init_img_ids, self._init_img_dims = await self.upload_images(init_paths)
        return await self.run(prompt=prompt)
