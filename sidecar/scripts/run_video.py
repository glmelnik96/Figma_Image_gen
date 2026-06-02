"""Ручной прогон одной видео-генерации на произвольной Phygital+ ноде.

ЗАЧЕМ:
  Для рекона сценариев sub-project D — погонять каждую модель руками с разными
  входами/параметрами и зафиксировать что именно работает. Каждый прогон пишется
  одной строкой в `runs.jsonl` — потом по этому логу пишутся сценарии.

ОБХОДИТ sidecar: sidecar пока знает только node 94 (Nano Banana). Этот скрипт
ходит напрямую через vendored PhygitalClient — тот же путь что recon_video_nodes.py.

ТРЕБОВАНИЯ:
  - session.json в C:\\Users\\<user>\\AppData\\Local\\PhygitalStudio\\
    (если sidecar поднял Claude — скопировать руками из Packages\\Claude_*\\LocalCache\\)
  - Активный .venv в sidecar/

ЗАПУСК (всё в одну строку):

  # минимум — t2v
  python -m scripts.run_video --node 105 --input prompt="cat in space" --out cat.mp4

  # с файловыми входами (любое количество --input slot=path)
  python -m scripts.run_video --node 121 ^
      --input text_prompt="character dancing" ^
      --input first_frame=./frame_a.png ^
      --input last_frame=./frame_b.png ^
      --param duration=5 ^
      --out kling_dance.mp4

  # массив рефов (повтори --input для одного слота)
  python -m scripts.run_video --node 100 ^
      --input prompt="..." ^
      --input ref_img=./ref1.png ^
      --input ref_img=./ref2.png ^
      --out seedance.mp4

  # узнать какие inputs/params принимает нода — без запуска
  python -m scripts.run_video --node 121 --describe

  # переопределить путь лога
  python -m scripts.run_video --node 105 --input prompt="x" --out x.mp4 --log my_runs.jsonl

ЛОГ (runs.jsonl):
  Каждый прогон — одна JSON-строка с {timestamp, node_id, node_name, inputs, params,
  task_id, status, duration_sec, output_path, error?, raw_status?}. Лог append-only,
  одной командой потом всё извлекается грепом / jq.

ТЕКСТОВЫЕ vs ФАЙЛОВЫЕ inputs:
  Скрипт смотрит схему ноды из /api/v2/nodes/:
    - dataType=text          → строка как есть
    - dataType=image/video/audio  → значение трактуется как ПУТЬ, файл загружается
    - dataType=array         → если несколько --input slot=... — собирается в список
                               (содержимое — пути или строки, в зависимости от itemType)

ПАРАМЫ:
  --param name=value применяется поверх default'ов из схемы. Если не указать —
  идут default-ы. Если указать неизвестное имя — warning + всё равно отправляется.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ssl

import httpx
import truststore
from loguru import logger

_SSL_CTX = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

from app.paths import session_file
from app.phygital_client.api import API_BASE, PhygitalClient
from app.phygital_client.session import Session
from app.services.session_manager import SidecarSessionManager
from app.workflows.image_gen import DONE_STATUSES, FAIL_STATUSES, PENDING_STATUSES

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_LOG = "runs.jsonl"
DEFAULT_POLL = 3.0     # сек между опросами статуса (видео — долго, не дёргаем чаще)
DEFAULT_TIMEOUT = 1800 # 30 минут потолок (avg ~17-25 мин)


# ─────────────────────── session / client ────────────────────────

async def load_session() -> Session:
    path = session_file()
    if not path.exists():
        raise SystemExit(
            f"No session at {path}\n"
            f"  1. python -m scripts.cli auth login\n"
            f"  2. Если Claude — скопировать из %LOCALAPPDATA%\\Packages\\Claude_*\\LocalCache\\Local\\PhygitalStudio\\"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    s = Session(cookies=data["cookies"])
    if data.get("captured_at"):
        s.captured_at = datetime.fromisoformat(data["captured_at"])
    return s


# ─────────────────────── schema fetch ────────────────────────────

async def fetch_node_schema(client: PhygitalClient, node_id: int) -> dict[str, Any]:
    """Достаёт дефиницию конкретной ноды из /api/v2/nodes/."""
    resp = await client.api_get("/api/v2/nodes/")
    resp.raise_for_status()
    data = resp.json()
    nodes = data["results"] if isinstance(data, dict) and "results" in data else data
    for wrapper in nodes:
        nd = wrapper.get("node", {}).get("nodeDefinition") or {}
        if nd.get("id") == node_id:
            return {
                "definition": nd,
                "isAvailable": wrapper.get("isAvailable"),
                "isVisible": wrapper.get("isVisible"),
                "default_price": wrapper.get("default_price"),
            }
    raise SystemExit(f"Node id={node_id} not found in /api/v2/nodes/")


def describe_node(schema: dict[str, Any]) -> None:
    d = schema["definition"]
    print(f"\n=== Node {d['id']}: {d['name']} ({d.get('id_global', '?')}) ===")
    print(f"avg: {d.get('averageTimeInSeconds', '?')}s | price: {schema['default_price']} | available: {schema['isAvailable']} ({schema['isVisible']})")

    print("\nINPUTS:")
    for i in d.get("inputs", []):
        dt = i["dataType"]
        if dt == "array":
            item = (i.get("optionalInfo", {}).get("valueOptions", {}) or {}).get("itemType") or {}
            dt = f"array<{item.get('dataType', '?')}>"
        print(f"  {i['name']:<22} {dt}")

    print("\nPARAMS (default in []):")
    for p in d.get("params", []):
        default = p.get("value", "?")
        opts = p.get("options") or {}
        values = opts.get("values")
        if values:
            opts_str = " enum=" + ",".join(
                str(v.get("value", v.get("name", v))) if isinstance(v, dict) else str(v)
                for v in values
            )
        elif "min" in opts or "max" in opts:
            opts_str = f" range=[{opts.get('min')}, {opts.get('max')}]"
        else:
            opts_str = ""
        print(f"  {p['name']:<22} {p.get('dataType', '?'):<10} [{default!r}]{opts_str}")

    print("\nUSAGE:")
    file_inputs = []
    text_inputs = []
    for i in d.get("inputs", []):
        if i["dataType"] == "text":
            text_inputs.append(i["name"])
        else:
            file_inputs.append(i["name"])
    parts = [f"python -m scripts.run_video --node {d['id']}"]
    for n in text_inputs:
        parts.append(f'--input {n}="..."')
    for n in file_inputs:
        parts.append(f"--input {n}=./file.ext")
    parts.append("--out output.mp4")
    print("  " + " \\\n      ".join(parts))


# ─────────────────────── inputs / payload ────────────────────────

def parse_kv_list(items: list[str], *, label: str) -> dict[str, list[str]]:
    """[`a=1`, `a=2`, `b=x`] → {`a`: [`1`, `2`], `b`: [`x`]}"""
    out: dict[str, list[str]] = defaultdict(list)
    for raw in items:
        if "=" not in raw:
            raise SystemExit(f"--{label} требует формат name=value, получено: {raw!r}")
        k, v = raw.split("=", 1)
        out[k.strip()].append(v)
    return dict(out)


async def upload_files(client: PhygitalClient, paths: list[str]) -> list[int]:
    ids: list[int] = []
    for p in paths:
        path = Path(p).expanduser().resolve()
        if not path.exists():
            raise SystemExit(f"File not found: {path}")
        size = path.stat().st_size
        print(f"  uploading {path.name} ({size/1024:.1f} KB)...", file=sys.stderr)
        file_id = await client.upload_file(str(path))
        print(f"    → file_obj_id={file_id}", file=sys.stderr)
        ids.append(file_id)
    return ids


async def build_inputs(
    client: PhygitalClient,
    schema_inputs: list[dict[str, Any]],
    user_inputs: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Собирает payload['inputs'] из user-данных + схемы. Файлы аплоадит."""
    out: list[dict[str, Any]] = []
    consumed = set()

    for slot in schema_inputs:
        name = slot["name"]
        dt = slot["dataType"]
        provided = user_inputs.get(name, [])

        # array<image|video|audio> ─ список file_obj_ids
        if dt == "array":
            item_dt = (slot.get("optionalInfo", {}).get("valueOptions", {}) or {}).get("itemType", {}).get("dataType", "image")
            if not provided:
                out.append({
                    "name": name, "type": "array", "optional": None,
                    "isModified": False, "value": [],
                    "meta": {"dimensions": []} if item_dt == "image" else {},
                })
            else:
                consumed.add(name)
                file_ids = await upload_files(client, provided)
                out.append({
                    "name": name, "type": "array", "optional": None,
                    "isModified": True, "value": file_ids,
                    "meta": {"dimensions": []} if item_dt == "image" else {},
                })
            continue

        # text ─ строка как есть
        if dt == "text":
            if not provided:
                out.append({"name": name, "type": "text", "optional": None,
                            "isModified": False, "value": "", "meta": {}})
            else:
                consumed.add(name)
                if len(provided) > 1:
                    print(f"WARN: input '{name}' (text) given {len(provided)} times — using last", file=sys.stderr)
                out.append({"name": name, "type": "text", "optional": None,
                            "isModified": True, "value": provided[-1], "meta": {}})
            continue

        # одиночный файл (image|video|audio)
        if dt in ("image", "video", "audio"):
            if not provided:
                out.append({"name": name, "type": dt, "optional": None,
                            "isModified": False, "value": None, "meta": {}})
            else:
                consumed.add(name)
                if len(provided) > 1:
                    print(f"WARN: input '{name}' ({dt}) given {len(provided)} times — using last", file=sys.stderr)
                file_ids = await upload_files(client, [provided[-1]])
                out.append({"name": name, "type": dt, "optional": None,
                            "isModified": True, "value": file_ids[0], "meta": {}})
            continue

        # number / прочее — пробрасываем строкой
        if provided:
            consumed.add(name)
            out.append({"name": name, "type": dt, "optional": None,
                        "isModified": True, "value": provided[-1], "meta": {}})
        else:
            out.append({"name": name, "type": dt, "optional": None,
                        "isModified": False, "value": None, "meta": {}})

    # Warning про неизвестные слоты
    for name in user_inputs.keys() - consumed:
        print(f"WARN: --input {name}=... — нет такого слота в схеме ноды, проигнорирован", file=sys.stderr)
    return out


def build_params(schema_params: list[dict[str, Any]], user_params: dict[str, list[str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen = set()
    for p in schema_params:
        name = p["name"]
        seen.add(name)
        value = p.get("value")
        if name in user_params:
            value = user_params[name][-1]
        out.append({
            "name": name,
            "type": p.get("dataType", "enum"),
            "value": value,
            "meta": {},
        })
    for name in user_params.keys() - seen:
        print(f"WARN: --param {name}=... — нет такого params в схеме, пробрасываю as-is", file=sys.stderr)
        out.append({"name": name, "type": "enum", "value": user_params[name][-1], "meta": {}})
    return out


def build_payload(schema: dict[str, Any], inputs: list[dict[str, Any]], params: list[dict[str, Any]]) -> dict[str, Any]:
    d = schema["definition"]
    return {
        "id": d["id"],
        "inputs": inputs,
        "params": params,
        "outputs": [{"name": o["name"], "type": o["dataType"], "value": ""} for o in d.get("outputs", [])],
    }


def build_config_history(schema: dict[str, Any], inputs: list[dict[str, Any]], params: list[dict[str, Any]]) -> dict[str, Any]:
    """Минималистичный config_history по образцу image_gen.py — generic-mirror схемы."""
    d = schema["definition"]
    node_uuid = str(uuid.uuid4())
    input_socket_group = {}
    for i in inputs:
        input_socket_group[i["name"]] = {
            "name": i["name"],
            "type": i["type"],
            "value": i.get("value"),
            "optionalInfo": {
                "isEnabled": True,
                "mapOfEnabylity": {},
                "originalWorkspaceIds": i.get("value") if i["type"] == "text" else None,
            },
        }

    output_socket_group = []
    for o in d.get("outputs", []):
        item = {"name": o["name"], "dataType": o["dataType"], "optional": None,
                "displayName": None, "value": [] if o["dataType"] == "array" else None}
        if o["dataType"] == "array":
            opt_info = o.get("optionalInfo") or {}
            item["optionalInfo"] = opt_info
        else:
            item["optionalInfo"] = {}
        output_socket_group.append(item)

    node = {
        "globalId": d.get("id_global", ""),
        "name": d.get("name", ""),
        "uuid": node_uuid,
        "taskID": 0,
        "serviceVersion": d.get("version", ""),
        "inputSocketGroup": input_socket_group,
        "outputSocketGroup": output_socket_group,
        "meta": {
            "taskSchema": {
                "id": d["id"],
                "inputs": inputs,
                "params": params,
                "outputs": [{"name": o["name"], "type": o["dataType"], "value": ""} for o in d.get("outputs", [])],
            },
        },
        "params": {
            p["name"]: {
                "name": p["name"],
                "type": p["type"],
                "optionalInfo": {"isEnabled": True, "mapOfEnabylity": {}},
                "value": p["value"],
            }
            for p in params
        },
        "width": 350,
        "position": {"x": 600, "y": 200},
        "connections": [],
        "height": 617,
    }
    return {"nodes": [node], "executedNodeUuid": node_uuid}


# ─────────────────────── poll + download ─────────────────────────

async def poll_task(client: PhygitalClient, task_id: int, *, timeout: float, poll: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        data = await client.task_status(task_id)
        status = (data.get("status") or "").lower()
        if status != last:
            print(f"  task {task_id}: {status} (pos={data.get('position')}, progress={data.get('progress')})", file=sys.stderr)
            last = status
        if status in DONE_STATUSES:
            return {"status": "completed", "data": data}
        if status in FAIL_STATUSES:
            return {"status": "failed", "data": data,
                    "error": data.get("error_message") or f"status={status}"}
        await asyncio.sleep(poll)
    return {"status": "failed", "data": {}, "error": "timeout"}


def extract_link_ids(outputs: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for out in outputs or []:
        raw = out.get("id")
        if isinstance(raw, list):
            ids.extend(int(x) for x in raw)
        elif isinstance(raw, int):
            ids.append(raw)
    return ids


async def download(url: str, dest: Path) -> int:
    async with httpx.AsyncClient(verify=_SSL_CTX, timeout=300, follow_redirects=True) as cli:
        async with cli.stream("GET", url) as r:
            r.raise_for_status()
            with dest.open("wb") as f:
                size = 0
                async for chunk in r.aiter_bytes(64 * 1024):
                    f.write(chunk)
                    size += len(chunk)
    return size


# ─────────────────────── log writer ──────────────────────────────

def write_log(log_path: Path, record: dict[str, Any]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────── main ────────────────────────────────────

async def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run one Phygital+ video generation (or any node) and log it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--node", type=int, required=True, help="node_id (напр. 121 = Kling Omni)")
    ap.add_argument("--input", action="append", default=[],
                    help="slot=value | slot=path/to/file (повторяй для массивов)")
    ap.add_argument("--param", action="append", default=[],
                    help="name=value, переопределяет дефолт из схемы (повторяй для разных)")
    ap.add_argument("--out", help="куда сохранить результирующий файл")
    ap.add_argument("--log", default=DEFAULT_LOG, help=f"JSONL-лог прогонов (default: {DEFAULT_LOG})")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help=f"sec, default {DEFAULT_TIMEOUT}")
    ap.add_argument("--poll", type=float, default=DEFAULT_POLL, help=f"sec, default {DEFAULT_POLL}")
    ap.add_argument("--describe", action="store_true", help="показать inputs/params ноды и выйти")
    ap.add_argument("--dry-run", action="store_true", help="собрать payload, напечатать, не отправлять")
    args = ap.parse_args()

    user_inputs = parse_kv_list(args.input, label="input")
    user_params = parse_kv_list(args.param, label="param")

    session = await load_session()
    ttl = session.jwt_ttl_seconds()
    print(f"session: jwt_ttl={ttl}s, cookies={len(session.cookies)}", file=sys.stderr)
    if ttl is None or ttl < 60:
        print("WARN: JWT TTL мал — будет авто-refresh при первом запросе", file=sys.stderr)

    manager = SidecarSessionManager(session_file())
    async with PhygitalClient(session=session, session_manager=manager) as client:
        print(f"fetching schema for node {args.node}...", file=sys.stderr)
        schema = await fetch_node_schema(client, args.node)

        if args.describe:
            describe_node(schema)
            return

        if not args.out and not args.dry_run:
            raise SystemExit("--out обязателен (или --dry-run)")

        d = schema["definition"]
        print(f"node {d['id']} '{d['name']}' avg={d.get('averageTimeInSeconds')}s price={schema['default_price']}", file=sys.stderr)
        print(f"uploading files / building payload...", file=sys.stderr)
        inputs = await build_inputs(client, d.get("inputs", []), user_inputs)
        params = build_params(d.get("params", []), user_params)
        payload = build_payload(schema, inputs, params)
        config = build_config_history(schema, inputs, params)

        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "node_id": d["id"],
            "node_name": d["name"],
            "user_inputs": user_inputs,
            "user_params": user_params,
            "payload": payload,
        }

        if args.dry_run:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return

        started = time.monotonic()
        try:
            task_id = await client.submit_task(payload)
            print(f"task_id={task_id}", file=sys.stderr)
            await client.post_config_history(task_id, config)

            result = await poll_task(client, task_id, timeout=args.timeout, poll=args.poll)
            duration = round(time.monotonic() - started, 1)
            record["task_id"] = task_id
            record["duration_sec"] = duration
            record["status"] = result["status"]

            if result["status"] == "failed":
                record["error"] = result.get("error")
                record["raw_status"] = result["data"]
                write_log(Path(args.log), record)
                raise SystemExit(f"FAILED after {duration}s: {result.get('error')}")

            link_ids = extract_link_ids(result["data"].get("outputs") or [])
            if not link_ids:
                record["error"] = "no link_ids in completed task"
                record["raw_status"] = result["data"]
                write_log(Path(args.log), record)
                raise SystemExit("completed but no link_ids")

            links = await client.get_download_links(link_ids)
            urls = [l["download_link"] for l in links if l.get("download_link")]
            record["download_urls"] = urls

            if not urls:
                record["error"] = "no download URLs"
                write_log(Path(args.log), record)
                raise SystemExit("no download URLs")

            dest = Path(args.out).expanduser().resolve()
            dest.parent.mkdir(parents=True, exist_ok=True)
            print(f"downloading → {dest}", file=sys.stderr)
            size = await download(urls[0], dest)
            record["output_path"] = str(dest)
            record["output_size"] = size
            write_log(Path(args.log), record)
            print(f"OK: {dest} ({size/1024/1024:.2f} MB), {duration}s total. Logged to {args.log}", file=sys.stderr)

        except Exception as e:
            record["status"] = "exception"
            record["error"] = repr(e)
            write_log(Path(args.log), record)
            raise


if __name__ == "__main__":
    asyncio.run(main())
