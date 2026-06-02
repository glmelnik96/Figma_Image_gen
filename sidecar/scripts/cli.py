"""CLI обёртка над HTTP API sidecar.

Использование:
  python -m scripts.cli status
  python -m scripts.cli auth login
  python -m scripts.cli nodes
  python -m scripts.cli generate --node 94 --prompt "cat in a hat" --out ./out.png
  python -m scripts.cli jobs list
  python -m scripts.cli jobs cancel <job_id>

Все запросы идут на http://127.0.0.1:8765 (sidecar должен быть поднят
отдельно через `python -m app.main`).
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

# Windows: stdout в utf-8, чтобы кириллица не падала в cp866 консоли
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8765"


async def cmd_status(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        try:
            r = await c.get("/health")
        except httpx.RequestError as e:
            print(f"sidecar not reachable: {e}")
            return 2
    if r.status_code != 200:
        print(f"sidecar not reachable: {r.status_code}")
        return 2
    h = r.json()
    print(f"sidecar OK    session_age={h['session_age_sec']}    jwt_ttl={h['jwt_ttl_sec']}    active_jobs={h['active_jobs']}")
    return 0


async def cmd_auth_login(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.post("/auth/recon")
        if r.status_code == 409:
            print("recon already in progress -- wait or restart sidecar")
            return 2
        if r.status_code != 200:
            print(f"recon trigger failed: {r.status_code} {r.text}")
            return 2
        print("Browser opened. Залогинься в Phygital+ -- sidecar дождётся cookies автоматически.")
        print("Жду пока появится сессия...")
        for _ in range(600):  # 10 минут
            await asyncio.sleep(1.0)
            h = (await c.get("/health")).json()
            if h["session_age_sec"] is not None and h["jwt_ttl_sec"] and h["jwt_ttl_sec"] > 0:
                print(f"OK    session_age={h['session_age_sec']}    jwt_ttl={h['jwt_ttl_sec']}")
                return 0
        print("Timeout waiting for login")
        return 2


async def cmd_nodes(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/nodes")
    if r.status_code != 200:
        print(f"failed: {r.status_code}")
        return 2
    for n in r.json()["nodes"]:
        print(f"  {n['id']:>4}  {n['name']:<24} ({n['workflow_class']})")
    return 0


async def cmd_generate(args) -> int:
    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.post("/jobs", json={
            "node_id": args.node,
            "params": {"prompt": args.prompt},
        })
        if r.status_code != 200:
            print(f"submit failed: {r.status_code} {r.text}")
            return 2
        job_id = r.json()["job_id"]
        print(f"job_id={job_id}")

        last = None
        deadline = time.time() + args.timeout
        j = None
        while time.time() < deadline:
            await asyncio.sleep(1.5)
            j = (await c.get(f"/jobs/{job_id}")).json()
            if j["status"] != last:
                print(f"  [{j['status']}]")
                last = j["status"]
            if j["status"] in ("completed", "failed", "canceled"):
                break
        else:
            print(f"timeout after {args.timeout}s")
            return 2

        if j is None or j["status"] != "completed":
            print(f"failed: {j.get('error') if j else 'no status'}")
            return 2

        # Download first result
        d = await c.get(f"/jobs/{job_id}/download")
        if d.status_code != 200:
            print(f"download failed: {d.status_code}")
            return 2
        out_path.write_bytes(d.content)
        print(f"saved -> {out_path}    ({len(d.content)} bytes)")
        return 0


async def cmd_jobs_list(args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/jobs", params={"limit": args.limit})
    if r.status_code != 200:
        print(f"failed: {r.status_code}")
        return 2
    for j in r.json()["jobs"]:
        print(f"  {j['job_id']}  node={j['node_id']}  status={j['status']:<11}  task={j['task_id'] or '-':<12}  {j['updated_at']}")
    return 0


async def cmd_jobs_cancel(args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.delete(f"/jobs/{args.job_id}")
    if r.status_code == 204:
        print(f"canceled {args.job_id}")
        return 0
    print(f"failed: {r.status_code} {r.text}")
    return 2


# ── assets ─────────────────────────────────────────────────────────────────


async def cmd_assets_upload(args) -> int:
    path = Path(args.path).resolve()
    if not path.exists():
        print(f"file not found: {path}")
        return 2
    async with httpx.AsyncClient(base_url=BASE, timeout=300) as c:
        with path.open("rb") as fh:
            r = await c.post("/assets", files={"file": (path.name, fh, "application/octet-stream")})
    if r.status_code != 200:
        print(f"failed: {r.status_code} {r.text}")
        return 2
    e = r.json()
    print(f"sha256={e['sha256'][:12]}...  file_obj_id={e['file_obj_id']}  mime={e['mime']}  size={e['size']}")
    return 0


async def cmd_assets_list(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/assets")
    if r.status_code != 200:
        print(f"failed: {r.status_code}")
        return 2
    items = r.json()["assets"]
    if not items:
        print("(empty)")
        return 0
    for e in items:
        print(f"  {e['sha256'][:12]}...  file_obj_id={e['file_obj_id']:<10}  {e['mime']:<22}  size={e['size']}")
    return 0


async def cmd_assets_clear(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.delete("/assets", params={"all": "true"})
    if r.status_code == 204:
        print("cleared")
        return 0
    print(f"failed: {r.status_code}")
    return 2


# ── video ──────────────────────────────────────────────────────────────────


async def cmd_video_models(_args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/nodes/video")
    if r.status_code != 200:
        print(f"failed: {r.status_code}")
        return 2
    for n in r.json()["nodes"]:
        scen = ", ".join(n["scenarios"])
        print(f"  {n['node_id']:>4}  {n['model']:<24}  scenarios: {scen}")
    return 0


async def cmd_video_scenarios(args) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as c:
        r = await c.get("/nodes/video")
    if r.status_code != 200:
        print(f"failed: {r.status_code}")
        return 2
    for n in r.json()["nodes"]:
        if n["node_id"] != args.node:
            continue
        print(f"{n['model']} (node {n['node_id']})")
        print(f"  slots:           {n['slots']}")
        print(f"  default_params:  {n['default_params']}")
        for scen, slots in n["scenario_slots"].items():
            print(f"  {scen:<28} required slots: {slots}")
        return 0
    print(f"unknown node {args.node}")
    return 2


def main() -> None:
    ap = argparse.ArgumentParser(prog="phygital-studio-cli")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status").set_defaults(fn=cmd_status)

    auth = sub.add_parser("auth").add_subparsers(dest="auth_cmd", required=True)
    auth.add_parser("login").set_defaults(fn=cmd_auth_login)

    sub.add_parser("nodes").set_defaults(fn=cmd_nodes)

    g = sub.add_parser("generate")
    g.add_argument("--node", type=int, required=True, help="node_id (например, 94 для Nano Banana)")
    g.add_argument("--prompt", type=str, required=True)
    g.add_argument("--out", type=str, default="./out.png")
    g.add_argument("--timeout", type=int, default=300, help="seconds")
    g.set_defaults(fn=cmd_generate)

    j = sub.add_parser("jobs").add_subparsers(dest="jobs_cmd", required=True)
    j_list = j.add_parser("list")
    j_list.add_argument("--limit", type=int, default=50)
    j_list.set_defaults(fn=cmd_jobs_list)
    j_cancel = j.add_parser("cancel")
    j_cancel.add_argument("job_id")
    j_cancel.set_defaults(fn=cmd_jobs_cancel)

    a = sub.add_parser("assets").add_subparsers(dest="assets_cmd", required=True)
    a_up = a.add_parser("upload")
    a_up.add_argument("path")
    a_up.set_defaults(fn=cmd_assets_upload)
    a.add_parser("list").set_defaults(fn=cmd_assets_list)
    a.add_parser("clear").set_defaults(fn=cmd_assets_clear)

    v = sub.add_parser("video").add_subparsers(dest="video_cmd", required=True)
    v.add_parser("models").set_defaults(fn=cmd_video_models)
    v_sc = v.add_parser("scenarios")
    v_sc.add_argument("--node", type=int, required=True)
    v_sc.set_defaults(fn=cmd_video_scenarios)

    args = ap.parse_args()
    exit_code = asyncio.run(args.fn(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
