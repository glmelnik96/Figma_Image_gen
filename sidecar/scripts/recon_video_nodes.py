"""Рекон по видео-нодам Phygital+ — выкачивает свежий каталог через живую сессию,
фильтрует video-output + available + visible, и печатает полную схему каждой:
inputs / outputs / params (с options + default values).

ЗАЧЕМ:
  nodes_dump.json в Phygital-bot — снимок от 2026-05-17 (статичный, без params).
  Этот скрипт делает то же самое, но ЖИВО и С params, чтобы при выборе модели
  для sub-project D было видно ВСЁ что Phygital+ умеет крутить.

ТРЕБОВАНИЯ:
  - Валидная Phygital-сессия в %LOCALAPPDATA%\\PhygitalStudio\\session.json
    (получить через `python -m scripts.cli auth login`).
  - Sidecar НЕ обязателен — скрипт ходит напрямую через vendored PhygitalClient.

ЗАПУСК:
  cd sidecar
  python -m scripts.recon_video_nodes                  # все 7 живых видео-нод
  python -m scripts.recon_video_nodes --ids 121,105    # конкретные id
  python -m scripts.recon_video_nodes --all-video      # включая isAvailable=false
  python -m scripts.recon_video_nodes --raw out.json   # сырой JSON в файл
  python -m scripts.recon_video_nodes --md  out.md     # markdown для редактирования

Markdown-выход — основа для сценариев sub-project D: открыл, выкинул лишние модели,
заполнил блоки СЦЕНАРИЙ.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from app.paths import session_file
from app.phygital_client.api import PhygitalClient
from app.phygital_client.session import Session
from app.services.session_manager import SidecarSessionManager

# Windows UTF-8
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

NODES_PATH = "/api/v2/nodes/"  # подтверждённый эндпоинт каталога


async def load_session() -> Session:
    """Подтянуть session.json с диска."""
    path = session_file()
    if not path.exists():
        raise SystemExit(
            f"No session at {path}\n"
            f"Run `python -m scripts.cli auth login` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    from datetime import datetime
    captured = data.get("captured_at")
    s = Session(cookies=data["cookies"])
    if captured:
        s.captured_at = datetime.fromisoformat(captured)
    return s


async def fetch_nodes(client: PhygitalClient) -> list[dict[str, Any]]:
    """GET /api/v2/nodes/ — полный каталог. Может вернуть list ИЛИ {results: [...]}."""
    resp = await client.api_get(NODES_PATH)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    if isinstance(data, list):
        return data
    raise RuntimeError(f"Unexpected /nodes shape: {type(data).__name__} keys={list(data)[:5] if isinstance(data, dict) else '-'}")


def has_video_output(node_def: dict[str, Any]) -> bool:
    return any(o.get("dataType") == "video" for o in node_def.get("outputs", []))


def is_live(wrapper: dict[str, Any]) -> bool:
    return bool(wrapper.get("isAvailable")) and wrapper.get("isVisible") == "visible"


def filter_video(nodes: list[dict[str, Any]], *, include_unavailable: bool, ids: set[int] | None) -> list[dict[str, Any]]:
    out = []
    for n in nodes:
        d = n.get("node", {}).get("nodeDefinition") or {}
        if not has_video_output(d):
            continue
        if ids is not None:
            if d.get("id") not in ids:
                continue
        elif not include_unavailable and not is_live(n):
            continue
        out.append(n)
    out.sort(key=lambda x: x["node"]["nodeDefinition"].get("id", 0))
    return out


def fmt_param_options(p: dict[str, Any]) -> str:
    opts = p.get("options") or {}
    values = opts.get("values")
    if values and isinstance(values, list):
        names = []
        for v in values:
            if isinstance(v, dict):
                names.append(str(v.get("value", v.get("name", v))))
            else:
                names.append(str(v))
        return "enum[" + ", ".join(names) + "]"
    if "min" in opts or "max" in opts:
        rng = f"min={opts.get('min')} max={opts.get('max')}"
        step = opts.get("step")
        if step is not None:
            rng += f" step={step}"
        return rng
    if isinstance(opts, dict) and opts:
        # на всякий случай — сырой дамп ключей options если ничего знакомого
        return f"options={list(opts.keys())}"
    return ""


def print_card_text(n: dict[str, Any]) -> None:
    d = n["node"]["nodeDefinition"]
    print()
    print("=" * 78)
    flag = "[LIVE]" if is_live(n) else "[----]"
    print(f"{flag}  id={d['id']}  name={d['name']}")
    print(f"       id_global: {d.get('id_global', '?')}")
    print(f"       avg: {d.get('averageTimeInSeconds', '?')}s    price: {n.get('default_price', '?')}    version: {d.get('version', '?')}")
    desc = d.get("description")
    if desc and desc != "none":
        print(f"       desc: {desc}")

    inputs = d.get("inputs", [])
    print(f"\n  INPUTS ({len(inputs)}):")
    if not inputs:
        print("    (none)")
    for i in inputs:
        name = i.get("name", "?")
        dt = i.get("dataType", "?")
        item_type = ""
        if dt == "array":
            opt = i.get("optionalInfo") or {}
            item = (opt.get("valueOptions") or {}).get("itemType") or {}
            item_type = f"<{item.get('dataType', '?')}>"
        print(f"    - {name:<22} {dt}{item_type}")

    outputs = d.get("outputs", [])
    print(f"\n  OUTPUTS ({len(outputs)}):")
    for o in outputs:
        print(f"    - {o.get('name', '?'):<22} {o.get('dataType', '?')}")

    params = d.get("params", [])
    print(f"\n  PARAMS ({len(params)}):")
    if not params:
        print("    (none)")
    for p in params:
        name = p.get("name", "?")
        dt = p.get("dataType", "?")
        default = p.get("value", "?")
        opts_str = fmt_param_options(p)
        line = f"    - {name:<22} {dt:<10} default={default!r}"
        if opts_str:
            line += f"    {opts_str}"
        print(line)


def render_card_md(n: dict[str, Any]) -> str:
    d = n["node"]["nodeDefinition"]
    nid = d["id"]
    name = d["name"]
    out = []
    out.append(f"### Модель {nid} — {name}")
    out.append(f"- avg: {d.get('averageTimeInSeconds', '?')}s | цена: ${n.get('default_price', '?')} | version: {d.get('version', '?')}")
    if d.get("description") and d["description"] != "none":
        out.append(f"- desc: {d['description']}")
    out.append("")
    out.append("**Inputs:**")
    for i in d.get("inputs", []):
        name_i = i.get("name", "?")
        dt = i.get("dataType", "?")
        item_type = ""
        if dt == "array":
            opt = i.get("optionalInfo") or {}
            item = (opt.get("valueOptions") or {}).get("itemType") or {}
            item_type = f" of {item.get('dataType', '?')}"
        out.append(f"- `{name_i}` ({dt}{item_type})")
    out.append("")
    out.append("**Outputs:**")
    for o in d.get("outputs", []):
        out.append(f"- `{o.get('name', '?')}` ({o.get('dataType', '?')})")
    out.append("")
    out.append("**Params (default + options):**")
    if not d.get("params"):
        out.append("- (none)")
    for p in d.get("params", []):
        name_p = p.get("name", "?")
        dt = p.get("dataType", "?")
        default = p.get("value", "?")
        opts_str = fmt_param_options(p)
        line = f"- `{name_p}` — {dt}, default={default!r}"
        if opts_str:
            line += f", {opts_str}"
        out.append(line)
    out.append("")
    out.append("**СЦЕНАРИЙ 1:**")
    out.append("```")
    out.append("Триггер:        <что юзер делает в Pr/AE>")
    out.append("Adobe surface:  <Pr | AE>")
    out.append("Что выделено:   <напр. 2 PNG-слоя в AE, или клип на timeline Pr>")
    out.append("Inputs (slot → откуда):")
    for i in d.get("inputs", []):
        out.append(f"  - {i.get('name', '?')}: <откуда брать>")
    out.append("Params overrides (default-ы выше):")
    out.append("  - <param>: <value>")
    out.append("Output:")
    out.append("  - формат: <mp4 / webm>")
    out.append("  - куда:   <auto-import в bin / auto-place на playhead / только download>")
    out.append("Edge cases:")
    out.append("  - <что блокирует кнопку>")
    out.append("```")
    out.append("")
    return "\n".join(out)


async def main() -> None:
    ap = argparse.ArgumentParser(description="Recon Phygital+ video nodes (live)")
    ap.add_argument("--ids", help="comma-separated node ids (overrides --all-video filter)")
    ap.add_argument("--all-video", action="store_true", help="включая isAvailable=false / invisible")
    ap.add_argument("--raw", metavar="PATH", help="дамп raw JSON отобранных нод в файл")
    ap.add_argument("--md", metavar="PATH", help="markdown с шаблонами сценариев в файл")
    args = ap.parse_args()

    ids: set[int] | None = None
    if args.ids:
        ids = {int(x.strip()) for x in args.ids.split(",") if x.strip()}

    session = await load_session()
    ttl = session.jwt_ttl_seconds()
    print(f"session ok: jwt_ttl={ttl}s, cookies={len(session.cookies)}", file=sys.stderr)
    if ttl is None or ttl < 60:
        print("WARNING: JWT TTL очень мал или None — refresh может потребоваться по ходу", file=sys.stderr)

    manager = SidecarSessionManager(session_file())
    async with PhygitalClient(session=session, session_manager=manager) as client:
        print("fetching /api/v2/nodes/ ...", file=sys.stderr)
        nodes = await fetch_nodes(client)
        print(f"got {len(nodes)} nodes total", file=sys.stderr)

    selected = filter_video(nodes, include_unavailable=args.all_video, ids=ids)
    print(f"video-output nodes matching filter: {len(selected)}", file=sys.stderr)

    # stdout pretty-print
    for n in selected:
        print_card_text(n)

    # raw json dump
    if args.raw:
        Path(args.raw).write_text(json.dumps(selected, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nraw dump → {args.raw}", file=sys.stderr)

    # markdown
    if args.md:
        md_lines = []
        md_lines.append("# Video Recon — sub-project D (live dump)\n")
        md_lines.append(f"> Снято: live из `/api/v2/nodes/`. Нод в выборке: {len(selected)}.\n")
        md_lines.append("> **Что делать:** удали лишние модели, оставь 2, заполни блоки СЦЕНАРИЙ.\n")
        md_lines.append("\n## Глобальные решения по sub-project D\n")
        md_lines.append("- Концепция: [одной фразой]\n- Где живёт UI: [ ] Pr / [ ] AE / [ ] обе\n- Кто инициирует: [ ] кнопка / [ ] context menu / [ ] drag-drop\n- Куда падает результат: [ ] auto-import / [ ] только download\n- Per-job cost confirm: [ ] да / [ ] нет\n- Concurrency для видео: [пусто = N=5 общий]\n")
        md_lines.append("\n---\n")
        for n in selected:
            md_lines.append(render_card_md(n))
            md_lines.append("---\n")
        md_lines.append("\n## Свободная зона\n\n[мысли вне формата]\n")
        Path(args.md).write_text("\n".join(md_lines), encoding="utf-8")
        print(f"markdown → {args.md}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
