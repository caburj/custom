# Stack Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched (v1.2 theming addendum):** 2026-02-22
**Confidence:** HIGH (all patterns verified against Odoo master and enterprise source at `/Users/joseph/clones/odoo/`)

---

## v1.3 Scope: IndexedDB Persistence, Export/Import, Trace Management

This section covers stack additions for persisting traces to IndexedDB, exporting/importing as JSON files, and providing delete/clear UI. No new npm packages or Odoo module dependencies are required — all needed APIs exist in Odoo master's `web` addon or in the browser platform itself.

**Existing stack unchanged.** The v1.2 theming stack (SCSS bundles, color scheme detection) and v1.1 stack (OWL standalone app, bus_service, sidebar tree) are not modified by v1.3.

---

## v1.3 Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `IndexedDB` from `@web/core/utils/indexed_db` | Odoo master | Structured local storage for trace data | Odoo's own IndexedDB wrapper handles versioning, schema upgrades, quota errors, and mutex-serialized transactions. Used in production by `menu_service`, `localization_service`, `rpc_cache`, and `offline_service`. Import path: `import { IndexedDB } from "@web/core/utils/indexed_db"`. Zero external dependency. |
| `downloadFile` from `@web/core/network/download` | Odoo master | Trigger a browser file download from in-memory data | Creates a temporary `<a download>` element, sets an object URL from a `Blob`, clicks it, then revokes the URL. Handles all cross-browser edge cases. Used throughout Odoo for report downloads. Import: `import { downloadFile } from "@web/core/network/download"`. Pass a `Blob` or string + filename + MIME type. |
| Native `FileReader` API | Browser (all modern) | Read a user-selected JSON file into memory | `FileReader.readAsText(file)` delivers the file content as a string. Wrap in a `Promise` for async/await. No Odoo wrapper needed — the download.js source in Odoo itself uses raw `FileReader` in the same pattern. |
| Hidden `<input type="file" accept=".json">` | Browser (all modern) | Trigger OS file picker for import | A `useRef`-held hidden input element, programmatically `.click()`-ed from a button handler, with `.change` event handling. This is the pattern used by Odoo's own component library (`FileInput` in `@web/core/file_input/file_input`). For local-only import we do NOT use `FileInput` (it uploads to server) — just the raw input element. |
| `notification` service via `useService("notification")` | Odoo master | User feedback for import errors, quota exceeded | `notification.add(message, { type: "danger" })`. Available in the standalone OWL app — registered in `web.assets_backend` which is included by `ai_debug.assets`. Already available to all OWL components via `useService`. |
| `dialog` service via `useService("dialog")` + `ConfirmationDialog` | Odoo master | Delete-confirmation modal before destructive operations | `dialogService.add(ConfirmationDialog, { body, confirm, cancel })` opens a Bootstrap modal with "Confirm" / "Discard" buttons. Import `ConfirmationDialog` from `@web/core/confirmation_dialog/confirmation_dialog`. Available automatically through `web.assets_backend`. |

### Supporting APIs (Browser-Native, No New Dependencies)

| API | Purpose | Notes |
|-----|---------|-------|
| `IndexedDB.execute(callback)` | Run raw IDB operations not covered by `read`/`write`/`getAllKeys` | The `execute` method gives the callback a live `IDBDatabase` instance. Use `db.transaction(table, "readonly").objectStore(table).getAll()` to bulk-read all trace records on startup hydration. The `IndexedDB` class itself only exposes `read(table, key)` and `getAllKeys(table)` — use `execute` for `getAll`. |
| `IndexedDB.invalidate()` | Clear all entries in all stores | Odoo's API: `invalidate(null)` clears all stores; `invalidate("traces")` clears one store. Use for "Clear All" button. |
| `IndexedDB.execute` with `objectStore.delete(key)` | Delete a single trace by ID | No `delete(key)` method on the `IndexedDB` class. Use `execute((db) => new Promise((res, rej) => { const tx = db.transaction("traces", "readwrite"); tx.objectStore("traces").delete(traceId); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }))`. |
| `JSON.stringify` / `JSON.parse` | Serialize trace data for IndexedDB and export | IndexedDB stores structured clones natively — pass plain objects directly to `write()`. For export: `JSON.stringify(payload, null, 2)` for readable output. For import: `JSON.parse(text)` then validate schema version field before merging. |
| `URL.createObjectURL` + `URL.revokeObjectURL` | Called internally by `downloadFile` | Do not call these directly — `downloadFile` handles the object URL lifecycle. |

---

## v1.3 Integration with Existing `useState(new Map())` Store

The existing reactive store uses `useState(new Map())` at the top level with nested `reactive(new Map())` for iterations and tool calls. IndexedDB persistence requires a serialization strategy because:

1. OWL `reactive` proxies are not JSON-serializable.
2. `Date` objects become strings in JSON round-trips and must be reconstructed.
3. Nested `reactive(new Map())` must be recreated when hydrating from IndexedDB.

### Serialization Pattern

Store each trace as a **plain JSON object** keyed by `trace_id`. The object stores only the raw data fields — no `reactive`, no `Map`, no `Date` objects. On load, reconstruct the reactive Maps and Date instances.

```javascript
// Serialize one trace to a plain object for IndexedDB storage
function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        agent_name: trace.agent_name,
        model_name: trace.model_name,
        status: trace.status,
        started_at: trace.started_at?.toISOString() ?? null,
        ended_at: trace.ended_at?.toISOString() ?? null,
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        iterations: Object.fromEntries(
            [...trace.iterations.entries()].map(([iterId, iter]) => [
                iterId,
                {
                    iteration_id: iter.iteration_id,
                    trace_id: iter.trace_id,
                    iteration_index: iter.iteration_index,
                    has_error: iter.has_error,
                    receivedAt: iter.receivedAt?.toISOString() ?? null,
                    is_final: iter.is_final,
                    error: iter.error,
                    messages_sent: iter.messages_sent,
                    raw_response: iter.raw_response,
                    toolCalls: Object.fromEntries(
                        [...iter.toolCalls.entries()].map(([tcId, tc]) => [tcId, { ...tc }])
                    ),
                },
            ])
        ),
    };
}

// Hydrate a plain object back to the reactive store format
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const [iterId, iterPlain] of Object.entries(plain.iterations || {})) {
        const toolCalls = reactive(new Map());
        for (const [tcId, tcPlain] of Object.entries(iterPlain.toolCalls || {})) {
            toolCalls.set(tcId, { ...tcPlain });
        }
        iterations.set(iterId, {
            ...iterPlain,
            receivedAt: iterPlain.receivedAt ? new Date(iterPlain.receivedAt) : null,
            expanded: false,  // UI state always starts collapsed on hydration
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        expanded: false,  // UI state always starts collapsed on hydration
        iterations,
    };
}
```

### Write Pattern (Fire-and-Forget on Every Bus Event)

Write to IndexedDB after each bus event mutates the store. The write is async but does not block the reactive update — OWL re-renders immediately; IndexedDB write happens in the background:

```javascript
// In _onNewTrace, _onIteration, _onToolCall, _onLoopEnd handlers — after store mutation:
this._db.write("traces", payload.trace_id, serializeTrace(this.traces.get(payload.trace_id)));
// No await — fire-and-forget. Failures are logged by IndexedDB class internally.
```

**Why fire-and-forget:** The bus events arrive quickly (multiple per second during an agentic loop). Awaiting each write would block the event handler and delay store updates, causing visual lag. IndexedDB writes with `durability: "relaxed"` are fast (sub-millisecond typically). The worst case on failure is one event not persisted — acceptable for a dev tool.

### Hydration Pattern (onMounted, Before Bus Subscription)

```javascript
onMounted(async () => {
    // Hydrate from IndexedDB BEFORE subscribing to bus
    // so that existing traces are visible immediately,
    // and new bus events append to (not overwrite) them.
    const keys = await this._db.getAllKeys("traces");
    for (const key of keys) {
        const plain = await this._db.read("traces", key);
        if (plain) {
            this.traces.set(plain.trace_id, hydrateTrace(plain));
        }
    }
    // Then subscribe to bus...
    this.busService.subscribe("new_trace", this._onNewTrace);
    // ...
});
```

**Why `getAllKeys` then individual `read` calls:** The `IndexedDB` class from `@web/core/utils/indexed_db` does not have a `getAll()` method that returns values (only `getAllKeys()` exists). To bulk-read, either: (a) loop `getAllKeys` → `read` per key (simple, works), or (b) use `execute((db) => new Promise(res => db.transaction("traces","readonly").objectStore("traces").getAll().onsuccess = e => res(e.target.result)))`. Option (a) is simpler and readable for the expected trace count (dozens, not thousands). Use option (b) if startup time becomes a concern.

---

## v1.3 Schema

Store one object store named `"traces"` in a database named `"ai_debug_traces"`.

```javascript
// In setup():
this._db = new IndexedDB("ai_debug_traces", 1);
// Version 1 — bump if schema changes. The IndexedDB class auto-deletes and re-creates
// the database when the version changes (verified in _checkVersion() source).
```

**Database name:** `"ai_debug_traces"` — scoped to this app, avoids conflicts with Odoo's other IndexedDB databases (`"webclient_menu"`, `"odoo_rpc_cache"`, etc.).

**Object store name:** `"traces"` — one store, one key per trace (`trace_id`), full serialized trace as value.

**Schema version strategy:** Start at `1`. The Odoo `IndexedDB` class's `_checkVersion()` deletes and re-creates the entire database if the version changes. This is acceptable for a dev tool. Bump to `2` if the stored schema changes in a future milestone.

---

## v1.3 Export Pattern

```javascript
exportTraces(traceIds) {
    // traceIds: array of trace_id strings to export, or null for all
    const toExport = traceIds
        ? traceIds.map((id) => serializeTrace(this.traces.get(id))).filter(Boolean)
        : [...this.traces.values()].map(serializeTrace);

    const payload = {
        version: 1,  // export schema version — bump if format changes
        exported_at: new Date().toISOString(),
        traces: toExport,
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const filename = `ai-traces-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
    downloadFile(blob, filename, "application/json");
}
```

**Why `downloadFile` not `<a>` directly:** `downloadFile` from `@web/core/network/download` handles cross-browser edge cases (Safari, IE11 fallback, object URL lifecycle). It is already in the bundle via `web.assets_backend`.

---

## v1.3 Import Pattern

```javascript
importTraces(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const payload = JSON.parse(e.target.result);
                if (payload.version !== 1) {
                    reject(new Error(`Unsupported export version: ${payload.version}`));
                    return;
                }
                for (const plain of payload.traces) {
                    // Merge: imported traces are added; existing traces with same ID are overwritten
                    this.traces.set(plain.trace_id, hydrateTrace(plain));
                    this._db.write("traces", plain.trace_id, plain);  // fire-and-forget
                }
                resolve(payload.traces.length);
            } catch (err) {
                reject(err);
            }
        };
        reader.onerror = () => reject(new Error("FileReader error"));
        reader.readAsText(file);
    });
}
```

**Error surface:** Wrap the call in a try/catch in the button handler and show `notification.add(err.message, { type: "danger" })` on failure.

---

## v1.3 Delete Patterns

```javascript
// Delete single trace — from store and IndexedDB
async deleteTrace(traceId) {
    this.traces.delete(traceId);
    if (this.state.selectedId === traceId) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    await this._db.execute((db) => new Promise((res, rej) => {
        const tx = db.transaction("traces", "readwrite");
        tx.objectStore("traces").delete(traceId);
        tx.oncomplete = res;
        tx.onerror = () => rej(tx.error);
    }));
}

// Clear all — both store and IndexedDB
async clearAll() {
    this.traces.clear();
    this.state.selectedId = null;
    this.state.selectedType = null;
    await this._db.invalidate("traces");  // clears the "traces" object store
}
```

**Confirmation before delete:** Use `dialogService.add(ConfirmationDialog, { body: "Delete this trace?", confirm: () => this.deleteTrace(id), confirmClass: "btn-danger", confirmLabel: "Delete" })`. The existing `clearAll()` method in `app.js` already exists but only clears the in-memory store — v1.3 adds the IndexedDB side.

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `localStorage` for trace storage | 5-10 MB limit in most browsers. A single large RAG-enabled session can produce megabytes of trace data. Size cap causes silent data loss with no error surfacing. | `IndexedDB` via `@web/core/utils/indexed_db` — browser-managed quota with explicit `QuotaExceededError`. |
| `idb` npm package (jakearchibald/idb) | External npm dependency; not in Odoo's asset pipeline; adds 2 KB gzip for a wrapper we get for free from `@web/core/utils/indexed_db`. | `IndexedDB` from `@web/core/utils/indexed_db` — already in the bundle via `web.assets_backend`. |
| `idb-keyval` (already vendored in mail/website_event_track) | Vendored as a service worker utility in the `mail` addon — not accessible from `@web/core/utils`. Importing across addons from a vendor lib path is fragile. | `IndexedDB` from `@web/core/utils/indexed_db`. |
| POS `IndexedDB` class (`@point_of_sale/app/models/utils/indexed_db`) | POS IndexedDB is designed for POS-specific batch ORM data — heavyweight, callback-based, not exposed as an `@web/*` import. | `IndexedDB` from `@web/core/utils/indexed_db`. |
| Storing OWL reactive proxies in IndexedDB | `structuredClone` (used internally by IndexedDB) cannot clone OWL Proxy objects and will throw `DataCloneError`. | Serialize to plain objects via `serializeTrace()` before writing. |
| Awaiting IndexedDB writes in bus event handlers | Blocks the event handler and delays OWL reactive updates, causing sidebar to stutter during fast loop execution. | Fire-and-forget writes — `this._db.write(...)` without `await` in event handlers. |
| `FileInput` component from `@web/core/file_input/file_input` | `FileInput` is hardwired to upload files to a server route (`/web/binary/upload_attachment`). We need client-side `FileReader` — no server round-trip. | Hidden `<input type="file">` with `FileReader.readAsText()`. |
| Server-side persistence (Odoo model, SQL) | Adds a migration, a model, ORM overhead, and database I/O for every bus event. Out of scope per PROJECT.md constraints. | IndexedDB for persistence; nothing for coordination. |

---

## Version Compatibility

| API | Odoo Version | Notes |
|-----|--------------|-------|
| `IndexedDB` class at `@web/core/utils/indexed_db` | Odoo master | Verified imported by `menu_service`, `localization_service`, `rpc_cache`, `offline_service`. The class is stable and widely used. |
| `IndexedDB.execute(callback)` | Odoo master | Exposes raw `IDBDatabase` for operations not in the class API. `getAll()` for values requires this. |
| `IndexedDB.invalidate(tableName)` | Odoo master | Passing a string clears one store. Passing null clears all stores except `__DBVersion__`. |
| `downloadFile(data, filename, mimetype)` | Odoo master | Exported from `@web/core/network/download`. Accepts `Blob`, `string`, or data URL as `data`. |
| `ConfirmationDialog` | Odoo master | At `@web/core/confirmation_dialog/confirmation_dialog`. Props: `body`, `confirm`, `cancel`, `confirmLabel`, `cancelLabel`, `confirmClass`, `title`. |
| `notification` service | Odoo master | `useService("notification")` in any OWL component mounted via `mountComponent`. API: `notification.add(message, { type: "success"|"danger"|"warning"|"info" })`. |
| `dialog` service | Odoo master | `useService("dialog")` in any OWL component. API: `dialogService.add(Component, props)`. Returns a close function. |
| `IDBQuotaExceededError` | Odoo master | Exported from `@web/core/utils/indexed_db`. Thrown (not just logged) when quota is exceeded. Catch it to show a user-facing notification. |
| `FileReader` | Browser — all modern | `readAsText(file)` → `onload` → `event.target.result` string. No Odoo dependency. |

---

## Sources

All patterns verified against Odoo master source code at `/Users/joseph/clones/odoo/odoo/.worktrees/master/`:

- `addons/web/static/src/core/utils/indexed_db.js` — Full `IndexedDB` class source: `read`, `write`, `getAllKeys`, `invalidate`, `execute`, `_checkVersion`, `IDBQuotaExceededError` (HIGH confidence)
- `addons/web/static/src/webclient/menus/menu_service.js` — `new IndexedDB("webclient_menu", session.registry_hash)` + `read`/`write` pattern (HIGH confidence)
- `addons/web/static/src/core/network/rpc_cache.js` — `IDBQuotaExceededError` catch pattern + `execute` usage (HIGH confidence)
- `addons/web/static/src/core/network/download.js` — `downloadFile(data, filename, mimetype)` implementation, Blob + object URL lifecycle (HIGH confidence)
- `addons/web/static/src/core/confirmation_dialog/confirmation_dialog.js` — `ConfirmationDialog` props, `AlertDialog` variant (HIGH confidence)
- `addons/web/static/src/core/file_input/file_input.js` — `FileInput` server-upload pattern (confirmed: NOT suitable for local import) (HIGH confidence)
- `addons/web/static/src/core/utils/files.js` — `useFileUploader` uploads to server route; raw `FileReader` needed instead for local import (HIGH confidence)
- `addons/web/static/src/core/utils/indexed_db.js` lines 215-244 — `_invalidate` implementation: `objectStore.clear()` for each named table (HIGH confidence)
- `addons/mail/static/lib/idb-keyval/idb-keyval.js` — idb-keyval confirmed vendored in mail addon; not usable from `@web/*` path (HIGH confidence)
- `addons/point_of_sale/static/src/app/models/utils/indexed_db.js` — POS-specific IndexedDB, batch-oriented, not appropriate for this use case (HIGH confidence)

---

## v1.2 Stack (Prior Milestone — Retained for Reference)

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.2)
**Researched:** 2026-02-22

---

### v1.2 Scope: Native Odoo Theming

This document adds a v1.2 section focused on replacing hardcoded Catppuccin Mocha colors with Odoo's Bootstrap CSS variable theming system. The v1.1 stack content (standalone OWL app, bus.bus, sidebar tree, asset bundle) follows at the bottom and is not re-researched.

---

### v1.2 Recommended Stack

#### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `web.assets_web_dark` asset bundle | Odoo master + web_enterprise | Provides fully compiled dark-mode CSS | The dark bundle re-compiles ALL SCSS with dark variable values injected before light ones via `web.dark_mode_variables`. This is Odoo's official mechanism — used by the webclient, POS, and all enterprise modules. Loading this bundle instead of `web.assets_web` gives a complete dark theme with zero extra SCSS authoring. |
| Bootstrap 5 CSS custom properties (`--body-bg`, `--border-color`, etc.) | Bootstrap 5 (no `bs-` prefix in Odoo) | Runtime color tokens that switch between light and dark without SCSS re-compilation | Odoo sets `$variable-prefix: ''` which strips the `bs-` prefix, so all Bootstrap CSS custom properties are unprefixed: `var(--body-bg)`, `var(--body-color)`, `var(--border-color)`. These are emitted at `:root` by Bootstrap and automatically carry dark values when the dark bundle is loaded. Using them in app SCSS means the app adapts for free as the bundle switches. |
| `request.env['ir.http'].color_scheme()` | web_enterprise `ir_http.py` | Server-side detection of user's color preference | Returns `'light'` or `'dark'`. Reads the `color_scheme` cookie first, then falls back to `res.users.settings.color_scheme`. The community `ir.http` base always returns `'light'`; the enterprise override (in `web_enterprise/models/ir_http.py`) adds the cookie and user preference. Called once at page render time — no JS needed. |
| `color_scheme` cookie | Browser cookie set by `web_enterprise` controller | Persists user's light/dark toggle preference across page loads | Set by `web_enterprise/controllers/home.py` on every `/web` or `/odoo` request. The cookie value is `'dark'` or `'light'`. Reading it server-side via `color_scheme()` and loading the correct bundle server-side is the same approach used by the main webclient template (`web.webclient_bootstrap` lines 314-319). |

#### Supporting Libraries (No New Dependencies)

No new npm packages, Python libraries, or Odoo modules required. All the infrastructure is already present:

| Library | Purpose | Status |
|---------|---------|--------|
| `web.dark_mode_variables` asset bundle | Injects dark SCSS variable overrides before light variables — enables full SCSS recompilation with dark palette | Defined by `web_enterprise/__manifest__.py`. Available because `ai_debug` already depends on `ai_app` which depends on `web_enterprise`. |
| `web_enterprise/static/src/scss/primary_variables.dark.scss` | Declares dark-mode overrides for all `$o-gray-*`, `$o-webclient-background-color`, `$o-view-background-color`, etc. | Included by `web.dark_mode_variables`; compiled automatically when the dark bundle is loaded. |

---

### Pattern 1: Conditional Bundle Loading in Controller + Template

This is the exact same mechanism used by `web.webclient_bootstrap`. The controller calls `color_scheme()` and passes it to the template. The template conditionally loads the light or dark bundle.

#### Controller Change (`controllers/main.py`)

```python
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import is_user_internal


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        session_info = request.env['ir.http'].session_info()
        color_scheme = request.env['ir.http'].color_scheme()
        return request.render('ai_debug.index', {
            'session_info': session_info,
            'color_scheme': color_scheme,
        })
```

**Why `color_scheme()` not cookie read directly:** `color_scheme()` encapsulates the full priority chain — cookie → user preference → default. The cookie alone misses the user's explicit preference set in the Odoo settings panel. Using the method is the authoritative source, identical to how the main webclient does it.

**Why `debug` is not passed explicitly:** QWeb auto-injects `debug` from `request.session.debug` into the template rendering context (`ir_qweb.py` line 1297: `values.setdefault('debug', debug)`). No need to pass it manually.

#### Template Change (`views/ai_debug_index.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="index" name="AI Debug">&lt;!DOCTYPE html&gt;
        <html>
            <head>
                <title>AI Debugger</title>
                <meta charset="utf-8"/>
                <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
                <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
                <script type="text/javascript">
                    var odoo = {
                        csrf_token: "<t t-out="request.csrf_token(None)"/>",
                        debug: "<t t-out="debug"/>",
                        __session_info__: <t t-out="json.dumps(session_info)"/>,
                    };
                </script>
                <t t-if="color_scheme == 'dark'">
                    <t t-call-assets="ai_debug.assets_dark" t-js="false"/>
                    <t t-call-assets="ai_debug.assets" t-css="false"/>
                </t>
                <t t-else="">
                    <t t-call-assets="ai_debug.assets"/>
                </t>
            </head>
            <body/>
        </html>
    </template>
</odoo>
```

**Why split CSS and JS for dark mode:** The dark bundle replaces the CSS only — the JS is identical in both themes. The split `t-js="false"` / `t-css="false"` pattern mirrors `web.webclient_bootstrap` exactly (lines 312-319 of `webclient_templates.xml`). In dark mode: load dark CSS from `ai_debug.assets_dark`, load JS from `ai_debug.assets`. In light mode: load the single bundle normally (which includes both).

**Why not load both dark and light CSS with a media query:** Odoo does not use `prefers-color-scheme` media queries. The dark/light choice is explicit via a user cookie, not an OS preference. The server decides which bundle to load based on the cookie value.

#### Asset Bundle Changes (`__manifest__.py`)

```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        'ai_debug/static/src/app/**/*.scss',
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
    ],
    # Dark mode bundle: recompiles all SCSS with dark variable values
    'ai_debug.assets_dark': [
        ('include', 'web.dark_mode_variables'),  # injects dark vars before light
        ('include', 'ai_debug.assets'),           # recompiles full bundle with dark palette
    ],
    'web.assets_backend': [
        'ai_debug/static/src/debug_menu_button.js',
    ],
},
```

**Why `('include', 'web.dark_mode_variables')` first:** `web.dark_mode_variables` uses `('before', ...)` positioning to place dark SCSS variable files immediately before their light counterparts in the file order. When `ai_debug.assets_dark` includes this bundle first, the dark SCSS variable files are loaded before the light SCSS compiles, so `$o-gray-100` etc. carry their dark values for the entire compilation. This is identical to how `web.assets_web_dark` works in the enterprise manifest.

**Why the dark bundle includes `ai_debug.assets` not `web.assets_web_dark`:** `web.assets_web_dark` includes `web.assets_web` which includes `main.js` and `start.js` — the webclient bootstrappers that conflict with the standalone app's own `main.js`. Using `ai_debug.assets` as the base keeps the standalone app's own bootstrap intact while still getting the dark variable recompilation.

**Why `web.dark_mode_variables` is safe to include:** `web.dark_mode_variables` is defined by `web_enterprise/__manifest__.py`. The `ai_debug` module depends on `ai_app` which depends on `web_enterprise`. The bundle is always present.

---

### Pattern 2: Replacing Hardcoded Colors with CSS Custom Properties

The app.scss currently uses hardcoded Catppuccin Mocha hex values. These map to Bootstrap/Odoo CSS custom properties that automatically carry dark or light values depending on which bundle is loaded.

#### Color Mapping: Catppuccin Mocha → Odoo CSS Custom Properties

| Catppuccin Hex | Semantic Role | Replace With | Notes |
|----------------|---------------|--------------|-------|
| `#1e1e2e` | App background, sidebar bg | `var(--body-bg)` | Bootstrap `:root` — `$body-bg` → `$o-webclient-background-color`. Dark: `#1B1D26`. Light: `#F9FAFB`. |
| `#181825` | Header background, deeper panel bg | `var(--secondary-bg)` | Bootstrap `:root` — darker surface than body. Dark: derived from `$o-gray-200 = #262A36` (actually, secondary-bg is darker). Use `color-mix(in srgb, var(--body-bg), black 30%)` or a custom CSS var. |
| `#11111b` | Detail panel background (deepest) | `var(--tertiary-bg)` or custom | Bootstrap emits `--tertiary-bg`. Alternatively define `--ai-debug-deep-bg` as a CSS var anchored to `var(--body-bg)`. |
| `#313244` | Borders and dividers | `var(--border-color)` | Bootstrap `:root` — `$border-color` → `$o-gray-300`. Dark: `$o-gray-300 = #3C3E4B`. Light: `$d8dadd`. |
| `#cdd6f4` | Primary text | `var(--body-color)` | Bootstrap `:root` — `$body-color` → `$o-main-text-color` → `$o-gray-900`. Dark: `#E4E4E4`. Light: `#111827`. |
| `#a6adc8` | Secondary text, monospace content | `var(--secondary-color)` | Bootstrap 5.3 `:root` variable. Falls back to `color-mix(in srgb, var(--body-color), transparent 40%)`. |
| `#585b70` | Muted / dimmed text, placeholder | `var(--tertiary-color)` | Bootstrap 5.3 `:root` variable. Or use `.text-muted` Bootstrap class directly in templates. |
| `#6c7086` | Section headers, labels | `color-mix(in srgb, var(--body-color), transparent 50%)` | No direct Bootstrap var maps here. Define as `--ai-debug-label-color`. |
| `#89b4fa` | Accent / selected indicator / link | `var(--link-color)` | Bootstrap `:root` — `$link-color` → `$o-main-link-color` → `$o-enterprise-action-color`. Dark: `#02c7b5`. Light: `#017e84`. |
| `#a6e3a1` | Success state | `var(--success)` | Bootstrap theme color. Dark: `#1dc959`. Light: Bootstrap default. |
| `#f38ba8` | Error / danger state | `var(--danger)` | Bootstrap theme color. Dark: `#b83232`. Light: Bootstrap default. |
| `#f9e2af` | Warning state | `var(--warning)` | Bootstrap theme color. Dark: `#FBB56A`. Light: Bootstrap default. |

**Confidence:** HIGH for `--body-bg`, `--body-color`, `--border-color`, `--link-color`, `--success`, `--danger`, `--warning` — these are established Bootstrap 5 `:root` variables. MEDIUM for `--secondary-color`, `--tertiary-color`, `--secondary-bg`, `--tertiary-bg` — these exist in Bootstrap 5.3 but may not all be emitted by Odoo's Bootstrap configuration (`$enable-dark-mode: false` suppresses Bootstrap's own dark mode variables in `_root.scss`; Odoo implements its own scheme).

**Important caveat on secondary/tertiary Bootstrap vars:** Odoo sets `$enable-dark-mode: false` in `bootstrap_overridden.scss` line 60. This disables Bootstrap 5's built-in `[data-bs-theme="dark"]` block in `_root.scss`, which means `--secondary-bg`, `--tertiary-bg`, `--secondary-color`, `--tertiary-color` may not be emitted at `:root`. Verify in the compiled bundle before using. Safe fallback: define component-scoped CSS custom properties anchored to `$o-gray-*` SCSS variables directly in the module's SCSS files, which get the correct values at compile time.

#### SCSS Approach for Compile-Time Color Values

For values with no direct CSS custom property match, use SCSS variables directly in the app's SCSS. These get the correct dark/light values at compile time because `web.dark_mode_variables` is included first:

```scss
// Use SCSS variables for values that won't have a CSS custom property
// These compile to the correct light or dark hex values automatically
// because web.dark_mode_variables overrides them before this file compiles.

.ai-debug-header {
    background-color: $o-gray-200;  // Light: #e7e9ed, Dark: #262A36
    border-bottom: 1px solid $o-gray-300;  // Light: #d8dadd, Dark: #3C3E4B
}

.ai-debug-app {
    background-color: $o-gray-100;  // Light: #F9FAFB, Dark: #1B1D26
    color: $o-gray-900;  // Light: #111827, Dark: #E4E4E4
}
```

**Why SCSS variables are safe:** When `ai_debug.assets_dark` is loaded, `web.dark_mode_variables` runs `('before', primary_variables.scss, primary_variables.dark.scss)`, which makes `$o-gray-100 = #1B1D26` during the entire SCSS compilation of `ai_debug.assets`. The compiled CSS has the dark value baked in. This is the same mechanism used by every enterprise dark SCSS file.

#### Dark-Specific Override Pattern (`.dark.scss` files)

For colors that cannot be expressed as CSS custom properties or SCSS variables — such as complex rgba() calls with specific alpha values tied to the Catppuccin palette — create `.dark.scss` override files. These are only included in the dark bundle:

```scss
// ai_debug/static/src/app/app.dark.scss
// Overrides for colors that differ from the SCSS variable mappings

.ai-tree-row {
    &.selected {
        // In light mode: uses default Bootstrap active bg
        // In dark mode: use Odoo's dark action color tint
        background-color: rgba($o-enterprise-action-color, 0.15);
        border-left-color: $o-enterprise-action-color;
    }

    &.ancestor {
        background-color: rgba($o-enterprise-action-color, 0.05);
    }
}

.ai-json-key { color: $o-action; }
```

**Why `.dark.scss` files are automatically included:** `ai_debug.assets_dark` includes `ai_debug.assets` which uses `'ai_debug/static/src/app/**/*.scss'`. This glob includes `.dark.scss` files. To exclude them from the light bundle, add `('remove', 'ai_debug/static/src/app/**/*.dark.scss')` to `ai_debug.assets`, identical to how `web_enterprise/__manifest__.py` line 46 does `('remove', 'web_enterprise/static/src/**/*.dark.scss')`.

---

### Pattern 3: Color Scheme Cookie Detection

#### Server-Side (Recommended Approach)

The controller reads the color_scheme cookie via `ir.http.color_scheme()` and conditionally loads the correct asset bundle server-side. No JavaScript cookie parsing needed at mount time:

```python
color_scheme = request.env['ir.http'].color_scheme()
return request.render('ai_debug.index', {'color_scheme': color_scheme, ...})
```

The template then loads `ai_debug.assets_dark` (CSS only) or `ai_debug.assets` based on `color_scheme == 'dark'`. The app JS never needs to know which theme is active — the CSS just works.

#### Client-Side Cookie Parsing (Only If Needed)

If any JS component needs to know the current color scheme at runtime (e.g., for a JS charting library that can't use CSS variables), parse the cookie client-side:

```javascript
// Read color_scheme cookie — same logic as webclient_offline template uses
function getColorScheme() {
    const match = document.cookie.match(/(?:^|;\s*)color_scheme=([^;]+)/);
    return match ? match[1] : 'light';
}
```

**Why not use `prefers-color-scheme` media query in JS:** Odoo's color scheme is user-controlled via cookie/preference, not OS-controlled. A user might have OS in dark mode but Odoo in light mode. The cookie is authoritative.

**Why not use a service or OWL reactive state for color scheme in the standalone app:** The color scheme is fixed for the lifetime of a page load. The correct bundle is loaded at page render time. No runtime switching occurs. There is nothing to react to in OWL.

---

### What NOT to Use (v1.2)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Custom theme system (CSS-in-JS, emotion, styled-components, etc.) | Introduces a dependency outside Odoo's toolchain. Odoo's SCSS pipeline is the only supported path for theming. | Odoo SCSS variables and Bootstrap CSS custom properties. |
| Third-party CSS frameworks (Tailwind, Bulma, etc.) | Would conflict with Odoo's Bootstrap-based layout. The standalone app already inherits Bootstrap via `web.assets_backend`. | Odoo's Bootstrap 5 classes and CSS custom properties already present in the bundle. |
| `@media (prefers-color-scheme: dark)` CSS queries | Odoo does not use OS dark mode preference. The user's color_scheme cookie controls the theme. Using a media query creates a split where OS preference and Odoo preference diverge. | Server-side bundle selection based on `color_scheme` cookie. |
| Inline styles for theme-sensitive colors | Defeats the variable system entirely. Inline styles always override CSS custom property defaults and require JS to switch. | CSS custom property references in SCSS rules. |
| `web.assets_web_dark` directly in the standalone app template | `web.assets_web_dark` includes `web.assets_web` which includes `main.js` and `start.js` — the webclient bootstrappers. Loading them in the standalone app's page creates a double bootstrap conflict. | The custom `ai_debug.assets_dark` bundle that includes `web.dark_mode_variables` + `ai_debug.assets`. |
| Hardcoding Catppuccin dark values in `.dark.scss` overrides | If the user has a light-mode Odoo instance, the dark SCSS file never loads — which is correct. But if you hardcode exact Catppuccin hex values in `.dark.scss`, you lose the ability to match Odoo's actual dark palette. | `$o-gray-*` SCSS variables and Bootstrap CSS custom property references in `.dark.scss` overrides. |

---

### Version Compatibility (v1.2)

| Pattern | Odoo Version | Notes |
|---------|--------------|-------|
| `ir.http.color_scheme()` method | web_enterprise master | Base method in community always returns `'light'`. Enterprise override adds cookie and user preference. Verified in `web_enterprise/models/ir_http.py`. |
| `color_scheme` cookie format | web_enterprise master | Set by `web_enterprise/controllers/home.py` on every `/web` request. Values: `'dark'` or `'light'`. |
| `web.dark_mode_variables` bundle | web_enterprise master | Defined in `web_enterprise/__manifest__.py` lines 61-67. Required for the `ai_debug.assets_dark` approach. |
| `web.assets_web_dark` bundle | web (community) + web_enterprise | Base `web.assets_web_dark` defined in `web/__manifest__.py` line 339. Enterprise adds dark variable injection via `web.dark_mode_variables`. Only the enterprise version has meaningful dark colors. |
| Bootstrap CSS custom properties (no `bs-` prefix) | Odoo 16+ master | `$variable-prefix: ''` in `web/static/src/scss/bootstrap_overridden.scss` line 51. CSS vars are `--body-bg` not `--bs-body-bg`. |
| `$o-gray-*` SCSS variables | web_enterprise master | Defined in `web_enterprise/static/src/scss/primary_variables.scss`. Dark overrides in `primary_variables.dark.scss`. Available in any SCSS file compiled within the asset bundle. |
| `$enable-dark-mode: false` | Odoo 16+ | Set in `web/static/src/scss/bootstrap_overridden.scss` line 60. Disables Bootstrap 5's own dark mode `:root` block. Odoo rolls its own dark mode via separate compiled bundles. |

---

### Sources (v1.2)

All patterns verified against Odoo master source, not training data or web search:

- `addons/web/views/webclient_templates.xml` lines 312-319 — conditional `color_scheme == 'dark'` → `assets_web_dark` pattern (HIGH confidence)
- `addons/point_of_sale/views/pos_assets_index.xml` lines 36-41 — standalone app conditional bundle loading on `pos_color_scheme` cookie (HIGH confidence)
- `web_enterprise/models/ir_http.py` lines 22-31 — `color_scheme()` method: cookie → user preference → default (HIGH confidence)
- `web_enterprise/controllers/home.py` lines 13-14 — `color_scheme` cookie set on every `/web` request (HIGH confidence)
- `web_enterprise/__manifest__.py` lines 44-75 — `web.dark_mode_variables`, `web.assets_web_dark`, `('remove', '**/*.dark.scss')` patterns (HIGH confidence)
- `addons/web/__manifest__.py` lines 339-342 — base `web.assets_web_dark` definition: includes `web.assets_web` + `**/*.dark.scss` (HIGH confidence)
- `web_enterprise/static/src/scss/primary_variables.dark.scss` — dark-mode $o-gray-* values: gray-100=#1B1D26, gray-200=#262A36, gray-300=#3C3E4B, gray-900=#E4E4E4 (HIGH confidence)
- `addons/web/static/src/scss/bootstrap_overridden.scss` lines 51, 60 — `$variable-prefix: ''` (no bs- prefix), `$enable-dark-mode: false` (HIGH confidence)
- `addons/web/static/lib/bootstrap/scss/_root.scss` — Bootstrap 5 `:root` CSS custom property declarations (HIGH confidence)
- `web_enterprise/static/src/core/notebook/notebook.dark.scss` — component-scoped dark override using `$o-*` SCSS vars (HIGH confidence)
- `enterprise/account_reports/static/src/scss/account_return.scss` — `var(--body-bg)`, `var(--body-color)`, `var(--border-color)` usage in enterprise SCSS (HIGH confidence)

---

## v1.1 Stack (Prior Milestone — Retained for Reference)

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1)
**Researched:** 2026-02-20

---

### What v1.1 Research Covers

v1.1 changes three things from v1.0:
1. Replace the `ir.actions.client` backend panel with a **true standalone OWL app** at `/ai-debug` (own HTML page, own asset bundle, own HTTP controller — same pattern as `point_of_sale.index`)
2. Carry **full payloads** over `bus.bus` instead of summary-only (no DB means no lazy ORM reads)
3. Render a **sidebar tree** (Loop > Iteration > Tool Call) with a master/detail layout

The v1.0 stack entries (generator yield passthrough, model inheritance, backend views) are NOT re-researched here. Only additions and changes are covered.

---

### Core Technologies (v1.1)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| OWL `mountComponent` | Odoo master (OWL 2.8.1) | Bootstrap standalone OWL app into `document.body` | `mountComponent` from `@web/env` creates its own OWL env, starts all registered services (including `bus_service`), and mounts the root component. Used identically by `point_of_sale/static/src/app/main.js` and `point_of_sale/static/src/customer_display/customer_display.js`. |
| Dedicated asset bundle (`ai_debug.assets`) | Odoo master | Isolate standalone app JS/CSS from backend | The standalone page loads exactly one `<t t-call-assets="..."/>` tag pointing to a module-defined bundle. POS uses `point_of_sale.assets_prod`; ai_debug uses `ai_debug.assets`. The bundle includes `web.assets_backend` for OWL, session, bus services. |
| HTTP controller (`type='http'`, `auth='user'`) | Odoo master | Serve the `/ai-debug` HTML page | `request.render('ai_debug.index', context)` renders the QWeb template. `auth='user'` enforces login. Exact same pattern as `PosController.pos_web()` in `point_of_sale/controllers/main.py`. |
| QWeb HTML template (`<template id="ai_debug.index">`) | Odoo master | Standalone HTML page shell | Declares `<!DOCTYPE html>`, injects `odoo` global with `csrf_token` and `__session_info__`, calls `t-call-assets`. Same structure as `point_of_sale/views/pos_assets_index.xml`. |
| `bus_service` + `bus_service.subscribe()` | Odoo master | Receive full-payload events in standalone app | The bus service registers itself into the service registry and is started automatically by `mountComponent` → `startServices`. Works identically in standalone and backend contexts. |

### What NOT to Use (v1.1)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `ir.actions.client` for the standalone app | Client actions render inside the Odoo backend layout (navbar, breadcrumbs, action manager). The requirement is a true standalone page with no Odoo chrome — like POS. | HTTP controller + QWeb template + `mountComponent` |
| `mount` (from `@odoo/owl`) instead of `mountComponent` | `mount` skips `makeEnv` and `startServices`. The `bus_service`, `rpc`, and all other services are not started. | `mountComponent` from `@web/env` |

### Sources (v1.1)

- `addons/point_of_sale/views/pos_assets_index.xml` — QWeb standalone HTML template structure
- `addons/point_of_sale/controllers/main.py` — HTTP controller `pos_web()` pattern
- `addons/point_of_sale/static/src/app/main.js` — `mountComponent` with `whenReady` bootstrap
- `addons/web/static/src/env.js` lines 226-250 — `mountComponent` implementation
- `addons/bus/static/src/services/bus_service.js` lines 174-181 — `addChannel()` starts connection
- `addons/bus/models/bus.py` lines 92-188 — pg_notify carries channel names only

---

*Stack research for: AI Debugger — IndexedDB persistence, export/import, trace management (v1.3)*
*Researched: 2026-02-22*
*All patterns verified against Odoo master source code at `/Users/joseph/clones/odoo/odoo/.worktrees/master/`*
