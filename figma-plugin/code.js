// Phygital Studio — main thread (sandbox).
// Owns canvas writes. All network I/O happens in ui.html (only the UI iframe
// can use fetch in Figma). The UI streams generated image bytes here and we
// place them on the canvas — either as a new node, or as a fill of the current
// selection (Phase 3 "fill selection" behavior).

figma.showUI(__html__, { width: 380, height: 640, themeColors: true });

// Cap the inserted node so a 4K render doesn't drop a huge node at 100%.
const MAX_INSERT_EDGE = 1024;

function sendSelection() {
  const sel = figma.currentPage.selection.map((n) => ({
    id: n.id,
    name: n.name,
    type: n.type,
    // Whether we can pour an image fill into it.
    fillable: "fills" in n,
  }));
  figma.ui.postMessage({ type: "selection", nodes: sel });
}

figma.on("selectionchange", sendSelection);

// Persisted connection settings live in figma.clientStorage (survives full
// plugin reloads, unlike the iframe's localStorage which Figma may clear).
const STORE_KEY = "phygital.settings";

figma.ui.onmessage = async (msg) => {
  if (!msg || typeof msg !== "object") return;

  switch (msg.type) {
    case "get-selection": {
      sendSelection();
      break;
    }

    // Return persisted { base, token } to the UI so it can prefill on boot.
    case "settings-get": {
      let saved = null;
      try {
        saved = await figma.clientStorage.getAsync(STORE_KEY);
      } catch (e) {
        saved = null;
      }
      figma.ui.postMessage({ type: "settings", settings: saved || {} });
      break;
    }

    // Persist { base, token } from the UI whenever the user edits them.
    case "settings-set": {
      try {
        await figma.clientStorage.setAsync(STORE_KEY, {
          base: typeof msg.base === "string" ? msg.base : "",
          token: typeof msg.token === "string" ? msg.token : "",
        });
      } catch (e) {
        // Non-fatal: settings just won't persist this session.
      }
      break;
    }

    // Export the single selected node to PNG bytes for use as an img2img init.
    case "export-selection": {
      try {
        const sel = figma.currentPage.selection;
        if (sel.length !== 1) {
          figma.ui.postMessage({ type: "exported", ok: false, error: "Select exactly one layer to use as reference." });
          break;
        }
        const node = sel[0];
        if (typeof node.exportAsync !== "function") {
          figma.ui.postMessage({ type: "exported", ok: false, error: "This layer can't be exported." });
          break;
        }
        // Cap longest edge so we don't ship a huge export to the sidecar; the
        // sidecar/Phygital normalize again anyway.
        const bbox = "width" in node ? Math.max(node.width, node.height) : 0;
        const constraint = bbox > 2048
          ? { type: "WIDTH_AND_HEIGHT", value: Math.round(2048 * (node.width >= node.height ? 1 : node.width / node.height)) }
          : undefined;
        const settings = constraint
          ? { format: "PNG", constraint }
          : { format: "PNG" };
        const bytes = await node.exportAsync(settings);
        figma.ui.postMessage({
          type: "exported", ok: true, bytes,
          srcId: node.id, srcName: node.name,
        });
      } catch (e) {
        figma.ui.postMessage({ type: "exported", ok: false, error: String(e) });
      }
      break;
    }

    case "insert-image": {
      try {
        const bytes = msg.bytes; // Uint8Array (structured-clone transferred)
        const image = figma.createImage(bytes);
        const size = await image.getSizeAsync();

        const sel = figma.currentPage.selection;
        const target = sel.length === 1 && "fills" in sel[0] ? sel[0] : null;

        if (target && msg.mode === "fill") {
          // Pour the render into the selected node as an image fill.
          target.fills = [{ type: "IMAGE", imageHash: image.hash, scaleMode: "FILL" }];
          figma.currentPage.selection = [target];
          figma.viewport.scrollAndZoomIntoView([target]);
          figma.notify("Filled selection with generated image");
          figma.ui.postMessage({ type: "inserted", ok: true, mode: "fill" });
        } else {
          // Insert as a new rectangle sized to the image (scaled to a sane max).
          let { width, height } = size;
          const scale = Math.min(1, MAX_INSERT_EDGE / Math.max(width, height));
          width = Math.round(width * scale);
          height = Math.round(height * scale);

          const rect = figma.createRectangle();
          rect.resize(width, height);
          rect.x = Math.round(figma.viewport.center.x - width / 2);
          rect.y = Math.round(figma.viewport.center.y - height / 2);
          rect.fills = [{ type: "IMAGE", imageHash: image.hash, scaleMode: "FILL" }];
          rect.name = msg.name || "Phygital generation";
          figma.currentPage.appendChild(rect);
          figma.currentPage.selection = [rect];
          figma.viewport.scrollAndZoomIntoView([rect]);
          figma.notify("Inserted generated image");
          figma.ui.postMessage({ type: "inserted", ok: true, mode: "insert" });
        }
      } catch (e) {
        figma.notify("Insert failed: " + (e && e.message ? e.message : String(e)));
        figma.ui.postMessage({ type: "inserted", ok: false, error: String(e) });
      }
      break;
    }

    case "notify": {
      figma.notify(String(msg.message || ""));
      break;
    }

    case "close": {
      figma.closePlugin();
      break;
    }
  }
};

// Push initial selection so the UI can render insert-vs-fill hint on open.
sendSelection();
