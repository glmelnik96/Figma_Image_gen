# Agent Handoff

## Project Scope
- This repository contains a Figma plugin (`figma-plugin/`) and a local sidecar (`sidecar/`).
- The plugin UI runs in Figma iframe (`ui.html`) and sends canvas operations to main thread (`code.js`).
- The sidecar is a FastAPI service on loopback (`127.0.0.1:18765` in managed/launchd runtime; Python default in `config.py` is `8765`, overridden by `PHYGITAL_PORT=18765` env in `install_autostart.command`) that proxies generation/auth flows to an external backend.

## Current User Flow
- Open plugin in Figma.
- Plugin restores `Sidecar URL` + `token` from `figma.clientStorage`.
- If sidecar is alive and session is valid, generation UI opens directly.
- If session is missing/expired, only auth step remains.

## Security Boundaries
- Sidecar is protected by `X-Phygital-Sidecar-Token` middleware.
- Token file is stored in user app-data (`~/Library/Application Support/PhygitalStudio/sidecar.token` on macOS).
- Only `/health` is intentionally public.
- Keep sidecar bound to loopback only; do not expose on `0.0.0.0`.

## Key Files
- Plugin:
  - `figma-plugin/manifest.json`
  - `figma-plugin/code.js`
  - `figma-plugin/ui.html`
- Sidecar:
  - `sidecar/app/main.py`
  - `sidecar/app/routers/auth.py`
  - `sidecar/app/routers/jobs.py`
  - `sidecar/app/services/job_runner.py`
  - `sidecar/app/services/brand_docs.py`
  - `sidecar/app/workflows/brand.py`
  - `sidecar/start.command`

## Operational Notes
- Preferred local operation mode is single-instance sidecar under user service manager (launchd on macOS, HKCU\…\Run on Windows via `Start Phygital Studio.bat`).
- Avoid spawning multiple manual sidecar processes in parallel.
- One-click launchers in repo root: `Start Phygital Studio.command` (macOS) and `Start Phygital Studio.bat` (Windows). Both copy the sidecar token to the clipboard and register autostart on first run.
- `launchd` plist uses narrow `KeepAlive={Crashed=true, SuccessfulExit=false}` + `ThrottleInterval=10` to avoid crash-loops on corrupt `session.json`.
- Sidecar `bs.preflight()` is wrapped in `try/except` — corrupt session degrades to no-session mode rather than crashing the process.
- If changing auth/session behavior, verify plugin login, job submit, and download paths end-to-end.

## Brand Pipelines
- `brand_t2i`: prompt -> text enhancer step -> image generation.
- `brand_i2i`: reference image(s) -> text enhancer step -> image generation.
- Pipeline selector is passed as `pipeline` in `/jobs` payload.

## Validation Checklist After Changes
- Sidecar boot: `/health` returns `ok: true` on port `18765` (managed) and `8765` (direct uvicorn).
- Plugin boot: settings auto-restored from `figma.clientStorage`; settings handler triggers `refreshState()` if base/token changed after first boot.
- Plugin status: shows three distinct states — sidecar offline / token rejected / not signed in — instead of generic "not reachable".
- Auth flow: login/logout works; corrupt `session.json` does not crash the process.
- Standard generation: node 94/98 works.
- Brand generation: both `brand_t2i` and `brand_i2i` work.
- Background `/health` ping (25s) in `view-app` detects sidecar restart without manual Retry.

