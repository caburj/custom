# Architecture Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1 → v1.2 theming → v1.3 persistence)
**Researched:** 2026-02-22
**Confidence:** HIGH (grounded in actual source at verified paths)

---

# v1.3 Persistence Architecture

> This section answers the research question for v1.3 milestone: How does IndexedDB persistence integrate with the existing OWL reactive store architecture? What are the integration points, new components, and data flow changes?

## The Core Problem

The existing store is `useState(new Map())` in `AiDebugApp`. OWL's reactive proxy observes `.set()`, `.delete()`, and `.clear()` calls on the Map and triggers re-renders. This reactive Map is the single source of truth — every component reads from it.

IndexedDB is an async key-value store. It cannot be directly observed by OWL. The integration must preserve the existing reactive Map as the runtime source of truth while using IDB as a durable backing store that persists across page refreshes.

The relationship is **write-through caching**: every mutation to the reactive Map also writes to IDB (fire-and-forget async). On page load, IDB is read once to populate the Map before the bus subscription starts.

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                  INSTRUMENTATION LAYER (unchanged)                   │
│  AiSessionDebug → bus.bus → WebSocket → AiDebugApp bus handlers      │
├──────────────────────────────────────────────────────────────────────┤
│                 AiDebugApp (root OWL component)                      │
│                                                                      │
│  this.traces = useState(new Map())   ←── Runtime source of truth     │
│       │                                                              │
│       │  Every mutation (set/delete/clear) triggers:                 │
│       │    1. OWL reactive re-render (existing behavior)             │
│       │    2. IDB write (new — fire-and-forget async)                │
│       ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  db.js  (plain ES module, NOT an OWL service)               │     │
│  │  ├── openDB()          — opens/upgrades IDB                 │     │
│  │  ├── loadAllTraces()   — hydration read on startup          │     │
│  │  ├── saveTrace(trace)  — upsert full trace record           │     │
│  │  ├── deleteTrace(id)   — delete one record                  │     │
│  │  └── clearAllTraces()  — wipe entire store                  │     │
│  └──────────────────────┬──────────────────────────────────────┘     │
│                         │                                            │
│                         ▼                                            │
├──────────────────────────────────────────────────────────────────────┤
│                    IndexedDB (browser storage)                       │
│  Database: "ai_debug_v1"                                             │
│  Object store: "traces"                                              │
│  Key: trace_id (string UUID)                                         │
│  Value: plain JS object (serialized trace with nested arrays)        │
└──────────────────────────────────────────────────────────────────────┘
```

## Integration Points

### Integration Point 1: Hydration (page load → reactive Map)

**Location:** `AiDebugApp.setup()` → `onMounted` callback

**What changes:** Before subscribing to bus events, the component loads all persisted traces from IDB and populates `this.traces`.

**Why `onMounted` not `setup()`:** IDB reads are async. OWL `setup()` must be synchronous. `onMounted` fires after the first render but allows await.

**Why hydration must complete before bus subscription:** A `loop_end` or `iteration` event could arrive for a trace that already exists in IDB. If the Map isn't populated first, the handler's `if (!trace) return` guard skips the event and the trace becomes inconsistent.

**Sequence:**
```
onMounted async:
  1. await db.loadAllTraces()         → returns plain object array
  2. for each trace: reconstruct reactive Maps, set into this.traces
  3. this.busService.addChannel(...)  → bus subscription starts
  4. Incoming events update both this.traces and IDB
```

### Integration Point 2: Write-Through on Bus Events

**Location:** `AiDebugApp._onNewTrace`, `_onIteration`, `_onToolCall`, `_onLoopEnd`

**What changes:** After the existing Map mutation, call `db.saveTrace(this.traces.get(traceId))`. The call is fire-and-forget (`saveTrace(...).catch(console.error)`) — IDB failure does not break the UI.

**Why save the full trace on every event (not just changed fields):** IDB stores one record per trace. Updating the trace record means overwriting with the current full trace state. The alternative (per-event delta writes with separate stores for iterations/toolCalls) is a normalized DB schema — overkill for a developer tool with bounded trace counts.

**Why fire-and-forget:** IDB writes on a local device are fast (<1ms). Awaiting them in the bus handler would delay re-renders unnecessarily. If an IDB write fails (quota exceeded, private browsing), the in-memory data is unaffected. The user sees a console error but the app keeps working.

**Which handlers write to IDB:**

| Handler | IDB action | Reason |
|---------|-----------|--------|
| `_onNewTrace` | `db.saveTrace(trace)` | New record created |
| `_onIteration` | `db.saveTrace(trace)` | Trace record updated (new iteration inside) |
| `_onToolCall` | `db.saveTrace(trace)` | Trace record updated (new toolCall inside) |
| `_onLoopEnd` | `db.saveTrace(trace)` | Trace record updated (status, ended_at, duration_ms) |

### Integration Point 3: Delete and Clear

**Location:** `AiDebugApp.deleteTrace(traceId)` (new method) and `AiDebugApp.clearAll()` (modified)

**What changes:**
- New `deleteTrace(traceId)` method: `this.traces.delete(traceId)` + `db.deleteTrace(traceId)` + clears selection if the deleted trace was selected.
- Modified `clearAll()`: adds `db.clearAllTraces()` after `this.traces.clear()`.

Both IDB calls are fire-and-forget.

### Integration Point 4: Export

**Location:** New method `AiDebugApp.exportTraces(traceIds)` (or a standalone utility function)

**What touches:** Only `this.traces` (in-memory). IDB is not involved in export.

**Flow:** Serialize selected traces from `this.traces` to a plain object array → `JSON.stringify` → create a `Blob` → `URL.createObjectURL` → programmatically click an `<a>` element → download.

**Why not read from IDB for export:** The in-memory reactive Map is the authoritative runtime state. Reading from IDB would require an async round-trip and could be stale if an IDB write hasn't committed yet. The Map has everything needed.

### Integration Point 5: Import

**Location:** New method `AiDebugApp.importTraces(file)` triggered by a file `<input>` change event

**Flow:**
```
File input change event
  → FileReader.readAsText(file)
  → JSON.parse(text)
  → validate structure (check required fields exist)
  → for each trace in parsed array:
      if !this.traces.has(trace.trace_id):          // skip duplicates
          reconstruct reactive Maps
          this.traces.set(trace.trace_id, trace)    // update UI
          db.saveTrace(serializedTrace)              // persist
```

**Why skip duplicates:** Import is additive. If the user imports a file they already have (from a previous session that was also live-captured), duplicate suppression prevents confusing doubled entries. The trace_id UUID is the deduplication key.

## New and Modified Components

### New: `static/src/app/db.js`

**What it is:** A plain ES module (not an OWL Component, not an Odoo service). Exports async functions that wrap the IDB API.

**Why not an Odoo service:** IDB is a browser primitive that doesn't need service lifecycle management. The Odoo service registry is for capabilities that need `env`, reactive state, or cross-component communication. `db.js` is a pure persistence utility — closer to a utility module than a service.

**Why not inline into `app.js`:** Separation of concerns. `app.js` is already ~350 lines. IDB schema definition and CRUD operations belong in their own module.

**API:**

```javascript
// db.js
const DB_NAME = "ai_debug_v1";
const DB_VERSION = 1;
const STORE_TRACES = "traces";

let _db = null;

async function openDB() { ... }
export async function loadAllTraces() { ... }    // returns plain objects
export async function saveTrace(plainTrace) { ... }  // upsert by trace_id
export async function deleteTrace(traceId) { ... }
export async function clearAllTraces() { ... }
```

**Database schema:**
- Database name: `"ai_debug_v1"` (versioned so future schema changes can use `onupgradeneeded`)
- Object store: `"traces"`, keyPath: `"trace_id"`
- No secondary indexes needed (all access is by `trace_id` or full scan)

### New: `static/src/app/toolbar.js` + `toolbar.xml`

**What it is:** A toolbar component rendered inside the sidebar header (replacing the raw `<button>` in the template) with export, import, and clear controls.

**Why extract to a component:** The header currently has one button (clear). With export and import added, three controls in a row warrant a dedicated component with its own template rather than cluttering `app.xml`.

**Props:** Receives `traces` (the reactive Map) for determining disabled states (e.g., export disabled when no traces).

**Events / callbacks:** Receives handler functions from `AiDebugApp` as props or uses `env` to call parent methods (via the standard OWL callback-props pattern).

**Alternative considered — keep inline in `app.xml`:** Acceptable if import/export UI is minimal (just two more buttons). But the file input element for import requires special handling (hidden input + programmatic click), which is cleaner in a dedicated component.

### Modified: `static/src/app/app.js`

**Changes:**

| Method/area | What changes |
|-------------|-------------|
| `setup()` | `import * as db from "./db"` at top of file |
| `setup()` > `onMounted` | Add `await hydration` before bus subscription |
| `_onNewTrace` | Add `db.saveTrace(...)` after Map mutation |
| `_onIteration` | Add `db.saveTrace(...)` after Map mutation |
| `_onToolCall` | Add `db.saveTrace(...)` after Map mutation |
| `_onLoopEnd` | Add `db.saveTrace(...)` after Map mutation |
| `clearAll()` | Add `db.clearAllTraces()` after `this.traces.clear()` |
| New `deleteTrace(id)` | `this.traces.delete(id)` + selection cleanup + `db.deleteTrace(id)` |
| New `exportTraces(ids)` | Serialize + download |
| New `importTraces(file)` | Parse + validate + hydrate + persist |

### Modified: `static/src/app/app.xml`

**Changes:** Add per-trace delete button in the sidebar tree. Add export/import controls to the toolbar. The clear button stays.

### No changes needed:

- `main.js` — mounting logic unchanged
- `detail/` components — all read from props, unaffected
- Python models, controllers, views — no backend changes
- Asset bundles — `db.js` and `toolbar.js` are picked up automatically by the `**/*.js` glob in `ai_debug.assets`

## Serialization: Reactive Maps → Plain Objects

The reactive Map and its nested Maps cannot be stored in IDB directly. IDB uses the structured clone algorithm, which does not support ES6 `Map` objects in all browsers (and even where supported, OWL's reactive proxy wrapper is not cloneable).

**Serialize (before IDB write):**

```javascript
function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        agent_name: trace.agent_name,
        model_name: trace.model_name,
        status: trace.status,
        started_at: trace.started_at?.toISOString(),
        ended_at: trace.ended_at?.toISOString(),
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        // Nested Maps → arrays of plain objects
        iterations: [...trace.iterations.values()].map(serializeIteration),
    };
}

function serializeIteration(iter) {
    return {
        ...iter,  // all scalar fields
        toolCalls: [...iter.toolCalls.values()],  // toolCalls have no nested Maps
        expanded: false,  // UI state not restored — fresh expand state on hydration
    };
}
```

**Key decisions in serialization:**
- `Date` → ISO string: IDB supports `Date` objects natively, but JSON export also needs ISO strings. Use ISO strings in IDB to be consistent.
- `expanded` reset to `false`: UI collapse/expand state is ephemeral. Restoring it would be confusing if the user had collapsed everything. All items start collapsed on hydration (existing default for iterations).
- `reactive()` wrapper is transparent to property reads: iterating `trace.iterations.values()` through the reactive proxy works — OWL's reactive proxy forwards property access to the underlying Map.

**Deserialize (after IDB read, before Map population):**

```javascript
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const iter of plain.iterations) {
        const toolCalls = reactive(new Map());
        for (const tc of iter.toolCalls) {
            toolCalls.set(tc.tool_call_id, tc);
        }
        iterations.set(iter.iteration_id, {
            ...iter,
            receivedAt: new Date(iter.receivedAt),  // reconstruct Date
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        iterations,
        expanded: false,  // all traces start collapsed after hydration
    };
}
```

**Why `reactive(new Map())` during hydration, not just `new Map()`:** The bus event handlers call `trace.iterations.set(...)` expecting to trigger OWL re-renders. If an event arrives for a hydrated trace and its `iterations` is a plain Map (not reactive), OWL will not re-render on the `.set()`. All Maps in the store must be reactive.

## Data Flow Changes

### Before v1.3 (v1.2 state)

```
Page load
  → this.traces = useState(new Map())    // empty
  → busService.addChannel('ai_debug')    // listen immediately
  → events update Map in memory
  → page refresh → all data lost
```

### After v1.3

```
Page load
  → this.traces = useState(new Map())    // empty
  → await db.loadAllTraces()             // read IDB
  → for each trace: hydrateTrace() → this.traces.set()   // populate Map
  → busService.addChannel('ai_debug')    // NOW listen
  → new events update Map AND IDB
  → page refresh → IDB → Map → same data restored
```

### Bus Event Flow (after v1.3)

```
Bus event: 'new_trace'
  → _onNewTrace(payload)
      → const iterations = reactive(new Map())
      → this.traces.set(traceId, {..., iterations})    // OWL re-render triggered
      → db.saveTrace(serializeTrace(this.traces.get(traceId)))  // IDB write (async, fire-and-forget)
```

### Delete Flow

```
User clicks delete button on trace X
  → deleteTrace(traceId)
      → if (this.state.selectedId === traceId) → clear selection
      → this.traces.delete(traceId)        // OWL re-render
      → db.deleteTrace(traceId)            // IDB delete (async, fire-and-forget)
```

### Export Flow

```
User clicks Export (for selected traces)
  → exportTraces(traceIds)
      → traces = traceIds.map(id => serializeTrace(this.traces.get(id)))
      → blob = new Blob([JSON.stringify({version: 1, traces})], {type: 'application/json'})
      → url = URL.createObjectURL(blob)
      → <a href=url download="ai_debug_traces_<timestamp>.json">.click()
      → URL.revokeObjectURL(url)
```

### Import Flow

```
User picks file in <input type="file">
  → importTraces(file)
      → text = await file.text()
      → parsed = JSON.parse(text)
      → validate(parsed)                   // check version, required fields
      → for each trace in parsed.traces:
          if this.traces.has(trace.trace_id): skip (duplicate)
          else:
              hydrated = hydrateTrace(trace)
              this.traces.set(hydrated.trace_id, hydrated)   // OWL re-render
              db.saveTrace(trace)                             // IDB write
```

## Recommended Project Structure (v1.3 additions)

```
ai_debug/
├── __manifest__.py                   # unchanged — new JS files picked up by glob
├── controllers/                      # unchanged
├── models/                           # unchanged
├── views/                            # unchanged
└── static/src/
    └── app/
        ├── main.js                   # unchanged
        ├── app.js                    # modified — hydration, write-through, delete, export, import
        ├── app.xml                   # modified — delete buttons, toolbar, file input
        ├── app.scss                  # possibly modified — styles for new controls
        ├── app.dark.scss             # possibly modified — dark overrides for new controls
        ├── db.js                     # NEW — IDB wrapper (openDB, loadAllTraces, saveTrace, etc.)
        ├── toolbar.js                # NEW (optional) — export/import/clear toolbar component
        ├── toolbar.xml               # NEW (optional) — toolbar template
        └── detail/                   # unchanged
```

## Build Order

Dependencies between tasks determine this order:

**Step 1: `db.js`** — the IDB wrapper. No dependencies on other new code. Can be written and tested (in browser console) before any UI changes. Write all five functions: `openDB`, `loadAllTraces`, `saveTrace`, `deleteTrace`, `clearAllTraces`. Verify: open DevTools → Application → IndexedDB after calling functions manually.

**Step 2: Hydration in `app.js` `onMounted`** — depends on `db.js` existing and `loadAllTraces` working. Add the hydration block and `hydrateTrace` helper. Must complete before bus subscription. Verify: add a trace, refresh the page, confirm trace reappears.

**Step 3: Write-through in bus handlers** — depends on hydration working (to confirm the round-trip). Add `db.saveTrace()` calls to all four handlers. Verify: trigger a new trace, refresh, see it restored with all iterations.

**Step 4: Delete single trace** — depends on write-through working (otherwise delete removes from Map but the item returns on next hydration). Add `deleteTrace()` method + delete button in `app.xml`. Verify: delete a trace, refresh, confirm it stays gone.

**Step 5: Clear all** — depends on `deleteTrace` pattern working. Modify `clearAll()` to also call `db.clearAllTraces()`. Already has a button in the UI. Verify: clear, refresh, see empty state.

**Step 6: Export** — depends on nothing new (reads from in-memory Map). Add `exportTraces()` method + export button. Verify: export JSON, inspect file structure.

**Step 7: Import** — depends on export working (need an export file to import). Add `importTraces()` + file input in UI. Verify: clear all, import the previously exported file, traces appear.

**Steps 6 and 7 are independent of Steps 4 and 5** — they can be done in any order after Step 3.

## Architectural Patterns

### Pattern 1: Write-Through Cache with Fire-and-Forget Persistence

**What:** The reactive Map is the in-memory cache. Every write to the Map immediately fires an async IDB write without awaiting it.

**When to use:** When UI responsiveness matters more than durability guarantees. For a developer tool, a lost write (IDB error) is acceptable; the worst case is re-running the agentic loop.

**Trade-offs:**
- Pro: Zero latency added to bus event processing.
- Pro: IDB failures don't crash the UI.
- Con: A write failure means the next page load won't see the latest state of that trace. Acceptable for this use case.

**Example:**
```javascript
this._onNewTrace = (payload) => {
    // Existing: update in-memory Map (OWL re-renders)
    this.traces.set(payload.trace_id, { ...traceData, iterations });
    // New: persist to IDB (fire-and-forget)
    db.saveTrace(serializeTrace(this.traces.get(payload.trace_id)))
        .catch(console.error);
};
```

### Pattern 2: Hydrate-Before-Subscribe

**What:** On page load, fully populate the reactive Map from IDB before subscribing to bus events.

**When to use:** When live events reference existing persisted data. If a loop started before the page was opened, and the user refreshes mid-loop, the `iteration` event references a `trace_id` that only exists in IDB.

**Trade-offs:**
- Pro: Ensures event handlers can always find their parent trace.
- Pro: No async gap where events arrive for traces not yet in the Map.
- Con: Small startup latency while IDB is read. Acceptable — IDB reads are <10ms for dozens of traces.

**Example:**
```javascript
onMounted(async () => {
    // Hydrate first — fully awaited
    const plainTraces = await db.loadAllTraces();
    for (const plain of plainTraces) {
        this.traces.set(plain.trace_id, hydrateTrace(plain));
    }
    // Now safe to subscribe — any events for existing traces will find them
    this.busService.subscribe("new_trace", this._onNewTrace);
    // ... other subscriptions ...
    await this.busService.addChannel("ai_debug");
});
```

### Pattern 3: Serialize-At-Write, Deserialize-At-Read

**What:** Convert reactive Maps to plain objects immediately before IDB writes. Convert plain objects back to reactive Maps immediately after IDB reads. The IDB layer only ever sees plain objects.

**When to use:** Any time you persist data from an OWL reactive store.

**Trade-offs:**
- Pro: Cleanly separates the reactive layer from the storage layer.
- Pro: The serialized format doubles as the export format — same structure used in JSON files.
- Con: Requires serialization/deserialization code. For a bounded schema (~3 levels deep) this is straightforward.

### Pattern 4: Plain Module for Storage, Not OWL Service

**What:** `db.js` is a plain ES module, not registered in the Odoo service registry.

**When to use:** When the capability is stateless from OWL's perspective (IDB is a browser API, not a reactive dependency) and doesn't need `env` access.

**Trade-offs:**
- Pro: Simpler. No `registry.add()`, no `useService()` call, no service lifecycle.
- Pro: Testable in isolation without an OWL env.
- Con: Can't be overridden or mocked via the service registry. For a developer tool, this is acceptable — there's no production variant that needs to substitute a different storage backend.

## Anti-Patterns

### Anti-Pattern 1: Storing Reactive Maps Directly in IDB

**What people do:** Call `db.saveTrace(this.traces.get(id))` and pass the reactive proxy directly to IDB.

**Why it's wrong:** The structured clone algorithm (used by IDB internally) does not support OWL's Proxy objects. The write will throw a `DataCloneError`. Even if IDB supported Maps, OWL's reactive Proxy wrapper is not structurally clonable.

**Do this instead:** Always serialize before writing: `db.saveTrace(serializeTrace(this.traces.get(id)))`.

### Anti-Pattern 2: Subscribing to Bus Before Hydration Completes

**What people do:** Start the bus subscription in parallel with the IDB read to minimize startup time.

**Why it's wrong:** If an `iteration` event arrives with a `trace_id` that is in IDB but not yet in `this.traces`, the handler's `if (!trace) return` guard drops the event. The iteration is lost — it won't appear in the UI even after hydration finishes, because hydration only reads what was already written.

**Do this instead:** Always `await` the full hydration (including `this.traces.set` for all loaded traces) before calling `busService.addChannel()`.

### Anti-Pattern 3: Normalizing IDB Schema (Separate Stores for Iterations/ToolCalls)

**What people do:** Create separate IDB object stores for traces, iterations, and tool_calls, joined by foreign keys.

**Why it's wrong:** Normalized IDB requires multiple transactions for every write and read. For a developer tool with at most a few dozen traces and a few hundred total records, the overhead is not justified. Hydration becomes a join query. Writes require three coordinated transactions.

**Do this instead:** Store each trace as one denormalized record with nested arrays for iterations and tool calls. Simple upsert, simple scan.

### Anti-Pattern 4: Awaiting IDB Writes in Bus Handlers

**What people do:** `await db.saveTrace(...)` in `_onNewTrace` to guarantee the write completed before the handler returns.

**Why it's wrong:** Bus event handlers run synchronously in the OWL reactive context. Awaiting in the handler doesn't block the next event, but it does introduce async branching that makes the handler harder to reason about. More importantly, IDB write latency (typically <1ms) does not justify the added complexity. If a write fails, the user sees a console error — no worse than before persistence existed.

**Do this instead:** Fire-and-forget: `db.saveTrace(...).catch(console.error)`.

### Anti-Pattern 5: Using localStorage Instead of IndexedDB

**What people do:** Serialize all traces to a single JSON string in localStorage.

**Why it's wrong:** localStorage has a 5-10MB quota per origin. A multi-turn conversation with RAG-augmented context can produce payloads of 50KB+ per iteration. A session with 10 iterations and 3 tool calls each is ~2MB+. Multiple sessions will quickly exhaust localStorage. Additionally, localStorage serializes everything synchronously — writing 2MB on every bus event would block the main thread.

**Do this instead:** IndexedDB has no practical size limit (quota is a fraction of disk space, typically gigabytes). It is async, so writes don't block the UI thread. IDB is the correct tool for structured, potentially large browser-side persistence.

## Export File Format

The export file should be self-describing and round-trippable via import.

```json
{
    "version": 1,
    "exported_at": "2026-02-22T10:30:00.000Z",
    "traces": [
        {
            "trace_id": "uuid-here",
            "agent_name": "...",
            "model_name": "...",
            "status": "success",
            "started_at": "2026-02-22T10:00:00.000Z",
            "ended_at": "2026-02-22T10:01:30.000Z",
            "duration_ms": 90000,
            "instructions": "...",
            "tools": [...],
            "state_snapshot": {...},
            "iterations": [
                {
                    "iteration_id": "uuid-here",
                    "trace_id": "uuid-here",
                    "iteration_index": 1,
                    "has_error": false,
                    "receivedAt": "2026-02-22T10:00:01.000Z",
                    "expanded": false,
                    "messages_sent": [...],
                    "raw_response": {...},
                    "is_final": true,
                    "error": null,
                    "toolCalls": [
                        {
                            "tool_call_id": "uuid-here",
                            "iteration_id": "uuid-here",
                            "tool_name": "...",
                            "success": true,
                            "args": {...},
                            "result": {...},
                            "error": null,
                            "state_before": {...},
                            "state_after": {...},
                            "call_id": null
                        }
                    ]
                }
            ]
        }
    ]
}
```

**`version` field:** Allows future imports to detect old export formats and apply migrations or show warnings.

**IDB storage format is identical to export format** — same serialization function is used for both. This is not an accident; it simplifies reasoning about what's stored and what's exported.

## Integration Points Summary

| Point | Component | Change Type | Notes |
|-------|-----------|-------------|-------|
| IDB open/schema | `db.js` (new) | New | `openDB()` called lazily on first db operation |
| Hydration | `app.js` `onMounted` | Modified | Await `db.loadAllTraces()` before bus subscribe |
| Write-through | `app.js` `_onNewTrace/Iteration/ToolCall/LoopEnd` | Modified | Fire-and-forget `db.saveTrace()` after each Map mutation |
| Delete | `app.js` `deleteTrace()` | New method | Symmetric: `this.traces.delete()` + `db.deleteTrace()` |
| Clear all | `app.js` `clearAll()` | Modified | Adds `db.clearAllTraces()` |
| Export | `app.js` `exportTraces()` | New method | In-memory only; no IDB involvement |
| Import | `app.js` `importTraces()` | New method | File → parse → `this.traces.set()` + `db.saveTrace()` |
| UI controls | `app.xml` | Modified | Delete buttons per trace; export/import buttons in toolbar |

## Sources

**v1.3 architecture sources (HIGH confidence — direct source reads and reasoning from existing codebase):**

- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — complete existing reactive store architecture, all bus event handlers, `onMounted` lifecycle
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` — existing template structure (sidebar tree, header controls)
- `/Users/joseph/clones/odoo/custom/ai_debug/__manifest__.py` — asset bundle glob patterns (confirm new files are picked up automatically)
- `/Users/joseph/clones/odoo/custom/.planning/PROJECT.md` — v1.3 requirements: persist, hydrate, delete, clear, export, import
- MDN IndexedDB API — structured clone algorithm limitations (Map/Proxy not cloneable), IDB quota behavior, `keyPath` vs `autoIncrement` key strategies
- OWL source — `reactive()` + `useState()` proxy mechanics: mutations on proxied Maps trigger render callbacks

---

# v1.2 Theming Architecture

> This section answers the research questions for v1.2 milestone: How does native theming integrate with a standalone OWL app? How is `color_scheme` detected? How does the template serve the correct CSS bundle? How should SCSS be restructured?

## How Odoo's Theming System Works

Odoo's theme system has three layers. Understanding all three is required to integrate correctly.

### Layer 1: User preference storage (enterprise only)

`web_enterprise/models/res_users_settings.py` adds a `color_scheme` field (`Selection: light/dark/system`). `res.users` exposes this as `color_scheme` (via `related`). The preference persists across sessions.

### Layer 2: Server-side color_scheme resolution

`web_enterprise/models/ir_http.py` overrides `color_scheme()`:

```python
def color_scheme(self):
    cookie_scheme = request.httprequest.cookies.get('color_scheme')
    scheme = cookie_scheme if cookie_scheme else super().color_scheme()
    if user := request.env.user:
        if user._is_public():
            return super().color_scheme()           # light for public
        if user_scheme := user.res_users_settings_id.color_scheme:
            if user_scheme in ('light', 'dark'):    # not 'system'
                return user_scheme                  # user explicit choice wins
    return scheme                                   # cookie fallback
```

The base `web/models/ir_http.py` returns `"light"` as the hardcoded default. The enterprise override reads the cookie first, then the user's explicit setting if it's not `'system'`. **'system' is not passed through** — the server cannot know the OS preference, so `color_scheme()` never returns `'system'`, only `'light'` or `'dark'`.

### Layer 3: Cookie synchronization

`web_enterprise/controllers/home.py` sets the cookie on every webclient visit:

```python
@route()
def web_client(self, s_action=None, **kw):
    response = super().web_client(s_action, **kw)
    if response.status_code == 200:
        response.set_cookie('color_scheme', request.env['ir.http'].color_scheme())
    return response
```

This means: every time the user visits `/odoo`, Odoo sets (or refreshes) the `color_scheme` cookie to `'light'` or `'dark'`. **The ai_debug controller can read this cookie directly** to determine which CSS bundle to serve.

## Data Flow: Theme Detection to CSS Bundle

```
User sets theme in Odoo Settings
    ↓
res.users_settings.color_scheme = 'dark'
    ↓
User visits /odoo → web_enterprise.home.web_client()
    → request.env['ir.http'].color_scheme()
        → reads user.res_users_settings_id.color_scheme → 'dark'
    → response.set_cookie('color_scheme', 'dark')
    ↓
Cookie 'color_scheme' = 'dark' persists in browser
    ↓
User navigates to /ai-debug
    ↓
AiDebugController.ai_debug()
    → request.httprequest.cookies.get('color_scheme')  # 'dark'
    → pass to QWeb template context: color_scheme='dark'
    ↓
ai_debug.index QWeb template
    → <t t-if="color_scheme == 'dark'">
    →     <t t-call-assets="ai_debug.assets_dark" .../>
    → <t t-else="">
    →     <t t-call-assets="ai_debug.assets" .../>
    ↓
Browser loads either ai_debug.assets (light) or ai_debug.assets_dark (dark)
    ↓
Bootstrap CSS variables resolve to light or dark values
    ↓
App renders with Odoo-native color palette
```

**Confidence: HIGH** — verified directly from `web_enterprise/models/ir_http.py`, `web_enterprise/controllers/home.py`, and `web/views/webclient_templates.xml` (`web.webclient_bootstrap` template shows the exact pattern).

## The Exact Webclient Bootstrap Pattern (Reference)

`web/views/webclient_templates.xml` (`web.webclient_bootstrap`) is the authoritative reference:

```xml
<t t-call-assets="web.assets_web_print" media="print" t-js="false"/>
<t t-call-assets="web.assets_web" t-css="false"/>   <!-- always: JS only -->

<t t-if="color_scheme == 'dark'">
    <t t-call-assets="web.assets_web_dark" media="screen" t-js="false"/>
</t>
<t t-else="">
    <t t-call-assets="web.assets_web" media="screen" t-js="false"/>
</t>
```

Key observations:
1. JS is loaded once from `web.assets_web` (CSS-free pass, `t-css="false"`).
2. CSS is loaded separately from either the light bundle or the dark bundle.
3. `web.assets_web_dark` includes everything in `web.assets_web` PLUS dark SCSS files.
4. The `media="screen"` attribute is added to the CSS link tag to allow a print bundle to coexist.

The ai_debug template should follow this same split: one JS-only bundle, one CSS-only conditional.

## How `web.assets_web_dark` Works

`web/__manifest__.py`:
```python
"web.assets_web_dark": [
    ('include', 'web.assets_web'),        # everything in light mode
    'web/static/src/**/*.dark.scss',      # plus all *.dark.scss files
],
```

`web_enterprise/__manifest__.py` extends it:
```python
"web.assets_web_dark": [
    ('include', 'web.dark_mode_variables'),     # dark SCSS variable overrides
    # web._assets_backend_helpers overrides:
    ('before', 'web_enterprise/static/src/scss/bootstrap_overridden.scss',
               'web_enterprise/static/src/scss/bootstrap_overridden.dark.scss'),
    ('after', 'web/static/lib/bootstrap/scss/_functions.scss',
              'web_enterprise/static/src/scss/bs_functions_overridden.dark.scss'),
    # assets_backend dark files:
    'web_enterprise/static/src/**/*.dark.scss',
],
```

The `web.dark_mode_variables` sub-bundle prepends dark SCSS variable overrides before the light-mode variable files. This means Sass compiles with dark values, so all compiled CSS already uses the dark palette. The `.dark.scss` files then add component-specific overrides that can't be handled by variables alone.

**Critical insight:** The dark mode is NOT CSS `prefers-color-scheme` media query. It is a **server-selected separate CSS bundle**. The server decides which bundle to serve based on the user's stored preference. There is no runtime CSS switching.

## How Bootstrap CSS Variables Are Emitted

Bootstrap 5 emits CSS custom properties on `:root` from `_root.scss`:

```css
:root, [data-bs-theme="light"] {
  --bs-body-color: #{$body-color};
  --bs-body-bg: #{$body-bg};
  --bs-border-color: #{$border-color};
  --bs-secondary-bg: #{$body-secondary-bg};
  --bs-tertiary-bg: #{$body-tertiary-bg};
  /* ...many more... */
}
```

The SCSS variables (`$body-color`, `$body-bg`, etc.) are resolved at Sass compile time. In the dark bundle, Odoo's dark variable overrides are prepended, so Bootstrap's `$body-bg` compiles to a dark value like `#1B1D26`. The resulting `--bs-body-bg` CSS custom property in the dark bundle's output is already the dark color — it was baked in at build time, not switched at runtime.

**What this means for ai_debug:** By using `var(--bs-body-bg)` instead of hardcoded `#1e1e2e`, the SCSS will pick up whichever value the loaded bundle compiled in.

## Available Bootstrap CSS Custom Properties

These are available from the `web.assets_backend` (and `ai_debug.assets`) bundle and change value between light and dark bundles:

| CSS Custom Property | Light value (approx) | Dark value (approx) | Use for |
|---------------------|----------------------|----------------------|---------|
| `--bs-body-bg` | `#ffffff` | `#1B1D26` (gray-100) | Page/panel backgrounds |
| `--bs-body-color` | `#212529` | `#E4E4E4` (gray-900) | Primary text |
| `--bs-secondary-bg` | `#f8f9fa` | `#262A36` (gray-200) | Sidebar, header backgrounds |
| `--bs-tertiary-bg` | `#e9ecef` | `#3C3E4B` (gray-300) | Hover states |
| `--bs-border-color` | `#dee2e6` | varies | Dividers, borders |
| `--bs-secondary-color` | `#6c757d` | `#7E8392` (gray-600) | Muted text |
| `--bs-emphasis-color` | `#000` | `#E4E4E4` | Strong emphasis text |
| `--bs-primary` | `#017e84` | adjusted | Accent/action color |
| `--bs-success` | `#198754` | `#1dc959` | Success indicators |
| `--bs-danger` | `#dc3545` | `#ff5757` | Error indicators |
| `--bs-warning` | `#ffc107` | `#FBB56A` | Warning indicators |

**Confidence: HIGH** — verified from `_root.scss`, `primary_variables.dark.scss`, and `bootstrap_overridden.dark.scss`.

Note: The grays (`$o-gray-100` through `$o-gray-900`) are inverted in dark mode: gray-100 is the darkest (background), gray-900 is the lightest (text). Bootstrap CSS custom properties like `--bs-secondary-bg` map to these.

## Odoo-Specific CSS Custom Properties

Odoo defines additional `--o-*` CSS custom properties. These are sparse and not comprehensively emitted. For theming, prefer Bootstrap's `--bs-*` properties which are well-defined and consistently emitted in both bundles.

## How the POS Handles It (Comparison)

POS (`point_of_sale/views/pos_assets_index.xml`) uses a POS-specific cookie:

```xml
<t t-if="request.cookies.get('pos_color_scheme') == 'dark'">
    <t t-call-assets="point_of_sale.assets_prod_dark"/>
</t>
<t t-else="">
    <t t-call-assets="point_of_sale.assets_prod"/>
</t>
```

POS reads a `pos_color_scheme` cookie (separate from `color_scheme`). ai_debug should read the main `color_scheme` cookie directly since it serves internal Odoo users who have already set their preference via the standard Odoo settings.

## Architecture for v1.2

### Modified Files

**`controllers/main.py`** (modified — add `color_scheme` to template context):

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
        color_scheme = request.httprequest.cookies.get('color_scheme', 'light')
        return request.render('ai_debug.index', {
            'session_info': session_info,
            'color_scheme': color_scheme,
        })
```

**`views/ai_debug_index.xml`** (modified — conditional CSS bundle, JS-only base):

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
                <!-- JS only (no CSS) — same for both themes -->
                <t t-call-assets="ai_debug.assets" t-css="false"/>
                <!-- CSS only — conditional on color_scheme cookie -->
                <t t-if="color_scheme == 'dark'">
                    <t t-call-assets="ai_debug.assets_dark" t-js="false"/>
                </t>
                <t t-else="">
                    <t t-call-assets="ai_debug.assets" t-js="false"/>
                </t>
            </head>
            <body/>
        </html>
    </template>
</odoo>
```

**`__manifest__.py`** (modified — add `ai_debug.assets_dark` bundle):

```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
        # SCSS that works in light mode (no hardcoded dark colors)
        'ai_debug/static/src/app/**/*.scss',
        # Exclude dark-mode-only files from the base bundle
        ('remove', 'ai_debug/static/src/app/**/*.dark.scss'),
    ],
    'ai_debug.assets_dark': [
        ('include', 'ai_debug.assets'),
        # Dark mode variable overrides (reuse enterprise's dark variables)
        ('include', 'web.dark_mode_variables'),
        # Component-specific dark overrides
        'ai_debug/static/src/app/**/*.dark.scss',
    ],
    'web.assets_backend': [
        'ai_debug/static/src/debug_menu_button.js',
    ],
},
```

**`static/src/app/app.scss`** (modified — replace hardcoded colors with CSS vars):

The existing `app.scss` has ~650 lines of hardcoded Catppuccin Mocha colors. These are replaced with Bootstrap CSS custom properties. The file stays as `app.scss` (light-mode baseline). A new `app.dark.scss` handles any colors that can't be expressed via `--bs-*` vars alone.

**`static/src/app/app.dark.scss`** (new — dark-only overrides for remaining values):

This file is only included in `ai_debug.assets_dark`. It handles the few cases where the dark theme needs values that differ from what `--bs-*` provides (e.g., custom Catppuccin accent colors for JSON syntax highlighting, status dots, badge colors).

### SCSS Restructuring Strategy

The restructuring maps each hardcoded Catppuccin Mocha color to the semantically closest Bootstrap CSS custom property:

| Current hardcoded value | Semantic meaning | Replacement |
|-------------------------|-----------------|-------------|
| `#1e1e2e` (base) | Page background | `var(--bs-body-bg)` |
| `#181825` (mantle) | Header/darker surface | `var(--bs-secondary-bg)` |
| `#11111b` (crust) | Detail panel darkest | `var(--bs-body-bg)` or `color-mix(in srgb, var(--bs-body-bg) 80%, black)` |
| `#313244` (surface1) | Borders, dividers | `var(--bs-border-color)` |
| `#45475a` (surface2) | Subtle borders | `color-mix(in srgb, var(--bs-border-color) 70%, var(--bs-body-bg))` |
| `#585b70` (overlay0) | Disabled/muted text | `var(--bs-secondary-color)` |
| `#6c7086` (overlay1) | Section labels | `var(--bs-secondary-color)` |
| `#a6adc8` (subtext1) | Secondary text | `var(--bs-secondary-color)` |
| `#cdd6f4` (text) | Primary text | `var(--bs-body-color)` |
| `#89b4fa` (blue) | Selected/accent | `var(--bs-primary)` |
| `#a6e3a1` (green) | Success | `var(--bs-success)` |
| `#f38ba8` (red) | Error/danger | `var(--bs-danger)` |
| `#f9e2af` (yellow) | Warning | `var(--bs-warning)` |
| `#fab387` (peach) | Numbers (JSON) | `var(--bs-warning)` |
| `#cba6f7` (mauve) | Booleans (JSON) | `var(--bs-primary)` or keep in `app.dark.scss` |
| `#2a2a3e` (hover) | Tree row hover | `var(--bs-tertiary-bg)` |
| `#2d3748` (selected bg) | Tree row selected | `color-mix(in srgb, var(--bs-primary) 15%, var(--bs-body-bg))` |
| `rgba(137,180,250,.05)` (ancestor) | Ancestor tint | `color-mix(in srgb, var(--bs-primary) 5%, transparent)` |

Colors that cannot be expressed with a single CSS variable (syntax highlighting colors like JSON key blue, JSON string green) belong in `app.dark.scss` as dark-specific overrides.

**Light mode baseline:** When `ai_debug.assets` (not dark) is loaded, the Bootstrap CSS variables resolve to light values. `app.scss` using `var(--bs-body-bg)` will naturally get a white/light background. The app will look like a standard Odoo light-mode page, which is the correct behavior.

### New vs Modified Files Summary

| File | Status | What changes |
|------|--------|--------------|
| `controllers/main.py` | **Modified** | Add `color_scheme` cookie read, pass to template context |
| `views/ai_debug_index.xml` | **Modified** | Split `t-call-assets` into JS-only + CSS conditional |
| `__manifest__.py` | **Modified** | Add `ai_debug.assets_dark` bundle definition; update `ai_debug.assets` to exclude `*.dark.scss` |
| `static/src/app/app.scss` | **Modified** | Replace all hardcoded hex colors with `var(--bs-*)` properties |
| `static/src/app/app.dark.scss` | **New** | Dark-only overrides for values not expressible via BS vars (JSON syntax colors, status dot colors) |

No JS files change. No Python models change. No bus protocol changes.

### Build Order for v1.2

Dependencies determine this order:

1. **`controllers/main.py`** — read the `color_scheme` cookie, add to render context. Verifiable immediately: hit `/ai-debug`, check QWeb rendering context in debug mode.

2. **`views/ai_debug_index.xml`** — split `t-call-assets` into JS-only + conditional CSS. Verifiable: with dark cookie set, check browser DevTools network tab for which CSS file loads.

3. **`__manifest__.py`** — add `ai_debug.assets_dark` bundle. Must be done before step 2 is useful, otherwise `ai_debug.assets_dark` is undefined and the template crashes. **Do steps 2 and 3 together.**

4. **`static/src/app/app.scss`** — replace hardcoded colors with CSS custom properties. Do this color category by category: backgrounds first (body, header, sidebar), then borders, then text, then accent/status colors. Verify in both light and dark mode after each group.

5. **`static/src/app/app.dark.scss`** — add overrides for any remaining values that the light-mode `var(--bs-*)` substitutions don't handle correctly in dark mode (e.g., JSON syntax highlighting colors, status dot colors that need Catppuccin-specific accents).

**Step 3 must precede step 2** (bundle must exist before template references it). Steps 4 and 5 are independent of steps 1-3 and can be done iteratively after the infrastructure is in place.

---

# v1.1 Base Architecture (Unchanged)

> The following is the v1.1 architecture document, retained for reference.

## What Changed in v1.1

v1.0 used: persistent DB models + backend XML views + OWL client action panel.
v1.1 replaces that with: no DB models + standalone OWL app at `/ai-debug` + full bus payloads.

This document focuses on the v1.1 target architecture. v1.0 patterns that carry over unchanged (generator yield passthrough, separate cursor bus sends) are referenced but not re-explained in full.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INSTRUMENTATION LAYER (unchanged)                │
│                                                                      │
│  AiSessionDebug (_inherit = 'ai.session')                            │
│  ├── _run_agentic_loop()   — wraps super(), captures events          │
│  ├── _handle_tool_calls()  — wraps super(), captures tool events     │
│  └── _generate_next_response() — captures instructions + RAG        │
│           │                                                          │
│           │  No DB writes. Sends via separate cursor:                │
│           ▼                                                          │
├──────────────────────────────────────────────────────────────────────┤
│                  REAL-TIME NOTIFICATION LAYER                        │
│                                                                      │
│  bus.bus._sendone('ai_debug:traces', event_type, FULL_PAYLOAD)       │
│                                                                      │
│  Events (all carry full data — no lazy DB reads):                    │
│  ├── ai_debug/new_trace    — loop start, instructions, tools def     │
│  ├── ai_debug/iteration    — messages_sent, raw_response, timing     │
│  ├── ai_debug/tool_call    — args, result, state_before/after        │
│  └── ai_debug/trace_update — state, termination_reason              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                       HTTP LAYER (new in v1.1)                       │
│                                                                      │
│  AiDebugController                                                   │
│  └── GET /ai-debug  →  renders 'ai_debug.index' template            │
│                         (auth='user', internal users only)           │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                   STANDALONE OWL APP LAYER (new)                     │
│                                                                      │
│  ai_debug.index (QWeb template — full HTML page, no Odoo chrome)     │
│  └── loads asset bundle: ai_debug.assets                            │
│      └── main.js → mountComponent(AiDebugApp, document.body)        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  AiDebugApp  (root OWL component)                           │     │
│  │  ├── TraceList  (sidebar — loops, with agent label)         │     │
│  │  │   ├── LoopItem (clickable, shows status badge)          │     │
│  │  │   │   ├── IterationItem (LLM call, duration)           │     │
│  │  │   │   │   └── ToolCallItem (tool name, success badge)  │     │
│  │  │   │   └── ...                                          │     │
│  │  │   └── ...                                              │     │
│  │  └── DetailPanel  (right pane — context for selection)     │     │
│  │      ├── LoopDetail  (system prompt, tools definition)     │     │
│  │      ├── IterationDetail  (messages sent, raw response)    │     │
│  │      └── ToolCallDetail  (args, result, state diff)        │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| `AiSessionDebug` | Generator yield passthrough; emits full bus payloads | `TransientModel`, `_inherit = 'ai.session'`, unchanged from v1.0 except payload content |
| `ir.websocket` (inherit) | Restricts `ai_debug:*` channels to `group_system` users | `AbstractModel`, `_build_bus_channel_list` override — carried over from v1.0 |
| `AiDebugController` | Serves the standalone app HTML page at `/ai-debug` | `http.Controller`, `auth='user'`, renders `ai_debug.index` QWeb template |
| `ai_debug.index` (template) | Full HTML page: CSRF token, `__session_info__`, asset bundle | QWeb template declared in views XML; bootstraps OWL app |
| `ai_debug.assets` (bundle) | JS + CSS for the standalone app | Declared in `__manifest__.py`; includes OWL, web core services, bus service |
| `main.js` | Boots the OWL app | `mountComponent(AiDebugApp, document.body)` from `@web/env` |
| `AiDebugApp` | Root component; owns bus subscription and all trace state | OWL `Component`; `useState` for traces map; `useService('bus_service')` |
| `TraceList` | Sidebar tree: loop > iteration > tool call | Receives traces from parent; emits selection events upward |
| `DetailPanel` | Right pane; renders context for selected item | Receives `selection` prop (type + data); switches between sub-components |
| `JsonTree` | Collapsible JSON tree renderer | Pure presentational; carries over from v1.0 |
| `StateDiff` | Before/after state comparison | Pure presentational; carries over from v1.0 |

---

## Recommended Project Structure (v1.1 actual + v1.2 + v1.3 additions)

```
ai_debug/
├── __manifest__.py                   # v1.2: add assets_dark bundle
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                       # v1.2: add color_scheme cookie read
├── models/
│   ├── __init__.py
│   ├── ai_session.py                 # unchanged: generator instrumentation
│   └── ir_websocket.py               # unchanged: channel access control
├── views/
│   └── ai_debug_index.xml            # v1.2: conditional CSS bundle
└── static/src/
    ├── debug_menu_button.js
    └── app/
        ├── main.js
        ├── app.js                    # v1.3: hydration, write-through, delete, export, import
        ├── app.xml                   # v1.3: delete buttons, file input
        ├── app.scss                  # v1.2: replace hex colors with var(--bs-*)
        ├── app.dark.scss             # v1.2: NEW — dark-only overrides
        ├── db.js                     # v1.3: NEW — IDB wrapper
        └── detail/
            ├── iter_detail.js/xml
            ├── json_tree.js/xml
            ├── loop_detail.js/xml
            ├── state_diff.js/xml
            ├── tc_detail.js/xml
            └── text_popup.js/xml
```

---

## Architectural Patterns

### Pattern 1: Standalone OWL App — Controller + Template + Asset Bundle

This is the POS Self Order pattern, which is simpler than full POS and has no session management complexity.

**What:** A dedicated HTTP route renders a full HTML page (no Odoo chrome/navbar). The template inlines the CSRF token and `__session_info__` as a JS global, then loads a custom asset bundle. The bundle's `main.js` boots an OWL app via `mountComponent`.

**When to use:** Any tool that should live in its own browser tab, free of the Odoo backend navbar.

`mountComponent` from `@web/env` calls `makeEnv()` + `startServices(env)` internally, which initializes the Odoo service registry (including `bus_service`, `orm`, `rpc`, `notification`). All services registered in `web.assets_backend` service registry are available.

### Pattern 2: Full Bus Payloads — No Lazy ORM Reads

**What:** The bus payloads carry complete data. There are no DB models, so all data must travel in the bus payload at event time.

**When to use:** Always, when there is no DB to fall back to.

**Trade-offs:** Payloads can be large. `messages_sent` for a multi-turn conversation can be tens of KB. The `bus_bus` table stores each payload as JSONB — no size constraint from pg_notify (that limit applies to the channel list notification, not the message payload).

### Pattern 3: OWL App State Management — Reactive Store in Root Component

**What:** The root component `AiDebugApp` owns the entire application state as `useState` objects. Child components receive state slices as props. Uses `useState(new Map())` for the trace store (not `reactive()` without callback, which uses NO_CALLBACK sentinel and blocks OWL render).

**When to use:** Apps with a bounded set of entity types and simple selection state.

### Pattern 4: Conditional CSS Bundle — Server-Side Theme Selection

**What:** The controller reads the `color_scheme` cookie set by the standard Odoo webclient. The QWeb template conditionally loads `ai_debug.assets_dark` vs `ai_debug.assets` for the CSS. JS is always loaded from `ai_debug.assets` (t-css="false").

**When to use:** Any standalone Odoo app that should respect user theme preference.

**Trade-offs:** Theme is determined at page load. If the user changes their Odoo theme in another tab, they must reload `/ai-debug` to pick it up. This matches the behavior of the main Odoo webclient.

---

## Data Flow

### Theme Selection Flow

```
User visits /odoo → Odoo sets color_scheme cookie ('light' or 'dark')
    ↓
User navigates to /ai-debug
    ↓
AiDebugController reads cookie → passes color_scheme to QWeb context
    ↓
QWeb template: t-if="color_scheme == 'dark'" → loads assets_dark CSS
    ↓
Bootstrap CSS vars resolve to dark values (compiled into bundle at build time)
    ↓
app.scss's var(--bs-body-bg) etc. get dark colors automatically
```

### Capture Flow (Python — write path)

```
HTTP call triggers agentic loop
    ↓
AiSessionDebug._run_agentic_loop()
    ├── Generate trace_id = uuid.uuid4()
    ├── _debug_bus_send_full('new_trace', {full trace payload})
    ├── for each LLM yield:
    │   ├── Generate iteration_id = uuid.uuid4()
    │   ├── _debug_bus_send_full('iteration', {full iteration payload})
    │   └── for each tool result:
    │       └── _debug_bus_send_full('tool_call', {full tool payload})
    └── _debug_bus_send_full('loop_end', {termination reason, duration})
```

### Live App Flow (OWL — read path)

```
User navigates to /ai-debug
    ↓
Bundle loads (JS + appropriate CSS bundle)
    ↓
main.js: mountComponent(AiDebugApp, document.body)
    → makeEnv() + startServices(env)
    → AiDebugApp.setup() → busService.addChannel('ai_debug')
    ↓
Agentic loop fires on another tab
    → bus.bus → WebSocket → browser
    → AiDebugApp handlers update state
    → OWL re-renders sidebar + detail panel
```

---

## Integration Points

### Theme Integration

| Component | Integration | Notes |
|-----------|-------------|-------|
| `color_scheme` cookie | Read in `controllers/main.py` | Set by Odoo enterprise webclient; fallback to `'light'` |
| `ai_debug.assets_dark` bundle | Includes `ai_debug.assets` + dark SCSS | JS not duplicated — loaded from base bundle with `t-css="false"` |
| Bootstrap CSS vars | Used in `app.scss` | Values baked in at Sass compile time; differ between light and dark bundles |

### Bus / Services Integration

| Service | Used by | Notes |
|---------|---------|-------|
| `bus_service` | `AiDebugApp` | WebSocket connection, channel subscription |
| `rpc` | Not used | No backend data fetching |
| `orm` | Not used | No DB models |

### Auth and Access

- Route: `auth='user'` — Odoo session required.
- Channel access: `ir.websocket` override restricts `ai_debug:*` channels to `group_system` (carried from v1.0).
- Any internal user can view the page; only system users receive bus events.

---

## Anti-Patterns

### Anti-Pattern 1: Using `prefers-color-scheme` CSS Media Query

**What people do:** Add `@media (prefers-color-scheme: dark) { ... }` in `app.scss` instead of a dark bundle.
**Why it's wrong:** Odoo's theme system is server-side bundle selection, not CSS media query. The user may have set Odoo to dark mode regardless of their OS preference. Using `prefers-color-scheme` would conflict with the user's Odoo preference.
**Do this instead:** Read the `color_scheme` cookie in the controller. Serve `assets_dark` when the cookie is `'dark'`. Use `var(--bs-*)` properties in SCSS — they resolve to the correct values for whichever bundle was loaded.

### Anti-Pattern 2: Storing Full Payload in pg_notify

**What people do:** Assume the bus payload flows through pg_notify directly and is size-limited.
**Why it's wrong:** The pg_notify size limit applies to the channel list, not the message content. Bus message data is stored in `bus_bus` rows as JSONB and fetched separately.
**Do this instead:** Send full payloads via `bus.bus._sendone()` without concern for pg_notify limits.

### Anti-Pattern 3: Including `web.assets_web` Instead of `web.assets_backend`

**What people do:** Build the dark bundle as `('include', 'web.assets_web')` to match the webclient pattern.
**Why it's wrong:** `web.assets_web` includes `web.assets_backend` plus `main.js` and `start.js` — those boot the full Odoo webclient and conflict with `mountComponent`.
**Do this instead:** Build `ai_debug.assets` with `('include', 'web.assets_backend')` as the base, then add the app-specific files. Match what `pos_self_order` does.

### Anti-Pattern 4: Duplicating JS in the Dark Bundle

**What people do:** Define `ai_debug.assets_dark` as a completely standalone bundle with all JS files repeated.
**Why it's wrong:** JS loads twice, bloating the page and causing `@odoo-module` double-registration errors.
**Do this instead:** Follow the webclient pattern exactly: load JS from the base bundle with `t-css="false"`, load CSS from the conditional bundle with `t-js="false"`.

### Anti-Pattern 5: Fetching Data On Selection

**What people do:** Store only IDs in state and fetch full data when the user clicks a node.
**Why it's wrong:** There is no DB to fetch from. All data must be in the bus payload, in memory, at selection time.
**Do this instead:** Store complete data in the state Map at event receipt time. Selection is purely a pointer into already-held state.

---

## Sources

**v1.3 persistence sources (HIGH confidence — direct source reads):**

- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — existing reactive store, all bus handlers, `onMounted` lifecycle (verified)
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` — existing template structure (verified)
- `/Users/joseph/clones/odoo/custom/.planning/PROJECT.md` — v1.3 requirements list
- MDN Web Docs — IndexedDB structured clone algorithm, IDB API (openDB, IDBObjectStore, IDBKeyRange)
- OWL 2.x source — `reactive()`, `useState()` proxy behavior, `onMounted` async support

**v1.2 theming sources (HIGH confidence — direct source reads):**

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/models/ir_http.py` — `color_scheme()` method: reads cookie, then user setting; never returns `'system'`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/controllers/home.py` — sets `color_scheme` cookie on every webclient response
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — base `color_scheme()` returns `"light"` hardcoded; `webclient_rendering_context()` adds it to QWeb context
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` — `web.webclient_bootstrap`: exact pattern of JS-only bundle + conditional CSS-only dark/light bundle
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — POS uses `pos_color_scheme` cookie with same conditional `t-call-assets` pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/__manifest__.py` — `web.assets_web_dark`: `('include', 'web.assets_web')` + `'web/static/src/**/*.dark.scss'`
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/__manifest__.py` — enterprise extends `web.assets_web_dark` with `web.dark_mode_variables`, dark SCSS helpers, and `**/*.dark.scss` files
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/bootstrap/scss/_root.scss` — Bootstrap emits `--bs-body-bg`, `--bs-body-color`, `--bs-border-color` etc. on `:root` from Sass variables compiled at build time
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/scss/primary_variables.dark.scss` — inverted gray scale: gray-100 is darkest (`#1B1D26`), gray-900 is lightest (`#E4E4E4`)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/web_enterprise/static/src/webclient/navbar/navbar.dark.scss` — pattern for component dark overrides: override local CSS custom properties, not global Bootstrap vars
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.scss` — existing 650-line SCSS with hardcoded Catppuccin Mocha colors (all to be replaced)

**v1.1 base sources (HIGH confidence — direct source reads):**

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/views/pos_self_order.index.xml` — template structure
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/controllers/self_entry.py` — controller pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/env.js` — `mountComponent`, `makeEnv`, `startServices`
- `/Users/joseph/clones/odoo/custom/ai_debug/` — actual v1.1 module source (all files)

---
*Architecture research for: Odoo AI debugger v1.3 — IndexedDB persistence integration*
*Researched: 2026-02-22*
