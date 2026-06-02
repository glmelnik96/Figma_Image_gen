# Setup (New Mac)

Quick onboarding for this repo.

## 1) Clone and open
```bash
git clone git@github.com:glmelnik96/Figma_Image_gen.git
cd Figma_Image_gen
```

## 2) Install sidecar autostart (one time)
```bash
cd sidecar
./install_autostart.command
```

What this does:
- creates/updates a user `launchd` service (`com.phygitalstudio.sidecar`)
- keeps a single sidecar instance alive
- avoids Desktop privacy issues by running from:
  - `~/Library/Application Support/PhygitalStudio/sidecar-runtime`

## 3) Start/restart sidecar (daily command)
```bash
./start.command
```

This command:
- syncs runtime copy
- restarts the `launchd` service
- prints sidecar token
- runs a health probe

## 4) After code changes in `sidecar/`
```bash
./sync_runtime.command
```

## 5) Figma plugin setup
- Load `figma-plugin/manifest.json` in Figma (development plugin).
- Open plugin.
- Sidecar URL should be `http://localhost:8765`.
- Paste token once (from `start.command` output).
- Token and URL are persisted via `figma.clientStorage`.

## 6) Troubleshooting
- Service state:
```bash
launchctl print "gui/$(id -u)/com.phygitalstudio.sidecar" | awk '/state =|pid =|last exit code/'
```
- Health:
```bash
curl -s http://localhost:8765/health
```
- Listener:
```bash
lsof -nP -iTCP:8765 -sTCP:LISTEN
```
- Logs:
  - `~/Library/Logs/PhygitalStudio/sidecar.out.log`
  - `~/Library/Logs/PhygitalStudio/sidecar.err.log`

## 7) Remove autostart (optional)
```bash
./uninstall_autostart.command
```

