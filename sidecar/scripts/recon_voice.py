"""Manual live-capture для voice/TTS нод backend'а.

Открывает Chromium с persistent-профилем sidecar'а (тот же, что у
`auth_recon` / `recon_t2v` — логин уже там, повторно логиниться не нужно),
пишет HAR со всеми XHR/Fetch + WS-фреймы в JSONL. Пользователь сам кликает
нужные voice-ноды в backend-UI; по нажатию Enter в терминале — закрывает
браузер и дампит storage.

Цель: захватить РЕАЛЬНЫЕ submit-payloads / config_history / outputs для
voice generation (TTS, voice clone, и т.д.), чтобы потом добавить
новый набор сценариев в sidecar (`app/workflows/voice_*.py`,
новая `Category.VOICE` в taxonomy) и Music/Voice таб в CEP.

Запуск:
    cd sidecar
    python -m scripts.recon_voice

Что нужно сделать в открывшемся Chromium:

    Для КАЖДОЙ voice-ноды, которую хочешь добавить в панель — сделай
    одну минимальную генерацию (самые дешёвые параметры) и дождись
    полного завершения (status -> completed + появление результата в
    UI). Чем больше параметров переключишь между запусками — тем лучше
    видно schema-варианты в HAR.

    Минимум на каждую ноду:
      - один TTS (text -> speech) с дефолтным голосом
      - если есть voice clone / reference voice — один прогон с
        загрузкой короткого audio-сэмпла (5-10 сек), чтобы поймать
        upload-payload
      - если есть несколько моделей/языков в enum — переключи хотя бы
        раз, чтобы зафиксировать config-варианты

    prompt/script — любой нейтральный короткий текст, например:
        "Hello, this is a test recording for prompt enhancement."

    Если какая-то нода требует обязательный input (reference audio,
    язык) и блокирует submit без него — это тоже сигнал, попробуй
    кликнуть submit чтобы поймать ошибку в HAR.

После завершения всех генераций — вернись в терминал и нажми Enter.
В терминале также можно отметить какие именно ноды отработал, чтобы
потом я знал на что смотреть.

Дамп будет в `recon-captures/<ts>-voice-manual/`:
    - phygital.har        — все XHR/Fetch + bodies
    - ws.jsonl            — WebSocket-фреймы
    - storage.json        — cookies + localStorage
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from playwright.async_api import WebSocket, async_playwright

from app.paths import user_data_dir

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


TARGET_URL = "https://app.phygital.plus/"
CAPTURES_ROOT = Path("recon-captures")

TASK_LIST = """
=======================================================================
 MANUAL VOICE RECON — задачи в backend-UI:

 Для КАЖДОЙ voice/TTS-ноды, которую хотим добавить в панель:
   1) одна минимальная TTS-генерация (дефолтный голос, короткий текст)
   2) если есть voice clone / reference audio — один прогон с
      загрузкой короткого audio-сэмпла (поймать upload)
   3) если есть enum моделей/языков — переключить хотя бы раз

 prompt (любой короткий нейтральный):
   "Hello, this is a test recording for prompt enhancement."

 Если submit заблокирован в UI без обязательного input — попробуй всё
 равно кликнуть, чтобы поймать ошибку в HAR. Если совсем нельзя —
 пропусти и отметь в терминале.

 Когда все нужные ноды отработали (или отметил пропуски) — вернись
 сюда и нажми Enter.
=======================================================================
"""


async def dump_storage(context, page, path: Path) -> None:
    """Снимаем cookies + localStorage + sessionStorage активной страницы."""
    cookies = await context.cookies()
    try:
        local_storage = await page.evaluate(
            "() => Object.fromEntries(Object.entries(localStorage))"
        )
    except Exception:
        local_storage = {}
    try:
        session_storage = await page.evaluate(
            "() => Object.fromEntries(Object.entries(sessionStorage))"
        )
    except Exception:
        session_storage = {}
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "url": page.url,
        "cookies": cookies,
        "localStorage": local_storage,
        "sessionStorage": session_storage,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(f"Storage dumped -> {path}")


def attach_ws_logger(ws: WebSocket, ws_log_path: Path) -> None:
    """Логируем все WebSocket-фреймы в JSONL (HAR не всегда сохраняет тела)."""
    logger.info(f"WS opened: {ws.url}")

    def write(direction: str, payload) -> None:
        try:
            data = payload if isinstance(payload, str) else f"<binary:{len(payload)}>"
        except Exception:
            data = "<unreadable>"
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "url": ws.url,
            "dir": direction,
            "payload": data,
        }
        with ws_log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    ws.on("framesent", lambda p: write("send", p))
    ws.on("framereceived", lambda p: write("recv", p))
    ws.on("close", lambda: logger.info(f"WS closed: {ws.url}"))


async def stdin_wait() -> None:
    """Ждём Enter в stdin без блокировки event loop."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, sys.stdin.readline)


async def main() -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    save_dir = CAPTURES_ROOT / f"{ts}-voice-manual"
    save_dir.mkdir(parents=True, exist_ok=True)

    har_path = save_dir / "phygital.har"
    ws_log_path = save_dir / "ws.jsonl"
    storage_path = save_dir / "storage.json"

    profile_dir = user_data_dir()
    profile_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"profile -> {profile_dir}")
    logger.info(f"HAR     -> {har_path}")
    logger.info(f"WS      -> {ws_log_path}")
    logger.info(f"STOR    -> {storage_path}")

    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            viewport={"width": 1440, "height": 900},
            record_har_path=str(har_path),
            record_har_content="embed",
            record_har_mode="full",
            args=["--disable-blink-features=AutomationControlled"],
        )

        # WS-перехватчик на все будущие страницы
        context.on(
            "page",
            lambda p: p.on("websocket", lambda ws: attach_ws_logger(ws, ws_log_path)),
        )

        page = context.pages[0] if context.pages else await context.new_page()
        page.on("websocket", lambda ws: attach_ws_logger(ws, ws_log_path))

        await page.goto(TARGET_URL, wait_until="domcontentloaded")

        print(TASK_LIST)

        await stdin_wait()

        # Берём актуальную активную страницу — юзер мог переключиться
        active = context.pages[-1] if context.pages else page
        try:
            await dump_storage(context, active, storage_path)
        except Exception as e:
            logger.error(f"Storage dump failed: {e}")

        await context.close()
        logger.success(f"Done. Captures saved to {save_dir.absolute()}")
        print(f"\nResult: {save_dir.absolute()}")


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    asyncio.run(main())
