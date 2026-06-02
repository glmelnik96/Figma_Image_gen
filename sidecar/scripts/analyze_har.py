"""Стрим-разбор большого HAR'а от recon_capture.

Печатает по каждому submit + config_history + upload что было послано/получено,
группируя по task_id. ВЫХОД — компактный summary, чтобы не утопиться в 666 МБ.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import ijson

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


INTERESTING_PATHS = (
    "/api/v2/tasks/",                               # submit (POST) + status (GET /queue-position/)
    "/api/v2/tasks/config_history",                 # config
    "/api/v2/storage-object/storage-object",        # uploads + download-links
    "/api/v2/nodes/get_credits_price",              # price calc
)


def short(s: str, n: int = 500) -> str:
    return s if len(s) <= n else s[:n] + f"...<+{len(s)-n} chars>"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("har", help="path to phygital.har")
    ap.add_argument("--full-payloads", action="store_true", help="печатать ВЕСЬ payload submit/config")
    ap.add_argument("--dump", metavar="DIR", help="сохранить каждый submit/config/price отдельным JSON в DIR")
    args = ap.parse_args()

    har_path = Path(args.har).resolve()
    dump_dir = Path(args.dump).resolve() if args.dump else None
    if dump_dir:
        dump_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    n_total = 0
    print(f"streaming {har_path} ({har_path.stat().st_size/1024/1024:.1f} MB)...", file=sys.stderr)

    with har_path.open("rb") as f:
        for entry in ijson.items(f, "log.entries.item"):
            n_total += 1
            url = entry.get("request", {}).get("url", "")
            if not any(p in url for p in INTERESTING_PATHS):
                continue
            entries.append(entry)
            if n_total % 1000 == 0:
                print(f"  scanned {n_total} entries, kept {len(entries)}", file=sys.stderr)

    print(f"scanned {n_total} total HTTP entries, kept {len(entries)} relevant\n", file=sys.stderr)

    # Группировка
    submits: list[dict] = []
    configs: list[dict] = []
    uploads: list[dict] = []
    prices: list[dict] = []
    statuses: dict[str, list[dict]] = defaultdict(list)
    download_links: list[dict] = []

    for e in entries:
        method = e["request"]["method"]
        url = e["request"]["url"]
        status_code = e["response"]["status"]
        if "/tasks/config_history" in url and method == "POST":
            configs.append(e)
        elif "/tasks/queue-position/" in url and method == "GET":
            # extract task id
            tid = url.rsplit("/", 1)[-1].split("?")[0]
            statuses[tid].append(e)
        elif url.rstrip("/").endswith("/api/v2/tasks") and method == "POST":
            submits.append(e)
        elif "/storage-object/storage-object/download-links" in url:
            download_links.append(e)
        elif "/storage-object/storage-object" in url and method == "POST":
            uploads.append(e)
        elif "/get_credits_price" in url:
            prices.append(e)

    print(f"=== SUMMARY ===", file=sys.stderr)
    print(f"  submits:      {len(submits)}", file=sys.stderr)
    print(f"  config_hist:  {len(configs)}", file=sys.stderr)
    print(f"  uploads:      {len(uploads)}", file=sys.stderr)
    print(f"  prices:       {len(prices)}", file=sys.stderr)
    print(f"  status polls: {sum(len(v) for v in statuses.values())} for {len(statuses)} unique task_ids", file=sys.stderr)
    print(f"  download_lnk: {len(download_links)}", file=sys.stderr)
    print(file=sys.stderr)

    # Печать submits
    for i, e in enumerate(submits):
        try:
            body = e["request"].get("postData", {}).get("text", "")
            parsed = json.loads(body) if body else {}
            schema_id = parsed.get("id")
            inputs = parsed.get("inputs", [])
            params = parsed.get("params", [])
            resp_text = e["response"].get("content", {}).get("text", "")
            task_id = None
            try:
                rj = json.loads(resp_text) if resp_text else {}
                # Phygital ответ — int task_id напрямую, либо {id: ...}
                if isinstance(rj, int):
                    task_id = rj
                elif isinstance(rj, dict):
                    task_id = rj.get("id") or rj.get("task_id")
            except Exception:
                pass

            print(f"--- SUBMIT #{i+1}  schema_id={schema_id}  → task_id={task_id} ---")
            print("INPUTS:")
            for inp in inputs:
                n, t, v = inp.get("name"), inp.get("type"), inp.get("value")
                mod = inp.get("isModified", False)
                marker = "*" if mod else " "
                if isinstance(v, str) and len(v) > 120:
                    v = v[:120] + "..."
                print(f"  {marker} {n:<22} {t:<8} = {v!r}")
            print("PARAMS:")
            for p in params:
                print(f"    {p.get('name'):<22} = {p.get('value')!r}")

            if args.full_payloads:
                print("FULL PAYLOAD:")
                print(json.dumps(parsed, indent=2, ensure_ascii=False))

            if dump_dir:
                (dump_dir / f"submit_{i+1:02d}_schema{schema_id}_task{task_id}.json").write_text(
                    json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
                )

            print()
        except Exception as ex:
            print(f"  submit #{i+1} parse failed: {ex}")

    # config_history (краткий)
    print(f"\n=== CONFIG_HISTORY entries: {len(configs)} ===", file=sys.stderr)
    for i, e in enumerate(configs):
        try:
            body = e["request"].get("postData", {}).get("text", "")
            parsed = json.loads(body) if body else {}
            tid = parsed.get("taskId")
            cfg = parsed.get("config", {})
            nodes = cfg.get("nodes", []) if isinstance(cfg, dict) else []
            schemas = [n.get("meta", {}).get("taskSchema", {}).get("id") for n in nodes]
            print(f"  CFG #{i+1}  taskId={tid}  schemas={schemas}  nodes_in_graph={len(nodes)}")
            if dump_dir:
                (dump_dir / f"config_{i+1:02d}_task{tid}.json").write_text(
                    json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        except Exception as ex:
            print(f"  cfg #{i+1} parse failed: {ex}")

    # uploads summary
    if uploads:
        print(f"\n=== UPLOADS: {len(uploads)} ===", file=sys.stderr)
        for i, e in enumerate(uploads):
            try:
                resp_text = e["response"].get("content", {}).get("text", "")
                rj = json.loads(resp_text) if resp_text else {}
                fid = rj if isinstance(rj, int) else (rj.get("id") if isinstance(rj, dict) else None)
                # размер из request headers
                size_hdr = next((h["value"] for h in e["request"].get("headers", []) if h["name"].lower() == "content-length"), "?")
                print(f"  UP  #{i+1}  size={size_hdr}  → file_obj_id={fid}")
            except Exception as ex:
                print(f"  up #{i+1} parse failed: {ex}")

    # download_links (краткий)
    if download_links:
        print(f"\n=== DOWNLOAD-LINKS: {len(download_links)} ===", file=sys.stderr)
        for i, e in enumerate(download_links):
            try:
                req_body = e["request"].get("postData", {}).get("text", "")
                rb = json.loads(req_body) if req_body else {}
                ids = rb.get("ids") or rb.get("link_ids") or rb
                resp_text = e["response"].get("content", {}).get("text", "")
                rj = json.loads(resp_text) if resp_text else {}
                n_links = len(rj) if isinstance(rj, list) else "?"
                print(f"  DL  #{i+1}  requested_ids={ids}  → {n_links} links")
            except Exception as ex:
                print(f"  dl #{i+1} parse failed: {ex}")

    if dump_dir:
        print(f"\nFull payloads dumped to: {dump_dir}", file=sys.stderr)


if __name__ == "__main__":
    main()
