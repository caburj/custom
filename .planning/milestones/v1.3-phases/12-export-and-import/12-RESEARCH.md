# Phase 12: Export and Import - Research

**Researched:** 2026-02-22
**Domain:** Browser file download/upload, OWL dialog pattern, JSON validation
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Trigger placement
- Export and Import buttons live in the sidebar header action bar, alongside existing select-all checkbox and delete controls
- Icon-only buttons (download icon for export, upload icon for import) — no text labels
- Export button is disabled when no traces are selected (same pattern as delete button)
- Import button is always enabled

#### Import behavior
- Merge mode: imported traces are added alongside existing traces (no clearing)
- Duplicate handling: if an imported trace has the same ID as an existing one, overwrite with the imported version
- Preview before import: show a summary dialog ("12 traces found, 3 duplicates will be overwritten") with confirm/cancel
- No success toast — the sidebar updating with new traces is the feedback

#### Export scope
- Exports only the selected (checked) traces — leverages Phase 11 checkbox selection
- Button is disabled when nothing is selected
- Full trace data exported — everything stored in IDB, complete fidelity for restore
- Raw JSON array of trace objects — no envelope or metadata wrapper

#### File format
- Export filename: `ai-debug-traces-YYYY-MM-DD.json` (timestamped with export date)
- Import file picker restricted to `.json` files only

#### Error feedback
- Errors shown inline in the import preview dialog (not as Odoo notifications)
- User-friendly message with technical hint: e.g. "Invalid file: expected JSON array of traces"
- All-or-nothing validation: if any trace in the file is invalid, reject the entire import
- Existing traces are never affected by a failed import

### Claude's Discretion
- Button ordering in the action bar (relative to checkbox and delete)
- Exact validation rules for what constitutes a "valid trace"
- Preview dialog layout and styling
- File download mechanism (blob URL vs other approach)

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| XPRT-01 | User can export all traces as a JSON file download | Blob URL + anchor download pattern covers this; scoped to selected traces per CONTEXT.md |
| XPRT-02 | User can import a previously exported JSON file to restore traces | FileReader API + existing `hydrateTrace()` function covers full restore; IDB write via existing `writeTrace()` |
| XPRT-03 | Invalid import files are rejected with a user-facing error notification | Inline error in import preview dialog (not Odoo notification); all-or-nothing validation before any mutation |
</phase_requirements>

---

## Summary

Phase 12 adds export and import buttons to the sidebar header action bar. Export generates a timestamped JSON file download of the selected traces using the browser's Blob URL + anchor download pattern — no library needed. Import uses a hidden `<input type="file">` triggered programmatically, reads the file with the FileReader API, shows a preview confirmation dialog (reusing the existing OWL Dialog pattern already established by `TextPopupDialog`), then on confirm merges/overwrites traces into both the reactive Map and IDB.

The existing codebase already has all the building blocks: `serializeTrace()` (internal to db.js) produces the JSON-safe representation, `hydrateTrace()` reconstructs reactive traces from plain objects, `writeTrace()` persists to IDB, and the `dialog` service is already wired into the app via `useService("dialog")`. Export serializes the selected traces in the same format that `serializeTrace()` + the `writeTrace()` JSON round-trip produces — meaning imported files can be re-hydrated directly by the existing `hydrateTrace()` function without any new deserialization logic.

The only new component needed is an `ImportPreviewDialog` OWL component (a JS + XML pair, modeled exactly after `TextPopupDialog`). No npm packages are required. The full implementation fits cleanly in two plans: (1) export button + file download, (2) import button + preview dialog + merge logic.

**Primary recommendation:** Use the Blob URL anchor download pattern for export and the FileReader API for import. Reuse `hydrateTrace()` for reconstruction. Build `ImportPreviewDialog` as a new component following the `TextPopupDialog` pattern.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Browser Blob API | native | Create in-memory binary objects for file download | No dependency, universally supported |
| Browser FileReader API | native | Read user-selected file contents as text | No dependency; async, no blocking |
| `@odoo/owl` Component | (project version) | OWL dialog component for import preview | Already in project |
| `@web/core/dialog/dialog` Dialog | (project version) | Odoo Dialog wrapper with header/footer/slots | Already used by TextPopupDialog |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `URL.createObjectURL` | native | Turn Blob into a downloadable URL | Export: anchor href |
| `URL.revokeObjectURL` | native | Release Blob URL memory after click | Called immediately after anchor click |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Blob URL anchor download | `showSaveFilePicker` (File System Access API) | `showSaveFilePicker` is more powerful but requires permissions prompt and is not supported in Firefox; Blob+anchor is zero-friction universal |
| FileReader | `file.text()` (File.prototype.text) | `file.text()` is cleaner (returns Promise) and supported in all modern browsers; both work |

**Installation:** No packages needed. All APIs are native browser APIs.

---

## Architecture Patterns

### Recommended Project Structure

No new files for export logic — export method goes directly in `app.js` as a component method (same pattern as `deleteCheckedTraces()`). Import requires one new dialog component pair:

```
ai_debug/static/src/app/
├── app.js               # Add exportSelected(), openImportPicker() methods
├── app.xml              # Add export + import buttons to .ai-tree-header-actions
├── app.scss             # No changes needed (existing .ai-tree-action-btn covers it)
└── import_dialog.js     # NEW: ImportPreviewDialog component
└── import_dialog.xml    # NEW: ImportPreviewDialog template
```

### Pattern 1: Export — Blob URL Anchor Download

**What:** Create a Blob from JSON string, get a temporary object URL, create an anchor element, click it programmatically, immediately revoke the URL.
**When to use:** Any browser file download without server involvement.
**Example:**
```javascript
// Source: MDN Web Docs - URL.createObjectURL / Blob
exportSelected() {
    const ids = [...this.state.checkedTraceIds];
    if (ids.length === 0) return;

    // Build plain serializable array from reactive Map entries
    // Uses same JSON-safe format that writeTrace() stores in IDB
    const records = ids.map((id) => {
        const trace = this.traces.get(id);
        // IDB records are already plain objects post writeTrace() round-trip.
        // For live (non-hydrated) traces we need to serialize similarly:
        return serializeTraceForExport(trace);
    });

    const json = JSON.stringify(records, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10);  // "YYYY-MM-DD"
    a.href = url;
    a.download = `ai-debug-traces-${today}.json`;
    a.click();
    URL.revokeObjectURL(url);
}
```

**Serialization for export:** The export format must be re-importable. The IDB-stored format (output of `serializeTrace()`) is exactly this: trace_id string, storedAt number, string/number/null scalars, iterations as `[id, record]` pair arrays, toolCalls as `[id, record]` pair arrays, dates as ISO strings. Since `writeTrace()` already does `JSON.parse(JSON.stringify(serializeTrace(trace)))`, the records in IDB are already export-ready plain objects. For live traces (not yet in IDB), the export path needs the same serialization — either expose `serializeTrace()` from db.js or inline equivalent logic in the export method.

**Decision needed (Claude's discretion):** Whether to export `serializeTrace` from `db.js`. The simplest path is to add `export function serializeTrace(...)` in db.js and import it in app.js, removing the `function` keyword (currently it's unexported). This is the cleanest factoring.

### Pattern 2: Import — Hidden File Input

**What:** A hidden `<input type="file" accept=".json">` in the template, triggered by calling `.click()` on its DOM ref from an import button handler.
**When to use:** Standard file picker without drag-and-drop requirement.
**Example:**
```javascript
// In app.js setup():
this.fileInputRef = useRef("fileInput");

// Method:
openImportPicker() {
    this.fileInputRef.el.click();
}

onFileSelected(ev) {
    const file = ev.target.files[0];
    if (!file) return;
    // Reset input so the same file can be re-selected if user cancels + retries
    ev.target.value = "";

    const reader = new FileReader();
    reader.onload = (e) => {
        this._handleImportFile(e.target.result, file.name);
    };
    reader.readAsText(file);
}
```

```xml
<!-- Hidden file input in app.xml — placed outside visible layout -->
<input type="file"
       accept=".json"
       class="d-none"
       t-ref="fileInput"
       t-on-change="onFileSelected"/>
```

### Pattern 3: Import Preview Dialog

**What:** A new OWL component `ImportPreviewDialog` modeled after `TextPopupDialog`. Receives validated data as props. Shows trace count, duplicate count. Has Confirm and Cancel buttons.
**When to use:** Whenever preview confirmation is needed before a destructive or irreversible merge.

**Component structure (mirrors TextPopupDialog):**
```javascript
// import_dialog.js
/** @odoo-module **/
import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class ImportPreviewDialog extends Component {
    static template = "ai_debug.ImportPreviewDialog";
    static components = { Dialog };
    static props = {
        traceCount: Number,
        duplicateCount: Number,
        onConfirm: Function,  // Called when user clicks Confirm
        close: Function,      // Injected by dialog service
        errorMessage: { type: String, optional: true },
    };
}
```

```xml
<!-- import_dialog.xml -->
<t t-name="ai_debug.ImportPreviewDialog">
    <Dialog title="'Import Traces'" size="'sm'">
        <t t-set-slot="default">
            <t t-if="props.errorMessage">
                <p class="ai-import-error" t-esc="props.errorMessage"/>
            </t>
            <t t-else="">
                <p>
                    <strong t-esc="props.traceCount"/> traces found.
                    <t t-if="props.duplicateCount > 0">
                        <strong t-esc="props.duplicateCount"/> duplicate(s) will be overwritten.
                    </t>
                </p>
            </t>
        </t>
        <t t-set-slot="footer">
            <t t-if="!props.errorMessage">
                <button class="btn btn-primary" t-on-click="() => { props.onConfirm(); props.close(); }">
                    Import
                </button>
            </t>
            <button class="btn btn-secondary" t-on-click="props.close">Cancel</button>
        </t>
    </Dialog>
</t>
```

**Dialog service invocation in app.js:**
```javascript
// In setup():
this.dialog = useService("dialog");

// In _handleImportFile(text, filename):
let parsed;
try {
    parsed = JSON.parse(text);
} catch {
    this.dialog.add(ImportPreviewDialog, {
        traceCount: 0,
        duplicateCount: 0,
        onConfirm: () => {},
        errorMessage: "Invalid file: could not parse JSON.",
    });
    return;
}
// Validate + count...
this.dialog.add(ImportPreviewDialog, {
    traceCount: parsed.length,
    duplicateCount: duplicates,
    onConfirm: () => this._applyImport(parsed),
});
```

### Pattern 4: Import Merge Logic

**What:** After confirmation, iterate imported records. For each: merge into reactive Map using `hydrateTrace()` (same as hydration from IDB). Write to IDB using `writeTrace()` (fire-and-forget, same pattern as live traces). Overwrite on duplicate (same trace_id) with `this.traces.set(id, hydrateTrace(record))`.

**Example:**
```javascript
_applyImport(records) {
    for (const record of records) {
        const hydrated = hydrateTrace(record);
        this.traces.set(record.trace_id, hydrated);
        // Fire-and-forget IDB write (overwrites existing if duplicate)
        if (!this.state.ephemeralMode) {
            writeTrace(hydrated).catch((err) => {
                console.warn("[ai_debug] IDB write failed during import:", err);
            });
        }
    }
}
```

**Key insight:** `hydrateTrace()` is already a module-level pure function in app.js — it requires no changes. It handles the [iterId, record] pair array format and ISO date strings, which is exactly what the export JSON contains.

### Anti-Patterns to Avoid

- **Calling `serializeTrace()` on a hydrated trace for re-export:** Hydrated traces have `iterations` as reactive Maps, identical to live traces. `serializeTrace()` handles Map.entries() correctly for both. But `writeTrace()` does the JSON round-trip to strip Proxy wrappers — the export path must also do `JSON.parse(JSON.stringify(...))` if calling `serializeTrace()` directly, otherwise Blob content may include `{}` for proxy objects.
- **Using `URL.createObjectURL` without revoking:** Leaks memory. Always call `URL.revokeObjectURL(url)` after the anchor click fires.
- **Mutating existing traces before validation completes:** The all-or-nothing rule means _applyImport() is only called after full successful validation. Never partially apply.
- **Showing error as Odoo notification:** User decision is inline error in the preview dialog only.
- **Forgetting to reset `<input type="file">` value:** If value is not reset to `""` after each selection, selecting the same file twice does not trigger the `change` event.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File download | Custom server endpoint | Blob URL + anchor | Browser-native, zero-latency, no server round-trip |
| Modal dialog | Custom modal | Odoo `Dialog` + dialog service | Already used in project (TextPopupDialog); keyboard handling, overlay, z-index managed |
| JSON serialization | Custom binary format | Native JSON.stringify | The IDB format is already a clean JSON schema |
| Reactive reconstruction | Custom Map builder | Existing `hydrateTrace()` | Already handles all date parsing and nested Map wrapping |

**Key insight:** The entire import restore path is already implemented as hydration from IDB. Import is just hydration from a user-supplied file instead of from IDB.

---

## Common Pitfalls

### Pitfall 1: Exporting Live (Non-Hydrated) Traces
**What goes wrong:** Live traces have `iterations` and `toolCalls` as OWL reactive Proxies (reactive Maps). `JSON.stringify()` on a Proxy produces `{}` — empty object — because Proxy traps the property enumeration that JSON.stringify relies on.
**Why it happens:** OWL's `reactive()` wraps Map in a Proxy. The Proxy does not expose Map's iterable protocol to JSON.stringify.
**How to avoid:** Always serialize via `serializeTrace()` which calls `.entries()` explicitly, then run the result through `JSON.parse(JSON.stringify(...))` to strip any remaining Proxy wrappers before encoding to Blob. The existing `writeTrace()` function does exactly this.
**Warning signs:** Export JSON contains `{}` for iterations or toolCalls arrays.

### Pitfall 2: Dialog Service Availability in Standalone App
**What goes wrong:** `useService("dialog")` throws if dialog service is not registered or MainComponentsContainer is not rendering.
**Why it happens:** Standalone apps must explicitly render MainComponentsContainer for overlay/dialog services to function.
**How to avoid:** The app already renders `<MainComponentsContainer/>` at the bottom of the template (line 170 in app.xml). The dialog service is available. Confirmed by existing TextPopupDialog usage in loop_detail.js, iter_detail.js, tc_detail.js.
**Warning signs:** `useService("dialog")` error in console.

### Pitfall 3: Validation Scope — What Is a "Valid Trace"
**What goes wrong:** Either over-validation (rejecting valid files because a new field was added) or under-validation (accepting malformed data that breaks hydrateTrace).
**Why it happens:** No defined schema beyond what `hydrateTrace` needs.
**How to avoid (recommendation):** Validate the minimum required by `hydrateTrace()`: each element must be an object with `trace_id` (string, non-empty) and `iterations` (array). Reject if: top-level is not an array, any element is not an object, any element lacks `trace_id` string, any element lacks `iterations` array. This is permissive enough to accept files from future versions with extra fields.
**Warning signs:** `hydrateTrace()` throws TypeError on import.

### Pitfall 4: writeTrace() on Hydrated Trace Objects
**What goes wrong:** `writeTrace()` calls `JSON.parse(JSON.stringify(serializeTrace(trace)))`. `serializeTrace()` calls `trace.iterations.entries()` — which requires `iterations` to be a Map. Hydrated traces have `iterations` as reactive Maps so this works. But if someone passes a plain object (e.g., the raw imported record before hydration), `.entries()` will throw.
**Why it happens:** The export record has `iterations` as an array (the [id, record] pairs), not a Map.
**How to avoid:** Always call `writeTrace(hydrateTrace(record))` in the import path, not `writeTrace(record)`. The hydration step converts arrays to Maps, making the object compatible with `writeTrace()`.
**Warning signs:** `TypeError: trace.iterations.entries is not a function` during import.

### Pitfall 5: File Input Not Resetting
**What goes wrong:** User selects a file, import fails, user tries to re-select the same file — the `change` event does not fire.
**Why it happens:** Browser only fires `change` when the value changes. If the same file is selected again, the value is unchanged.
**How to avoid:** Reset `ev.target.value = ""` at the top of `onFileSelected`, before doing any async work.

---

## Code Examples

Verified patterns from project code:

### Export Button in Template (mirrors delete button pattern)
```xml
<!-- Export button — disabled when nothing selected (same as delete) -->
<button class="ai-tree-action-btn"
        t-att-disabled="state.checkedTraceIds.size === 0 or undefined"
        t-on-click="exportSelected"
        title="Export selected">&#x2193;</button>
<!-- Import button — always enabled -->
<button class="ai-tree-action-btn"
        t-on-click="openImportPicker"
        title="Import traces">&#x2191;</button>
```

### Existing serializeTrace Structure (from db.js)
The export format is exactly the output of `serializeTrace()` after a JSON round-trip:
```javascript
{
    trace_id: string,          // UUID hex
    storedAt: number,          // Date.now() ms
    agent_name: string,
    model_name: string,
    status: string,            // "success" | "error" | "max_iterations"
    started_at: string,        // ISO date string (after JSON round-trip)
    ended_at: string | null,
    duration_ms: number | null,
    instructions: string,
    tools: array,
    state_snapshot: object,
    iterations: [              // Array of [iterId, iterRecord] pairs
        [string, {
            iteration_id: string,
            trace_id: string,
            iteration_index: number,
            has_error: boolean,
            receivedAt: string,    // ISO date string
            is_final: boolean,
            error: any,
            messages_sent: array,
            raw_response: any,
            toolCalls: [           // Array of [tcId, tcRecord] pairs
                [string, {
                    tool_call_id: string,
                    iteration_id: string,
                    tool_name: string,
                    success: boolean,
                    args: object,
                    result: any,
                    error: any,
                    state_before: object,
                    state_after: object,
                    call_id: string | null,
                }]
            ]
        }]
    ]
}
```

### Existing hydrateTrace Signature (from app.js)
```javascript
// Module-level pure function — no changes needed for import use
function hydrateTrace(plain) {
    // Handles: iterations as [id, record] arrays, ISO date strings → Date objects
    // Returns: reactive-Map-wrapped trace, hydrated: true marker set
}
```

### Dialog Service Pattern (from existing detail components)
```javascript
// In setup():
try {
    this.dialog = useService("dialog");
} catch {
    this.dialog = null;  // Outside Odoo env (tests)
}

// Usage:
this.dialog.add(ImportPreviewDialog, { ...props });
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `showSaveFilePicker` File System Access API | Blob URL + anchor (fallback-proof) | N/A | Blob URL works in all browsers; File System Access not supported in Firefox |
| `FileReader` callbacks | `file.text()` Promise | ~2020 | Both work; `file.text()` is cleaner but FileReader is fine for this use case |

**Note:** The project uses `file.text()` style is available but FileReader is equally valid. Either works. The key choice is the Blob URL download approach vs server-side — Blob URL is clearly correct for this use case.

---

## Open Questions

1. **Should `serializeTrace` be exported from db.js?**
   - What we know: It's currently an unexported module-level function; `writeTrace()` uses it internally
   - What's unclear: Whether app.js should import it directly for export, or re-implement equivalent logic inline
   - Recommendation: Export it from db.js (add `export` keyword). This is the minimal-change factoring. Export path calls `JSON.parse(JSON.stringify(serializeTrace(trace)))` for Proxy-safe output.

2. **Should `hydrateTrace` be moved to db.js or kept in app.js?**
   - What we know: It lives in app.js as a module-level function; import merge path in app.js will call it directly
   - What's unclear: Whether a future phase would need it from outside app.js
   - Recommendation: Leave it in app.js for now — import merge happens in app.js anyway, so no cross-module call needed.

3. **Button ordering in .ai-tree-header-actions**
   - What we know: Currently only delete button is present; user deferred ordering to Claude's discretion
   - Recommendation: `[export] [import] [delete]` left to right — export and import are paired actions, delete is destructive and stands alone on the right edge.

---

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` (lines 1-479)
- Direct codebase inspection — `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/db.js` (complete file)
- Direct codebase inspection — `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` (complete file)
- Direct codebase inspection — `TextPopupDialog` pattern in `text_popup.js` + `text_popup.xml`
- Direct codebase inspection — `dialog_service.js` in Odoo core (overlay/add pattern)
- Direct codebase inspection — existing `useService("dialog")` usage in loop_detail.js, iter_detail.js, tc_detail.js

### Secondary (MEDIUM confidence)
- MDN Web Docs patterns for Blob + URL.createObjectURL (well-known, stable browser APIs)
- MDN Web Docs for FileReader API (well-known, stable)

### Tertiary (LOW confidence)
None — all critical claims verified against project codebase directly.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no external libraries; all browser-native APIs or existing project dependencies
- Architecture: HIGH — patterns derived directly from existing project code (TextPopupDialog, deleteCheckedTraces, hydrateTrace, writeTrace)
- Pitfalls: HIGH — Proxy/JSON.stringify trap verified by inspecting writeTrace's JSON round-trip; dialog availability verified by existing usage; file input reset is a well-known browser behavior

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (stable APIs; project code won't change between now and planning)
