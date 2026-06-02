# Agent Handoff

## Project Scope
- This repository contains a Figma plugin (`figma-plugin/`) and a local sidecar (`sidecar/`).
- The plugin UI runs in Figma iframe (`ui.html`) and sends canvas operations to main thread (`code.js`).
- The sidecar is a FastAPI service on loopback (`127.0.0.1:8765`) that proxies generation/auth flows to an external backend.

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
- Preferred local operation mode is single-instance sidecar under user service manager (launchd on macOS).
- Avoid spawning multiple manual sidecar processes in parallel.
- If changing auth/session behavior, verify plugin login, job submit, and download paths end-to-end.

## Brand Pipelines
- `brand_t2i`: prompt -> text enhancer step -> image generation.
- `brand_i2i`: reference image(s) -> text enhancer step -> image generation.
- Pipeline selector is passed as `pipeline` in `/jobs` payload.

## Validation Checklist After Changes
- Sidecar boot: `/health` returns `ok: true`.
- Plugin boot: settings auto-restored.
- Auth flow: login/logout works.
- Standard generation: node 94/98 works.
- Brand generation: both `brand_t2i` and `brand_i2i` work.

