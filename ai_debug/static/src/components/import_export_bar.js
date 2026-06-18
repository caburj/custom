/** @odoo-module **/

import { Component, plugin, props, types as t } from "@odoo/owl";
import { AiDebugStore } from "@ai_debug/store";

/**
 * Bundle schema version. Must match ``_EXPORT_SCHEMA_VERSION`` in
 * ``ai_debug/models/ai_debug_thread.py`` -- bump both on incompatible
 * shape changes.
 */
const SCHEMA_VERSION = 1;

/**
 * Trigger a download of `data` as a JSON file with `filename`. Uses an
 * object URL + synthetic click; works in evergreen browsers without
 * any backend round-trip.
 */
function downloadJSON(data, filename) {
    const blob = new Blob([JSON.stringify(data)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

/**
 * "Export this thread" button. Calls ``ai.debug.thread.export_transcript``
 * on the given thread id and triggers a browser download.
 *
 * Placed in the main-panel header next to the breadcrumbs. Only rendered
 * when a root thread (``!parent_thread_id``) is selected -- sub-agent
 * threads ride along inside their root's bundle.
 */
export class ExportButton extends Component {
    static template = "ai_debug.ExportButton";
    props = props({ threadId: t.number(), orm: t.object() });

    async onClick() {
        const bundle = await this.props.orm.call(
            "ai.debug.thread", "export_transcript", [this.props.threadId],
        );
        // Sanitize the ISO timestamp for the filename (replace : and . with -).
        // Drop the suffix entirely if exported_at is missing so we don't
        // produce a trailing-dash filename like ``ai-debug-thread-42-.json``.
        const stamp = (bundle.exported_at || "").replace(/[:.]/g, "-").slice(0, 19);
        const suffix = stamp ? `-${stamp}` : "";
        downloadJSON(bundle, `ai-debug-thread-${this.props.threadId}${suffix}.json`);
    }
}

/**
 * "Import a transcript" button. Opens a file picker and hands the
 * parsed JSON to ``store.loadFromImport``.
 *
 * Defined here for Task 5 to wire into the sidebar header. Not mounted
 * by Task 4.
 */
export class ImportButton extends Component {
    static template = "ai_debug.ImportButton";
    props = props({});

    store = plugin(AiDebugStore);

    async onClick() {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "application/json,.json";
        input.addEventListener("change", async () => {
            const file = input.files?.[0];
            if (!file) return;
            try {
                const text = await file.text();
                const bundle = JSON.parse(text);
                if (bundle.schema_version !== SCHEMA_VERSION) {
                    alert(
                        `Unsupported transcript schema (got ${bundle.schema_version}, expected ${SCHEMA_VERSION}).`
                    );
                    return;
                }
                await this.store.loadFromImport(bundle);
            } catch (e) {
                alert(`Failed to import transcript: ${e.message}`);
            }
        });
        input.click();
    }
}
