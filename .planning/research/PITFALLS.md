# Pitfalls Research

**Domain:** Adding IndexedDB persistence and export/import to an existing OWL standalone app with a reactive Map store
**Researched:** 2026-02-22
**Confidence:** HIGH (direct codebase inspection + official IndexedDB documentation + OWL source)

This document is scoped to v1.3: adding IndexedDB persistence, hydration on load, delete/clear, export, and import to the existing `ai_debug` OWL app. The v1.2 pitfalls (CSS/theming) are superseded. This document focuses on async/sync mismatches between IndexedDB and OWL rendering, write pressure from rapid bus events, large payload handling, schema design, and import validation.

---

## Critical Pitfalls

### Pitfall 1: Writing to IndexedDB Synchronously in Every Bus Event Handler Blocks the UI

**What goes wrong:**

Bus events arrive rapidly during an agentic loop — `new_trace`, `iteration`, `tool_call`, `loop_end` can fire in bursts with no natural throttle. If each handler calls `await db.put(...)` inline, two problems compound: (1) the handler is now async, which changes OWL's render scheduling, and (2) even though IndexedDB writes are nominally "asynchronous," the structured clone algorithm that serializes the object before storing it **runs on the main thread synchronously**. A trace object carrying a full conversation history (all prior messages per iteration) can take 2–10ms per clone operation. At 5–10 events per second, this adds up to janky scroll and missed renders during active loop execution.

**Why it happens:**

The natural reflex when adding persistence is to add the write at the end of the existing handler: "the event arrives, update the Map, then persist it." This feels safe because the write is awaited. But it means every render cycle now includes a main-thread clone operation plus an async IDB transaction overhead, all firing at bus frequency.

**How to avoid:**

Decouple persistence from the bus handlers entirely. The bus handlers write to the reactive Map (existing behavior — stays sync). A separate persistence layer observes completions and writes to IndexedDB on its own cadence:

- Use a pending-write queue: bus handlers push the trace ID to a Set of "dirty" traces. A `setTimeout(flush, 0)` or microtask debounce drains the queue by writing only changed traces.
- Write at natural checkpoint events, not on every sub-event: persist the full trace record on `loop_end`, and persist in-progress trace state at a throttled interval (e.g., every 2s) for crash recovery only.
- Per-record storage: store each trace as one IDB record (keyed by `trace_id`). On update, overwrite the full trace record. This is one `put()` call per trace per flush cycle, not one per bus event.

The transaction cost for inserting 1k records one-at-a-time is ~2s vs ~80ms batched. For traces this is not the bottleneck, but the structured clone per write is. Keep individual records small by accepting a full-trace-per-record model rather than a per-event-append model.

**Warning signs:**

- UI stutters or scroll jank during fast agentic loops (multi-tool iterations)
- DevTools Performance timeline shows main thread busy with `IDBRequest` during bus event callbacks
- Bus event handlers become `async` functions — check that OWL doesn't misinterpret the returned Promise as a component lifecycle concern

**Phase to address:** Phase 1 (IndexedDB layer design) — decide the write strategy before writing a line of IDB code

---

### Pitfall 2: IndexedDB Transaction Auto-Commits If an `await` Spans a Microtask Boundary Mid-Transaction

**What goes wrong:**

An IndexedDB transaction auto-commits once there are no pending IDB requests within the transaction scope. If you open a transaction, then `await` something that is NOT an IDB request (e.g., a `Promise.resolve()`, a `fetch()`, a `setTimeout`, or even an OWL render tick), the transaction commits before you make additional requests against it. You get a `TransactionInactiveError` on the second request. This is especially acute in Safari, which closes transactions more aggressively than Chrome.

Example of the trap:
```javascript
const tx = db.transaction('traces', 'readwrite');
const store = tx.objectStore('traces');
await store.put(traceData);       // OK — this IS an IDB request
const extra = await someHelper(); // NOT an IDB request — transaction may auto-commit here
await store.put(moreData);        // TransactionInactiveError in Safari
```

**Why it happens:**

The spec intends transactions to be short-lived. The auto-commit behavior is by design. Developers familiar with SQL transactions assume "open transaction, do work, commit" — but IDB commits eagerly, not at explicit `.commit()`. When using `async/await` with IDB, it's easy to accidentally yield the microtask queue to non-IDB work inside a transaction scope.

**How to avoid:**

Keep all IDB requests within a transaction contiguous — no awaiting non-IDB Promises between requests in the same transaction:

```javascript
// CORRECT: prepare data first, then open transaction and do all IDB work
const cloned = structuredClone(traceData); // prepare outside transaction
const tx = db.transaction('traces', 'readwrite');
const store = tx.objectStore('traces');
store.put(cloned);
await tx.done; // idb library helper — waits for transaction to complete
```

Use the `idb` library (Jake Archibald) which wraps IDB in Promises with correct transaction semantics and a `tx.done` promise that resolves on commit. This eliminates most transaction-close timing bugs. Alternatively, use Dexie which fully abstracts transaction management.

For the `ai_debug` use case: since writes are one `put()` per trace per flush, this pitfall only appears if the flush function tries to write multiple stores or performs non-IDB async work between requests. Keep flush functions to: get store reference, `store.put()`, `await tx.done` — nothing else in between.

**Warning signs:**

- `TransactionInactiveError` exceptions in the console during writes, especially in Safari
- Writes succeed in Chrome but silently fail (or throw) in Firefox/Safari
- Any non-IDB `await` expression between two `store.put()` or `store.get()` calls in the same function

**Phase to address:** Phase 1 (IDB wrapper implementation) — use `idb` library to eliminate this class of bugs

---

### Pitfall 3: Hydrating the Reactive Map Before OWL Mounts Causes a Render Before State Is Ready

**What goes wrong:**

The most natural place to hydrate `this.traces` from IndexedDB is in `onMounted`. But `onMounted` runs AFTER the first render. If the component renders with an empty Map, shows "No traces" state, then hydrates from IDB and triggers a second render, the user sees a flash of empty state on every page load — even when traces are already persisted.

Worse: if hydration is awaited inside `onMounted` and the IDB read returns a large dataset, the component has already rendered the empty state and now must patch the full tree of traces into the DOM in a single large render. This causes perceptible jank on load.

**Why it happens:**

OWL's `onMounted` is the familiar DOM-ready hook from React/Vue. Developers reach for it to do "initialization after render." But OWL also provides `onWillStart`, which runs asynchronously BEFORE the first render, blocking it until the hook resolves. `onWillStart` is the correct place for data loading that should be present for initial render.

**How to avoid:**

Use `onWillStart` for IDB hydration:

```javascript
setup() {
    this.traces = useState(new Map());
    this.state = useState({ hydrating: true, ... });

    onWillStart(async () => {
        const stored = await loadTracesFromIDB();
        for (const trace of stored) {
            // Reconstruct nested reactive Maps — IDB stores plain objects
            const iterations = reactive(new Map());
            for (const iter of trace.iterations) {
                const toolCalls = reactive(new Map());
                for (const tc of iter.toolCalls) {
                    toolCalls.set(tc.tool_call_id, tc);
                }
                iterations.set(iter.iteration_id, { ...iter, toolCalls });
            }
            this.traces.set(trace.trace_id, { ...trace, iterations });
        }
        this.state.hydrating = false;
    });
}
```

Keep the `onWillStart` read fast — IDB bulk reads of the trace index are fast; the bottleneck is deserializing large payloads. If there are many traces, consider loading only metadata (trace_id, agent_name, status, started_at) during `onWillStart` and lazy-loading full payloads on selection.

**Warning signs:**

- Hydration logic in `onMounted` (not `onWillStart`)
- A visible flash of "No traces" on page load even when IDB has data
- Console logs showing trace data being set after the initial render completes

**Phase to address:** Phase 2 (Hydration implementation) — use `onWillStart` from the start, not as a fix

---

### Pitfall 4: IDB Stores Plain Objects — Nested `reactive()` Maps Are Lost on Roundtrip

**What goes wrong:**

The current store uses a nested structure of reactive Maps: `this.traces` is `useState(new Map())`, each trace contains `iterations: reactive(new Map())`, each iteration contains `toolCalls: reactive(new Map())`. IndexedDB uses the structured clone algorithm to serialize objects for storage. Structured clone **cannot** clone Proxy objects (which is what `reactive()` returns). It strips proxy wrappers and stores the underlying plain object — and a Map is stored as a Map, but NOT as a reactive Map.

When data is read back from IDB on hydration, the returned objects are plain — no reactivity. If you do `this.traces.set(traceId, storedTrace)` where `storedTrace.iterations` is a plain `Map`, OWL will not observe mutations on `storedTrace.iterations`. Adding an iteration from a live bus event after hydration will not trigger a re-render unless the iterations Map is wrapped in `reactive()` again.

**Why it happens:**

Developers test persistence with a fresh trace (write then read), see the UI populate correctly, and conclude it works. The bug only manifests when a bus event arrives AFTER hydration for an in-progress trace that was loaded from IDB — the new iteration appears in the Map but the UI doesn't update.

**How to avoid:**

Deserialize IDB data by explicitly wrapping nested structures in `reactive()` during hydration. Treat IDB as a serialization format, not a live store:

```javascript
// Hydration: always reconstruct reactivity from plain IDB data
function hydrateTrace(rawTrace) {
    const toolCallsMaps = new Map(
        rawTrace.iterations.map(iter => [
            iter.iteration_id,
            {
                ...iter,
                toolCalls: reactive(new Map(
                    iter.toolCalls.map(tc => [tc.tool_call_id, tc])
                )),
            }
        ])
    );
    return {
        ...rawTrace,
        iterations: reactive(toolCallsMaps),
    };
}
```

Also: store traces in IDB as plain serializable objects — use `Array.from(trace.iterations.values())` when serializing, not the Map itself (Map serializes and deserializes correctly via structured clone, but the nested reactive wrapping is what needs reconstruction). Consider storing iterations and toolCalls as arrays in IDB (more portable, simpler to reconstruct).

**Warning signs:**

- UI shows stale iteration count after page refresh + new bus events arrive for an in-progress trace
- Clicking a trace loaded from IDB shows correct detail data but live events don't append to the sidebar
- Console shows `trace.iterations.set(...)` being called but no render cycle fires

**Phase to address:** Phase 2 (Hydration implementation) — add reactivity reconstruction as a design constraint from the start

---

### Pitfall 5: `Date` Objects in Stored Traces Become Strings After IDB Roundtrip If JSON Is Used

**What goes wrong:**

The current trace objects contain `started_at: new Date()`, `ended_at: new Date()`, and `receivedAt: new Date()` (per iteration). IndexedDB's structured clone algorithm CAN store `Date` objects natively — they are round-tripped as `Date` instances. However, if at any point the data is passed through `JSON.stringify` / `JSON.parse` (e.g., during export, or if using `JSON.stringify` as a serialization shortcut for IDB), the `Date` objects become ISO string strings. After that, `trace.ended_at - trace.started_at` (used in `getIterationDuration`) returns `NaN` because string subtraction doesn't work.

**Why it happens:**

Export/import necessarily involves `JSON.stringify` / `JSON.parse`. If the same data model is used for both IDB storage and JSON export without explicit Date handling, and if import restores data directly from parsed JSON into the IDB (bypassing reconstruction), all Dates become strings. The symptom is that duration calculations show `NaN` or `NaN ms` in the UI, only for imported traces.

Additionally: the code uses `new Date()` at event-receipt time for `receivedAt` and `started_at`. On hydration from IDB, if Dates are correctly stored as Date objects, the subtraction in `getIterationDuration` will work. But after a JSON import roundtrip, it will not unless Dates are explicitly reconstructed.

**How to avoid:**

Establish a consistent serialization contract:

1. **IDB storage**: Let structured clone handle `Date` objects natively. Never pre-serialize with `JSON.stringify` before storing in IDB.
2. **JSON export**: Convert `Date` objects to ISO strings explicitly (`date.toISOString()`). Document this in the export schema.
3. **JSON import**: Explicitly reconstruct `Date` objects from ISO strings after `JSON.parse`:

```javascript
function deserializeTrace(raw) {
    return {
        ...raw,
        started_at: raw.started_at ? new Date(raw.started_at) : null,
        ended_at: raw.ended_at ? new Date(raw.ended_at) : null,
        iterations: raw.iterations.map(iter => ({
            ...iter,
            receivedAt: new Date(iter.receivedAt),
        })),
    };
}
```

**Warning signs:**

- `getIterationDuration()` returns `'NaNms'` or `'NaN ms'` for imported traces
- `trace.started_at instanceof Date` returns `false` after import
- `typeof trace.started_at === 'string'` returns `true` after import

**Phase to address:** Phase 3 (Export/import) — define the export schema with explicit Date serialization before writing import logic

---

### Pitfall 6: Large JSON Export Payloads Block the Main Thread During `JSON.stringify`

**What goes wrong:**

A trace with a RAG-enabled session carries full conversation history per iteration. An agentic loop with 10 iterations, each with 20-message history plus tool args/results, can easily produce a 1–5MB JSON payload per trace. `JSON.stringify` of a 5MB object is synchronous and runs entirely on the main thread. At 10MB+ (multiple traces exported together), the browser tab freezes for 100–500ms during stringify — the user sees a hang, a spinner that doesn't move, or in worst cases a "Page Unresponsive" dialog.

**Why it happens:**

Export is triggered once by a user action ("Export selected traces") and feels low-frequency, so developers reach for the simple `JSON.stringify(allSelectedTraces)` approach. Traces are held in memory anyway, so it "should be fast." But structured data with deeply nested Maps serialized via `.values()` and spread operators can produce very large intermediate object graphs, and stringify on large objects is not incremental.

**How to avoid:**

- Export one trace at a time via `JSON.stringify` per trace to avoid one giant blocking call. Generate one export file per trace, or concatenate via Blob:

```javascript
// Stream-style export: build Blob from per-trace chunks
const chunks = [];
for (const trace of selectedTraces) {
    chunks.push(JSON.stringify(serializeTrace(trace)));
    chunks.push('\n'); // newline-delimited JSON (NDJSON)
}
const blob = new Blob(chunks, { type: 'application/json' });
```

- For multi-trace export as a single JSON array, use chunked stringify with `setTimeout` yield between traces to avoid blocking. For a developer tool with typically 1–20 traces of moderate size, this is overkill — but plan the export format to support it.
- Set a practical soft limit: warn the user if exporting more than N traces or the estimated payload exceeds a threshold (e.g., 10MB). This tool is for developer use; it's fine to communicate payload size.
- Measure actual payload size with a real RAG-enabled session before deciding whether chunking is needed. The PROJECT.md notes this as known tech debt.

**Warning signs:**

- The "Export" button appears to hang for >200ms before the download starts
- DevTools flame chart shows a long `JSON.stringify` block on the main thread during export
- The app becomes briefly non-interactive during export on large trace sets

**Phase to address:** Phase 3 (Export implementation) — measure payload size with a real session before deciding on chunking strategy

---

### Pitfall 7: JSON Import With No Schema Validation Causes Runtime Errors Deep in the Component Tree

**What goes wrong:**

A user imports a JSON file that was manually edited, came from a different version of the app, or is simply malformed. The import reads the file, parses JSON, and sets the restored traces into `this.traces`. The component then tries to render the trace — accessing `trace.iterations.values()`, `iter.toolCalls.get(...)`, etc. If the imported data has a different shape (e.g., `iterations` is an array instead of a Map, `trace_id` is missing, `status` is not one of the expected enum values), the component throws a rendering exception deep in a child component. The error surface is cryptic: a blank detail panel, or an OWL render error with a stack trace pointing into template code.

**Why it happens:**

Import validation is easy to defer — "we'll add it later, for now just parse and load." The happy path works perfectly. The failure modes only appear with edge-case files (manual edits, version mismatches, corrupt downloads, truncated exports).

**How to avoid:**

Validate import data before inserting it into the store. At minimum:

1. Confirm the top-level structure (`Array.isArray(data)` or expected schema key exists)
2. Validate each trace has required fields: `trace_id`, `agent_name`, `status`, `started_at`, `iterations`
3. Validate each iteration has: `iteration_id`, `trace_id`, `toolCalls`
4. Reject (with user-facing error message) rather than silently skip invalid records

A full JSON Schema validation (e.g., with `ajv`) is not necessary for a developer tool. A simple shape-check function is sufficient:

```javascript
function validateImport(data) {
    if (!Array.isArray(data)) throw new Error('Expected array of traces');
    for (const trace of data) {
        if (!trace.trace_id || !trace.agent_name) {
            throw new Error(`Invalid trace: missing required fields`);
        }
        if (!Array.isArray(trace.iterations)) {
            throw new Error(`Trace ${trace.trace_id}: iterations must be array`);
        }
    }
    return true;
}
```

Also guard against import of duplicate `trace_id` values — if the same trace_id already exists in the store (from IDB or from the current session), decide the policy (skip, overwrite, or error) before writing the import code.

**Warning signs:**

- Import logic does `this.traces.set(...)` without any shape validation
- OWL rendering errors appear after import with stack traces in template code
- Blank detail panel after selecting an imported trace (iteration or toolCall is undefined)

**Phase to address:** Phase 3 (Import implementation) — validation is part of the import, not an afterthought

---

### Pitfall 8: `clearAll()` Clears the Reactive Map But Not IDB — Deleted Data Reappears on Refresh

**What goes wrong:**

The existing `clearAll()` method calls `this.traces.clear()` and resets selection state. This clears the in-memory store. But on the next page load, `onWillStart` hydrates from IDB — which still has all the traces. The user clears all traces, sees an empty sidebar, then reloads the page and finds all the traces are back. This is maximally surprising behavior.

The same issue applies to `deleteTrace(traceId)`: deleting from the reactive Map is immediately visible in the UI, but if IDB is not updated synchronously with the UI action, a reload restores the deleted trace.

**Why it happens:**

The reactive Map clear is instant and visible; the IDB delete is async and deferred. Developers test the clear behavior without testing the reload case. The reflex is to add persistence but not to update the deletion operations to be persistence-aware.

**How to avoid:**

Delete operations must be dual: delete from both the reactive Map AND from IDB, atomically from the user's perspective. Because both are fast, the simplest approach is to await the IDB delete before showing the empty UI — but this is only acceptable if the IDB delete is fast (it is, for record-level deletes).

```javascript
async deleteTrace(traceId) {
    // Remove from reactive store immediately (UI updates)
    this.traces.delete(traceId);
    // Clear selection if the deleted trace was selected
    if (this.state.selectedId === traceId || this._isDescendantOf(traceId)) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    // Persist the deletion
    await idbDeleteTrace(traceId);
}

async clearAll() {
    this.traces.clear();
    this.state.selectedId = null;
    this.state.selectedType = null;
    await idbClearAll();
}
```

Do not defer IDB deletes to a "flush" cycle — deletions must be immediate and unconditional.

**Warning signs:**

- `clearAll()` or `deleteTrace()` do not have `async` in their signature (or do not call an IDB delete)
- After clearing and reloading the page, traces reappear in the sidebar
- The pending-write queue has no mechanism for deletions — it only batches puts

**Phase to address:** Phase 1 (IDB layer design) — deletion semantics must be part of the initial IDB layer design, not added later

---

### Pitfall 9: IDB Version Mismatch After Schema Change — Existing Data Becomes Inaccessible

**What goes wrong:**

The IndexedDB database is opened with a version number. If the code changes the schema (adds an object store, changes an index, adds a field that the IDB `keyPath` depends on) and bumps the version, the `onupgradeneeded` event fires and migrations can run. But if the code changes in a way that assumes a new schema field is present (e.g., `trace.schema_version`) without migrating existing records, IDB successfully opens (the store structure didn't change) but the JS code that reads old records crashes because the expected field is absent.

More critically: if an object store needs to be deleted and recreated (e.g., to change the `keyPath`), the only safe approach is to delete the old store in `onupgradeneeded` — which destroys all existing data in that store.

**Why it happens:**

During development of v1.3, the schema evolves. An early implementation might store traces differently than the final design. If the schema is changed without incrementing the version number (or without writing migration code), stale IDB data in the developer's own browser causes confusing bugs — traces that should have been deleted, missing fields, or data that doesn't match the current code expectations.

**How to avoid:**

- Start with DB version `1`. Define the schema carefully before writing any storage code.
- Never change the schema without incrementing the version number.
- Write explicit migration logic for each version increment in `onupgradeneeded`.
- For development: if the schema is still being finalized, provide a "nuke and restart" escape hatch in the `onupgradeneeded` handler (delete all stores on version mismatch during development). Document this as dev-only behavior.
- Store a `schemaVersion` field on each trace record (application-level versioning, separate from IDB's DB version). Check this on hydration and skip/migrate records from older schema versions.

**Warning signs:**

- Console shows `DOMException: The database connection is closing` or similar on page reload after a code change
- Hydration silently loads zero traces even though the IDB has data (field name mismatch causes a filter to exclude all records)
- `onupgradeneeded` handler is missing or empty (version is hardcoded without upgrade logic)

**Phase to address:** Phase 1 (IDB layer design) — define the schema and version strategy before writing any IDB code

---

### Pitfall 10: IDB Is Unavailable in Firefox Private Browsing (Older Versions) — App Must Not Crash

**What goes wrong:**

In Firefox versions before 115, IndexedDB throws a hard error in Private Browsing mode: `"A mutation operation was attempted on a database that did not allow mutations"`. The `ai_debug` app is a developer tool used in normal browser sessions, so this is unlikely — but if a developer opens `/ai-debug` in a private window for any reason (e.g., to test with a clean session), the app crashes at the IDB initialization point and becomes completely unusable, even though the core functionality (live bus streaming) works fine without persistence.

**Why it happens:**

IDB initialization is done in `onWillStart`, which throws if IDB fails. An unhandled Promise rejection in `onWillStart` propagates as an OWL mount error and the entire component fails to render.

**How to avoid:**

Wrap IDB initialization in a try/catch. Treat persistence as optional — if IDB is unavailable, fall back to in-memory-only behavior (the v1.1 baseline):

```javascript
onWillStart(async () => {
    try {
        this.db = await openTraceDB();
        const stored = await loadTracesFromDB(this.db);
        // ... hydrate store ...
    } catch (e) {
        console.warn('[ai_debug] IndexedDB unavailable, persistence disabled:', e);
        this.db = null; // persistence disabled flag
    }
});
```

All subsequent IDB calls (put, delete, clear) should check `if (!this.db) return;` before attempting to write. The app then degrades gracefully to ephemeral mode.

**Warning signs:**

- `openDB()` or IDB initialization has no try/catch
- A failed IDB open causes an unhandled Promise rejection that prevents `onWillStart` from completing
- The app shows a blank white page in Firefox private browsing instead of the expected UI

**Phase to address:** Phase 1 (IDB layer design) — error handling is part of the initial wrapper, not an afterthought

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Write to IDB on every bus event (no batching) | Simple code, immediate persistence | Main thread jank during fast agentic loops; structured clone overhead per event | Never — batch writes are required |
| Store the entire reactive Map as one IDB record | Simple serialization | Grows unbounded; structured clone on write blocks main thread for large traces | Never — per-trace records |
| Skip `onWillStart` in favor of `onMounted` for hydration | Familiar hook | Flash of empty state on every page load | Never — `onWillStart` is the correct hook |
| No IDB availability check / try-catch on open | Less boilerplate | Hard crash in private browsing or quota-exceeded scenarios | Never — always wrap IDB init |
| Import restores data without Date reconstruction | Simpler import code | `getIterationDuration` returns `NaN` for imported traces | Never — Date reconstruction is required |
| Skip import schema validation | Faster to ship | Runtime errors in render tree for malformed imports | Only in a prototype that will never see real files |
| Use same DB version for schema changes | Avoids migration code | Old data silently breaks on field name changes | Never — always bump version on schema change |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| IDB + OWL reactive Map | Await IDB reads/writes inside bus event handlers | Bus handlers stay sync; a separate flush layer handles IDB writes |
| IDB + `reactive()` Maps | Hydrate from IDB with plain Maps and assume reactivity | Explicitly wrap nested Maps in `reactive()` during deserialization |
| IDB + Date objects | Use `JSON.stringify` to store, lose Date type | Use structured clone (native IDB) for storage; explicit `new Date()` for import |
| IDB + `onMounted` | Load stored data in `onMounted` | Load stored data in `onWillStart` to block initial render until hydrated |
| IDB transactions + non-IDB `await` | `await fetch(...)` or `await someHelper()` inside a transaction scope | Prepare all data before opening the transaction; only IDB requests inside it |
| Export + large payloads | `JSON.stringify(allTraces)` synchronously | Stringify per-trace in a loop; measure actual payload size with real sessions |
| Import + duplicate IDs | Silently overwrite existing traces | Check for ID collision and apply a defined policy (skip, overwrite, or error) |
| Delete + IDB | Delete from reactive Map only | Always pair reactive Map delete with IDB record delete |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Structured clone on large objects (main thread) | UI jank/freeze during or after bus events | Per-trace IDB records; batch writes; measure with real RAG sessions | When a single trace exceeds ~1MB of serialized data |
| Unbatched IDB writes (one transaction per event) | Multiple `IDBRequest` items per second in DevTools; degraded animation | Coalesce writes — dirty-Set + debounced flush | During fast multi-iteration agentic loops |
| Synchronous `JSON.stringify` of all traces on export | Tab freeze for >200ms during export | Per-trace stringify; Blob concatenation; soft payload size limit | Multi-trace export with RAG traces >2MB each |
| Full trace hydration on load (no lazy load) | Slow page load when IDB has many large traces | Load metadata only on `onWillStart`; lazy-load full payloads on selection | When IDB accumulates >10 large RAG traces |
| No IDB index on `trace_id` | Slow lookups when many records exist | Define `trace_id` as the keyPath (or create an index) | After accumulating >100 traces (not likely for this tool) |

---

## "Looks Done But Isn't" Checklist

- [ ] **Persistence survives refresh:** Add a trace, reload the page, verify the trace appears in the sidebar (tests IDB write + hydration)
- [ ] **Delete is durable:** Delete a trace, reload the page, verify the trace does NOT reappear (tests IDB delete, not just reactive Map delete)
- [ ] **Clear all is durable:** Clear all traces, reload the page, sidebar is empty (tests IDB clearAll)
- [ ] **Live events post-hydration work:** Load the page with stored traces, then trigger a new agentic loop; verify the new trace appears AND its iterations/tool calls append in real time (tests reactive Map reconstruction after hydration)
- [ ] **Iteration durations are correct after hydration:** Reload with stored traces, select an iteration, verify duration displays correctly (tests Date roundtrip — not `NaN ms`)
- [ ] **Iteration durations are correct after import:** Import a previously exported file, select an iteration, verify duration displays correctly (tests Date deserialization in import path)
- [ ] **Import rejects malformed files:** Import a JSON file with missing `trace_id` field; verify a user-facing error appears rather than a crash
- [ ] **Import rejects non-JSON files:** Import a `.txt` file; verify a user-facing error rather than a JSON parse exception propagating to the UI
- [ ] **Export produces valid JSON:** Export a trace, open the file in a text editor, confirm it parses as valid JSON
- [ ] **Export + import roundtrip:** Export a trace, import the exported file, verify the trace renders identically to the original
- [ ] **IDB unavailable degrades gracefully:** Open the app in Firefox private browsing; the sidebar loads (possibly empty), bus events still appear, no blank page or uncaught exception
- [ ] **No write jank during fast loop:** Run a multi-tool agentic loop while monitoring DevTools Performance; no main thread blocking frames >50ms attributable to IDB writes

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| IDB writes in bus handlers (jank) | MEDIUM | Extract persistence to a separate flush module; audit all bus handlers to ensure they are synchronous |
| Transaction auto-close bug | LOW | Switch to `idb` library wrapper; `tx.done` pattern eliminates this class |
| Hydration in `onMounted` (flash) | LOW | Move hydration to `onWillStart`; add `hydrating` state and loading indicator |
| Reactivity not reconstructed | MEDIUM | Add `hydrateTrace()` deserialization function that wraps nested Maps in `reactive()`; test with post-hydration live events |
| Date strings instead of Date objects | LOW | Add explicit `new Date()` reconstruction in both hydration and import deserialization |
| Large export blocks main thread | LOW | Wrap stringify in per-trace loop with Blob concatenation |
| Import crashes on malformed data | LOW | Add shape validation before inserting imported data into store |
| Delete not durable | LOW | Add IDB delete call paired with every reactive Map delete |
| Schema mismatch on version bump | HIGH | Increment IDB version; write `onupgradeneeded` migration; or nuke and recreate (data loss) |
| IDB crash in private browsing | LOW | Wrap IDB open in try/catch; set `this.db = null` on failure; guard all IDB calls |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Writes block UI (no batching) | Phase 1: IDB layer design | DevTools Performance shows no IDB-related jank during fast loops |
| Transaction auto-close | Phase 1: IDB wrapper | Use `idb` library; zero `TransactionInactiveError` in console |
| Hydration in wrong hook | Phase 2: Hydration | No flash of empty state on page load with stored traces |
| Reactivity not reconstructed | Phase 2: Hydration | Live bus events update the sidebar for traces loaded from IDB |
| Date type loss | Phase 2 + Phase 3 | Duration displays correctly for both hydrated and imported traces |
| Large export blocking | Phase 3: Export | Export of 5+ traces completes in <100ms measured in DevTools |
| Import without validation | Phase 3: Import | Malformed file produces user error, not a render exception |
| Delete not durable | Phase 1: IDB layer design | Delete + reload shows empty sidebar |
| Schema version mismatch | Phase 1: IDB layer design | `onupgradeneeded` handler present and versioned from the start |
| IDB unavailable crash | Phase 1: IDB layer design | App loads in Firefox private browsing without blank page |

---

## Sources

- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — current bus event handlers, `useState(new Map())` reactive store, `onMounted` bus subscription, existing `clearAll()` method
- OWL lifecycle documentation: `onWillStart` is the correct async-before-render hook; `onMounted` runs post-render; modifying state in `onMounted` causes a second render — [github.com/odoo/owl/blob/master/doc/reference/component.md](https://github.com/odoo/owl/blob/master/doc/reference/component.md)
- IndexedDB transaction auto-commit: transactions auto-close when no pending IDB requests exist after microtasks flush; no non-IDB `await` inside a transaction scope — [MDN IDBTransaction](https://developer.mozilla.org/en-US/docs/Web/API/IDBTransaction), [javascript.info/indexeddb](https://javascript.info/indexeddb)
- IndexedDB structured clone blocks main thread: "the structured cloning process happens on the main thread. The larger the object, the longer the blocking time will be" — [web.dev/articles/indexeddb-best-practices-app-state](https://web.dev/articles/indexeddb-best-practices-app-state)
- Write batching performance: 1k records one-at-a-time ~2s vs. batched ~80ms — [nolanlawson.com/2021/08/22/speeding-up-indexeddb-reads-and-writes](https://nolanlawson.com/2021/08/22/speeding-up-indexeddb-reads-and-writes/)
- Safari transaction auto-close bug: more aggressive than Chrome; `Promise.resolve().then()` can close transaction prematurely — [github.com/pesterhazy/4de96193af89a6dd5ce682ce2adff49a](https://gist.github.com/pesterhazy/4de96193af89a6dd5ce682ce2adff49a)
- Firefox private browsing IDB error: throws on open in older Firefox private mode; resolved in Firefox 115 — [bugzilla.mozilla.org/show_bug.cgi?id=781982](https://bugzilla.mozilla.org/show_bug.cgi?id=781982)
- IDB export with large data: streaming Blob construction avoids holding entire DB in RAM — [dexie.org/docs/ExportImport/dexie-export-import](https://dexie.org/docs/ExportImport/dexie-export-import)
- IDB schema migration: changing keyPath requires delete + recreate (data destructive); version must be incremented — [MDN Using IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB)
- PROJECT.md: "Payload size for RAG-enabled sessions unknown (needs empirical baseline)" — known tech debt, informs export payload risk

---
*Pitfalls research for: Odoo AI Debugger v1.3 — IndexedDB persistence and export/import*
*Researched: 2026-02-22*
