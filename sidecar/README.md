# Adobe AI Studio — Sidecar

Локальный Python sidecar (FastAPI на `127.0.0.1:8765`), который мостит backend API в Adobe CEP-панели.

## Установка (Windows)

```cmd
cd sidecar
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium
```

## Vendor sync

`app/phygital_client/` и `app/workflows/{base,image_gen}.py` — vendored backend-клиент. Никогда не редактируй вручную.

Ресинк:
```cmd
python -m scripts.sync_from_bot --apply
```

Текущий vendored commit — в `app/phygital_client/__init__.py` (`SOURCE_COMMIT`).

## Запуск

```cmd
python -m app.main
```

Sidecar поднимается на `http://127.0.0.1:8765`. Логи — stdout + `%LOCALAPPDATA%\PhygitalStudio\logs\sidecar.log`.

## CLI

```cmd
python -m scripts.cli status                              # GET /health
python -m scripts.cli auth login                          # POST /auth/recon -> откроет браузер
python -m scripts.cli nodes                               # GET /nodes
python -m scripts.cli generate --node 94 --prompt "..." --out out.png
python -m scripts.cli jobs list
python -m scripts.cli jobs cancel <job_id>

# Asset cache (sha256-dedup uploads, переиспользуются между job'ами)
python -m scripts.cli assets upload ./input.png        # → sha256 + file_obj_id
python -m scripts.cli assets list
python -m scripts.cli assets clear

# Видео-модели и сценарии
python -m scripts.cli video models                     # GET /nodes/video
python -m scripts.cli video scenarios --node 100       # required slots по сценарию
```

## HTTP API

| Method | Path | Body | Response |
|---|---|---|---|
| GET | `/health` | — | `{ok, session_age_sec, jwt_ttl_sec, active_jobs}` |
| POST | `/auth/recon` | — | `{started: true}` или 409 `recon_in_progress` |
| GET | `/nodes` | — | `{nodes: [{id, name, workflow_class}]}` |
| POST | `/jobs` | `{node_id, params, init_files?}` | `{job_id}` |
| POST | `/jobs/preview-cost` | `{node_id, params}` | `{credits, currency}` (через `client.get_credits_price`) |
| GET | `/jobs` | `?status=&limit=` | `{jobs: [...]}` |
| GET | `/jobs/{id}` | — | `{job_id, status, progress, result_paths, error, ...}` |
| GET | `/jobs/{id}/download` | `?index=0` | bytes |
| DELETE | `/jobs/{id}` | — | 204 |
| GET | `/nodes/video` | — | `{nodes: [{node_id, model, scenarios, slots, scenario_slots, default_params}]}` |
| POST | `/assets` | multipart `file=@path` | `{sha256, file_obj_id, mime, size}` |
| GET | `/assets` | — | `{assets: [...]}` |
| DELETE | `/assets/{sha256}` | — | 204 |
| DELETE | `/assets?all=true` | — | 204 |

## Видео-генерация

Четыре видео-ноды + Nano Banana (94) как image-edit upstream. Каждая видео-нода поддерживает несколько сценариев — обязательные slots зависят от сценария (см. `GET /nodes/video` или `cli video scenarios --node N`).

| node_id | Модель | Сценарии |
|---|---|---|
| 74  | Kling Video       | `start_prompt`, `start_end_prompt`, `elements_prompt` |
| 100 | Seedance Video    | `start_prompt`, `start_end_prompt`, `ref_prompt`, `ref_prompt_video` |
| 121 | Kling Omni        | `start_prompt`, `start_end_prompt`, `elements_prompt`, `elements_prompt_video` |
| 124 | Kling Motion      | `char_video_prompt` (с `character_orientation ∈ {video, image}`) |

Init-файлы кладутся в `init_files` (sha256-dedup через `/assets` происходит автоматически), payload-параметры — в `params`:

```bash
curl -X POST http://127.0.0.1:8765/jobs \
  -H 'Content-Type: application/json' \
  -d '{
    "node_id": 100,
    "params": {
      "prompt": "slow camera push-in, cinematic",
      "scenario": "start_end_prompt",
      "seed": 42
    },
    "init_files": {
      "start_img": "C:/path/to/start.png",
      "end_frame": "C:/path/to/end.png"
    }
  }'
```

Один и тот же файл, переданный в несколько slot'ов или несколько job'ов, заливается на backend один раз (кэш по sha256 в `asset_cache.jsonl`).

## MSIX sandbox (Windows)

Claude Code на Windows в MSIX-режиме виртуализирует `%LOCALAPPDATA%` — процессы, запущенные **из агента**, пишут в `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\…`, а CEP-панели и обычные PowerShell-сессии этого не видят. **Sidecar надо запускать самому пользователю** (`python -m app.main` в обычном терминале), не через агента.

## Тесты

```cmd
pytest -m "not live" -v          # юнит, в CI
pytest -m live -v -s             # требует sidecar + сессии
```

## Состояние на диске

Всё лежит в `%LOCALAPPDATA%\PhygitalStudio\` (Windows) или `~/Library/Application Support/PhygitalStudio/` (Mac).

| Файл | Что |
|---|---|
| `session.json` | backend cookies + JWT |
| `user_data/` | Playwright persistent profile |
| `downloads/<job_id>/` | Скачанные результаты |
| `uploads/<session_id>/` | (для sub-project D) загруженные init-картинки |
| `jobs.jsonl` | Append-only журнал статусов задач |
| `logs/sidecar.log` | Логи (ротируются 10MB x 5) |

## Архитектура и спек

- [`../docs/superpowers/specs/2026-05-21-sidecar-mvp-design.md`](../docs/superpowers/specs/2026-05-21-sidecar-mvp-design.md)
- [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md)
- [`../docs/AUTH.md`](../docs/AUTH.md)
