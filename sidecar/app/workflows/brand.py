"""Brand-консистентная генерация (Cloud.ru) — порт из Phygital-bot.

Pipeline (Path A — два sequential tasks, как UI Phygital+):
  text2img:  user_text → Gemini Text (system-prompt-документ варианта) → description
             description → Nano Banana → image
  img2img:   init image(s) → Gemini Text ("Read the System Prompt" + img2img-doc
             + те же изображения) → description
             same images + description → Nano Banana → image

text2img поддерживает варианты photo / render / isometric (см. brand_docs).
Safety-retry: если Nano Banana вернул safety reject «remove harmful word X»,
прогоняем промпт через Gemini-scrubber и перезапускаем (до MAX_SCRUB_RETRIES).
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from app.phygital_client.api import PhygitalClient
from app.phygital_client.models import GenerationJob
from app.services.brand_docs import (
    IMG2IMG_DOC,
    SCRUBBER_DOC,
    VARIANT_DOCS,
    get_img2img_doc,
    get_scrubber_doc,
    get_text2img_doc,
    invalidate_brand_doc,
)
from app.workflows.base import ProgressCallback
from app.workflows.gemini_text import GeminiTextWorkflow, run_text_with_flash_fallback
from app.workflows.image_gen import ImageGenWorkflow
from app.workflows.image_to_image import ImageToImageWorkflow

# Фикс-текст для Gemini Text в img2img. Не редактируется — суть в system-prompt-документе.
BRAND_I2I_PROMPT = "Read the System Prompt"

# Максимум попыток sanitize+retry, если Nano Banana подряд режет safety filter.
MAX_SCRUB_RETRIES = 2

# Парсер сообщения вида «Please remove potential harmful word knob from the prompt…»
_SAFETY_PATTERN = re.compile(
    r"remove\s+(?:the\s+)?(?:potential(?:ly)?\s+)?harmful\s+words?\s+"
    r"['\"`]?(?P<word>[^\s,'\"`]+)['\"`]?"
    r"\s+from",
    re.IGNORECASE,
)


def _is_stale_doc_error(job: GenerationJob) -> bool:
    """True, если Gemini Text упал с 'Cannot upload files' — file_obj_id
    брендового документа протух, кэш надо переаплоадить."""
    if job.status == "completed":
        return False
    return "cannot upload files" in (job.error or "").lower()


def _extract_flagged_word(job: GenerationJob) -> str | None:
    """Если ошибка — safety-reject Nano Banana, вернуть flagged word; иначе None."""
    if job.status == "completed":
        return None
    m = _SAFETY_PATTERN.search(job.error or "")
    if not m:
        return None
    word = m.group("word").strip().strip('".,!?:;\'`')
    return word or None


async def _scrub_prompt(
    client: PhygitalClient, *, prompt: str, flagged_word: str
) -> str | None:
    """Прогнать промпт через Gemini-scrubber. Возвращает почищенный промпт или
    None, если Gemini Text упал/пустой (тогда retry смысла не имеет)."""
    scrubber_doc_id = await get_scrubber_doc(client)
    scrub_input = f"FLAGGED WORD: {flagged_word}\n\nPROMPT TO FIX:\n{prompt}"
    wf = GeminiTextWorkflow(client)
    job = await wf.run_text(prompt=scrub_input, document_ids=[scrubber_doc_id])
    if _is_stale_doc_error(job):
        logger.warning(
            "[scrubber] stale scrubber doc — invalidating cache and retrying once"
        )
        await invalidate_brand_doc(SCRUBBER_DOC)
        scrubber_doc_id = await get_scrubber_doc(client)
        wf = GeminiTextWorkflow(client)
        job = await wf.run_text(prompt=scrub_input, document_ids=[scrubber_doc_id])
    if job.status != "completed":
        logger.warning(
            f"[scrubber] Gemini Text failed: status={job.status} err={job.error!r}"
        )
        return None
    cleaned = (job.result_text or "").strip()
    if not cleaned:
        logger.warning("[scrubber] Gemini Text returned empty cleaned prompt")
        return None
    return cleaned


async def run_brand_text2img(
    client: PhygitalClient,
    *,
    prompt: str,
    variant: str = "photo",
    model_name: str = "v3_1",
    ratio: str = "default",
    resolution: str = "default",
    pct_cb: ProgressCallback | None = None,
) -> GenerationJob:
    """user-text → описание (Gemini c вариантным system-prompt) → картинка (Nano Banana)."""
    doc_id = await get_text2img_doc(client, variant)
    logger.info(f"[brand_t2i:{variant}] using system-prompt doc_id={doc_id}")
    job_t = await run_text_with_flash_fallback(
        client, prompt=prompt, document_ids=[doc_id], on_progress=pct_cb,
    )
    if _is_stale_doc_error(job_t):
        stale_doc = VARIANT_DOCS.get(variant)
        logger.warning(
            f"[brand_t2i:{variant}] stale brand doc (was id={doc_id}); "
            f"invalidating cache and retrying Gemini Text once"
        )
        if stale_doc:
            await invalidate_brand_doc(stale_doc)
        doc_id = await get_text2img_doc(client, variant)
        job_t = await run_text_with_flash_fallback(
            client, prompt=prompt, document_ids=[doc_id], on_progress=pct_cb,
        )
    if job_t.status != "completed" or not (job_t.result_text or "").strip():
        logger.warning(
            f"[brand_t2i:{variant}] Gemini Text failed: "
            f"status={job_t.status} err={job_t.error!r}"
        )
        return GenerationJob(
            job_id=job_t.job_id,
            status="failed",
            error=f"Gemini Text: {job_t.error or 'empty description'}",
            raw={"gemini": job_t.raw},
        )

    description = job_t.result_text
    logger.info(
        f"[brand_t2i:{variant}] Gemini description ready (chars={len(description)}); "
        f"submitting Nano Banana"
    )
    current_prompt = description

    def _new_img_wf() -> ImageGenWorkflow:
        # Каждый retry — свежий ImageGenWorkflow, чтобы _last_price/state
        # не утекали между сабмитами.
        wf = ImageGenWorkflow(
            client, model_name=model_name, ratio=ratio, resolution=resolution
        )
        wf.on_progress = pct_cb
        return wf

    img_job = await _new_img_wf().run(prompt=current_prompt)

    for attempt in range(1, MAX_SCRUB_RETRIES + 1):
        flagged = _extract_flagged_word(img_job)
        if not flagged:
            # либо успех, либо иная (не-safety) ошибка — не лезем чинить
            break
        logger.info(
            f"[brand_t2i:{variant}] Nano Banana safety-reject "
            f"(attempt={attempt}/{MAX_SCRUB_RETRIES}) flagged_word={flagged!r}; "
            f"running Gemini scrubber"
        )
        cleaned = await _scrub_prompt(
            client, prompt=current_prompt, flagged_word=flagged
        )
        if not cleaned or cleaned == current_prompt:
            logger.warning(
                f"[brand_t2i:{variant}] scrubber returned nothing/identical — aborting"
            )
            break
        current_prompt = cleaned
        logger.info(
            f"[brand_t2i:{variant}] scrubbed prompt ready (chars={len(current_prompt)}); "
            f"resubmitting Nano Banana"
        )
        img_job = await _new_img_wf().run(prompt=current_prompt)

    return img_job


async def run_brand_img2img(
    client: PhygitalClient,
    *,
    init_img_ids: list[int],
    init_img_dims: list[dict[str, int]],
    model_name: str = "v3_1",
    ratio: str = "r_3_4",
    resolution: str = "k2",
    pct_cb: ProgressCallback | None = None,
) -> GenerationJob:
    """init-image(s) → описание (Gemini) → картинка (Nano Banana с теми же init-img).

    init_img_ids/init_img_dims уже загружены вызывающим (JobRunner через
    AssetCache) — переиспользуем file_obj_id между Gemini Text и Nano Banana.
    """
    if not init_img_ids:
        return GenerationJob(
            job_id="", status="failed",
            error="brand_i2i requires at least one init image",
        )

    img_wf = ImageToImageWorkflow(
        client, model_name=model_name, ratio=ratio, resolution=resolution
    )
    img_wf.on_progress = pct_cb
    img_wf._init_img_ids = list(init_img_ids)
    img_wf._init_img_dims = list(init_img_dims)

    doc_id = await get_img2img_doc(client)
    job_t = await run_text_with_flash_fallback(
        client,
        prompt=BRAND_I2I_PROMPT,
        init_img_ids=init_img_ids,
        init_img_dims=init_img_dims,
        document_ids=[doc_id],
        on_progress=pct_cb,
    )
    if _is_stale_doc_error(job_t):
        logger.warning(
            f"[brand_i2i] stale brand doc (was id={doc_id}); "
            f"invalidating cache and retrying Gemini Text once"
        )
        await invalidate_brand_doc(IMG2IMG_DOC)
        doc_id = await get_img2img_doc(client)
        job_t = await run_text_with_flash_fallback(
            client,
            prompt=BRAND_I2I_PROMPT,
            init_img_ids=init_img_ids,
            init_img_dims=init_img_dims,
            document_ids=[doc_id],
            on_progress=pct_cb,
        )
    if job_t.status != "completed" or not (job_t.result_text or "").strip():
        logger.warning(
            f"[brand_i2i] Gemini Text failed: status={job_t.status} err={job_t.error!r}"
        )
        return GenerationJob(
            job_id=job_t.job_id,
            status="failed",
            error=f"Gemini Text: {job_t.error or 'empty description'}",
            raw={"gemini": job_t.raw},
        )

    description = job_t.result_text
    logger.info(
        f"[brand_i2i] Gemini description ready (chars={len(description)}); "
        f"submitting Nano Banana with same {len(init_img_ids)} init image(s)"
    )
    # img_wf уже держит _init_img_ids/_init_img_dims — build_payload подставит их.
    return await img_wf.run(prompt=description)


# Допустимые значения поля pipeline в /jobs.
BRAND_PIPELINES = {"brand_t2i", "brand_i2i"}


async def run_brand_pipeline(
    pipeline: str,
    client: PhygitalClient,
    *,
    params: dict[str, Any],
    init_img_ids: list[int],
    init_img_dims: list[dict[str, int]],
    pct_cb: ProgressCallback | None = None,
) -> GenerationJob:
    """Диспетчер brand-пайплайнов для JobRunner. Достаёт параметры из `params`."""
    model_name = params.get("model_name", "v3_1")
    ratio = params.get("ratio", "default")
    resolution = params.get("resolution", "default")
    if pipeline == "brand_t2i":
        prompt = (params.get("prompt") or params.get("text_prompt") or "").strip()
        if not prompt:
            return GenerationJob(
                job_id="", status="failed", error="brand_t2i requires a prompt"
            )
        return await run_brand_text2img(
            client,
            prompt=prompt,
            variant=params.get("variant", "photo"),
            model_name=model_name,
            ratio=ratio,
            resolution=resolution,
            pct_cb=pct_cb,
        )
    if pipeline == "brand_i2i":
        return await run_brand_img2img(
            client,
            init_img_ids=init_img_ids,
            init_img_dims=init_img_dims,
            model_name=model_name,
            ratio=ratio if ratio != "default" else "r_3_4",
            resolution=resolution if resolution != "default" else "k2",
            pct_cb=pct_cb,
        )
    return GenerationJob(
        job_id="", status="failed", error=f"unknown brand pipeline: {pipeline!r}"
    )
