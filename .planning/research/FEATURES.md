# Feature Research

**Domain:** Local persistence, export/import, and trace management in a browser-based developer tool
**Researched:** 2026-02-22
**Confidence:** HIGH — IndexedDB API is stable and well-documented. UX patterns drawn from Chrome DevTools, Edge DevTools, Redux DevTools, and MDN official sources.

---

## Context: What This Milestone Adds

**v1.2 (shipped):** All data is session-scoped and ephemeral. Refreshing the page destroys all captured traces. The reactive store is a `useState(new Map())` in the OWL component tree. No persistence mechanism exists.

**v1.3 goal:** Traces survive page refresh via IndexedDB. Users can delete individual traces or clear all. Users can export traces as JSON and import them back.

The existing reactive store (`useState(new Map())`) remains the source of truth for the UI. IndexedDB is a write-through persistence layer that mirrors the in-memory store and provides the initial hydration payload on page load.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features a developer will assume exist in any tool that claims to "persist" data. Missing these makes the persistence feel broken or untrustworthy.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Traces survive page refresh** — IndexedDB hydrates the reactive store on page load | This is the definition of persistence. Without it the feature doesn't exist. | LOW | `openDB()` on startup, `getAll()` from the traces store, populate reactive Map. Write-through: every bus.bus event that adds a trace also calls `put()` into IndexedDB. |
| **Delete individual trace** — remove one loop trace from both store and IndexedDB | Users accumulate traces across sessions. Being able to discard a stale one is fundamental to managing the list. | LOW | A delete button in the sidebar per trace item. Calls `delete(traceId)` on the IDB store and removes from the reactive Map. No confirmation dialog needed for individual items — the action is low-stakes and reversible (the agent can be re-run). |
| **Clear all traces** — bulk wipe of every persisted trace | Essential counterpart to persistence. Without it, the list grows unbounded and there's no clean-slate mechanism. | LOW | A "Clear all" button in the toolbar. Calls IDB `clear()` on the traces store and resets the reactive Map. A confirmation prompt (browser `confirm()` or inline warning) is standard practice when the action is irreversible. |
| **New live traces still appear in real time** — persistence layer does not block bus.bus event delivery | The existing real-time behavior must not regress. If IDB writes are slow or fail, the UI should still update. | LOW | IDB writes are fire-and-forget (`await put()` but do not block UI update). Update reactive Map synchronously, write IDB asynchronously. |

### Differentiators (Valuable, Not Required)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Export selected traces as JSON file** — download one or more traces to disk | Developers can share a failing trace with a colleague, attach to a bug report, or archive for later analysis. Covers the multi-session and cross-machine sharing use cases that IndexedDB alone cannot. | LOW | `JSON.stringify(selectedTraces, null, 2)` + programmatic `<a download>` click. No server round-trip. Filename: `ai-traces-{timestamp}.json`. |
| **Import previously exported JSON file** — restore a JSON export back into the store and IndexedDB | Closes the sharing loop. A teammate can reproduce the exact trace context you captured. | LOW | `<input type="file" accept=".json">` with `FileReader.readAsText()`. Parse JSON, validate structure, insert into reactive Map and IDB. Merge semantics: imported traces are added alongside existing ones (not replace). |
| **Manual retention only — no auto-expiry** | For a developer tool, the developer decides when data is stale. Auto-expiry on a timer or size limit would delete traces the developer still needs. | NONE | This is explicitly not a feature. Do not implement TTLs, LRU eviction, or size-based pruning. Storage quota for dev tools usage is not a practical concern (Chrome: up to 60% of disk). |

### Anti-Features (Do Not Build)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Auto-expiry / TTL** — delete traces older than N days automatically | "I don't want IndexedDB to fill up." | Unexpectedly deletes traces the developer still needs. Storage quota is not a practical constraint for this use case (the average agentic trace is tens of KB; quota is GBs). Introduces complexity (timestamp indexing, background cleanup) for no real benefit. | Manual delete and "Clear all" are sufficient. Inform the user of storage used if needed via `navigator.storage.estimate()`. |
| **Server-side sync / backup** — push traces to an Odoo model or external service | "I want to access traces from another machine." | Adds database models, migrations, backend code, and auth complexity. The `ai_debug` module's explicit design decision was no database persistence. Cross-machine sharing is solved by export/import. | Export to JSON file, send the file. |
| **Search and filter within persisted traces** | "I have 50 traces and need to find the one that failed." | Out of scope per PROJECT.md — "bounded tree depth makes this low-priority." IndexedDB does support indexes, but building filter UI is a distinct milestone. | Covered by the visual sidebar tree already. Defer to v2+. |
| **Selective import — choose which traces to import from a file** | "I only want trace 3 out of this 10-trace export file." | Adds UI complexity (a picker modal) for a rare use case. Full file import is the 95% case. | Import the whole file. Users can delete individual unwanted traces after import. |
| **Streaming / chunked writes** — write traces to IDB incrementally as each bus.bus event arrives (event-level granularity) | "Write the partial trace so it persists even if the loop crashes mid-run." | Increases IDB schema complexity (separate stores for iterations and tool calls vs one store for complete traces). An in-flight trace with only half its iterations is useless for replay or analysis. The existing data model (loop = one top-level trace object) is the right persistence unit. | Persist the trace as a complete object whenever a `loop_end` event arrives. In the meantime keep it in memory only. This is the natural boundary. |
| **Compression of stored traces** — gzip or similar before putting into IDB | "RAG traces could be large." | IDB quota is not a practical concern. Compression/decompression adds complexity and CPU overhead for reads. The `idb` library does not support it natively. | If payload sizes become a problem (empirical baseline needed per PROJECT.md tech debt), address at that point. Export compression (gzip) could make sense for large exports, but is not needed for storage. |

---

## Feature Dependencies

```
[IndexedDB persistence layer]
    └──requires──> [idb library or raw IDB API]
    └──writes-from──> [bus.bus event handler] (write-through on loop_end)
    └──reads-into──> [reactive store hydration on page load]

[Delete individual trace]
    └──requires──> [IndexedDB persistence layer] (to delete from IDB)
    └──requires──> [Reactive store with trace IDs] (to remove from Map)
    └──uses-same-ID-as──> [UUIDs already on bus.bus payloads]

[Clear all traces]
    └──requires──> [IndexedDB persistence layer] (IDB clear())
    └──requires──> [Reactive store reset]
    └──should-have──> [Confirmation prompt] (irreversible, unlike single delete)

[Export as JSON]
    └──requires──> [Reactive store] (in-memory data is the source)
    └──no-dependency-on──> [IndexedDB] (can export from memory alone)
    └──enables──> [Import workflow] (export defines the import schema)

[Import from JSON]
    └──requires──> [Export schema definition] (import validates against the same structure)
    └──writes-to──> [IndexedDB persistence layer] (imported traces should survive next refresh)
    └──writes-to──> [Reactive store] (imported traces should appear in sidebar immediately)
    └──merge-not-replace──> [Existing traces] (import adds to, not replaces, current traces)

[Page load hydration]
    └──requires──> [IndexedDB persistence layer]
    └──must-complete-before──> [Sidebar renders] (or render empty then fill — stale-while-revalidate)
    └──uses-existing-format-from──> [bus.bus payload structure] (same objects stored in IDB)
```

### Dependency Notes

- **Write-through boundary is `loop_end`:** Traces should be written to IDB only when a loop finishes (the `loop_end` bus event arrives), not on every intermediate event. Partial in-flight traces are not useful. The in-memory store accumulates events during the loop; IDB gets the completed trace.
- **UUIDs are already on all bus.bus payloads (v1.1).** The `traceId` (loop UUID) is the natural IDB record key. No new ID generation is needed.
- **Import must validate structure before inserting.** Malformed JSON or traces from an incompatible version should fail gracefully with a user-visible error, not corrupt the store.
- **Export does not depend on IDB.** The reactive in-memory Map is the authoritative source. If IDB is unavailable (private browsing, quota exceeded), export still works.
- **IDB write failures must not block the UI.** Wrap all IDB writes in try/catch. If a write fails, the trace stays in memory and the developer is not interrupted. Log the error to the console.

---

## MVP Definition

### Launch With (v1.3)

The minimum that delivers the stated milestone goal: traces survive refresh, can be deleted, can be exported, can be imported.

- [ ] **IndexedDB store initialization** — `openDB('ai-debug', 1)` with a `traces` object store, key = `traceId`. Runs on app startup.
- [ ] **Page load hydration** — `getAll()` from IDB, populate reactive Map. Sidebar populates immediately.
- [ ] **Write-through on loop_end** — when a `loop_end` bus event arrives and the in-memory trace is finalized, `put()` the complete trace object into IDB.
- [ ] **Delete individual trace** — delete button per trace in sidebar, calls IDB `delete(traceId)`, removes from reactive Map.
- [ ] **Clear all** — toolbar button, calls IDB `clear()`, resets reactive Map. Preceded by a confirmation step (inline confirm button or `window.confirm`).
- [ ] **Export as JSON** — button to download all current traces as a `.json` file. Programmatic download via `<a download>` with `URL.createObjectURL(blob)`.
- [ ] **Import from JSON** — file picker (`<input type="file">`), read and parse JSON, validate structure, merge into reactive Map and IDB.

### Add After Validation (v1.3.x)

- [ ] **Export selected traces only** — if users accumulate many traces and want to share a subset. Trigger: user feedback that "export all" is too coarse.
- [ ] **Storage usage indicator** — `navigator.storage.estimate()` to show how much IDB space is used. Trigger: user reports uncertainty about storage impact.

### Future Consideration (v2+)

- [ ] **Search/filter within sidebar** — depends on trace volume making navigation painful. Explicitly deferred in PROJECT.md.
- [ ] **OpenTelemetry export (OTLP)** — listed as v2+ candidate `EXPT-01` in PROJECT.md.
- [ ] **Selective import picker** — low-priority edge case.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Page load hydration (traces survive refresh) | HIGH | LOW | P1 — core milestone goal |
| Write-through on loop_end | HIGH | LOW | P1 — required for hydration to have anything to read |
| IDB initialization | HIGH | LOW | P1 — prerequisite for everything else |
| Delete individual trace | HIGH | LOW | P1 — without delete, list is permanent and grows unbounded |
| Clear all traces | HIGH | LOW | P1 — essential clean-slate mechanism |
| Export as JSON | HIGH | LOW | P1 — enables sharing and cross-machine use |
| Import from JSON | HIGH | LOW | P1 — completes the sharing loop |
| Export selected traces only | MEDIUM | LOW | P2 — add when volume makes "all" too coarse |
| Storage usage indicator | LOW | LOW | P2 — nice to have, not blocking |
| Streaming/chunked IDB writes | LOW | HIGH | ANTI-FEATURE — wrong persistence unit |
| Server-side sync | LOW | HIGH | ANTI-FEATURE — against module design decisions |
| Auto-expiry/TTL | LOW | MEDIUM | ANTI-FEATURE — unexpected data loss |

---

## Implementation Guidance from Research

### Library Choice: `idb` by Jake Archibald

Use the `idb` library (~1.19kB brotli'd) rather than raw IndexedDB callbacks. It is the de-facto standard wrapper: promise-based, async/await compatible, and has zero runtime dependencies. It mirrors the IDB API closely so the cognitive overhead is minimal.

Key methods used:
- `openDB(name, version, { upgrade })` — initialize with schema
- `db.getAll(storeName)` — hydration on load
- `db.put(storeName, value)` — write-through on loop_end
- `db.delete(storeName, key)` — individual trace delete
- `db.clear(storeName)` — clear all
- `db.get(storeName, key)` — targeted reads if needed

### Schema Design

```
Database: 'ai-debug'
Version: 1
Object store: 'traces'
  keyPath: 'traceId'  (the UUID already on all bus.bus payloads)
  indexes: none required for MVP (getAll() + client-side Map is sufficient)
```

Avoid large nested objects per web.dev best practices. Each trace record is one complete loop object. This is acceptable because: (a) traces are read as a batch on hydration anyway, (b) the structured clone of one trace object is bounded and fast, (c) individual put() calls only update the one changed record, not a global state blob.

### Write-Through Pattern

```
bus.bus event (loop_end) arrives
  → update reactive Map (synchronous, triggers OWL re-render)
  → await idb.put('traces', completeTraceObject)  // async, non-blocking to UI
  → if put() fails: log error, keep trace in memory only
```

This is the standard write-through pattern for developer tools: UI is always responsive, persistence is best-effort.

### Export File Format

```json
{
  "version": "1.3",
  "exported": "2026-02-22T10:30:00Z",
  "traces": [ ...array of trace objects identical to IDB records... ]
}
```

The `version` field enables import validation — if an import file has an incompatible version, surface a clear error rather than silently corrupting the store. The trace objects in the array are identical to what is stored in IDB (same structure as bus.bus payloads), so no transformation is needed on import.

### Import Merge Semantics

Imported traces are added to the existing store, not replacing it. If an imported trace has the same `traceId` as an existing trace, the imported version wins (IDB `put()` semantics, which upsert by key). This handles the common case of re-importing the same export file idempotently.

### Confirmation for "Clear All"

A confirmation step is standard UX when an irreversible bulk action is taken. Options in order of preference:
1. **Inline confirmation** — clicking "Clear all" changes button label to "Confirm?" for 3 seconds, a second click executes. No modal required.
2. **`window.confirm()`** — simplest, native, acceptable for a developer tool.

Single trace delete does NOT need confirmation — the action is low-stakes (the agent can be re-run), and adding a confirmation to every row item creates friction for the common case.

---

## Sources

- [MDN: Using IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB) — schema design, transactions, versioning (HIGH confidence)
- [web.dev: IndexedDB Best Practices for App State](https://web.dev/articles/indexeddb-best-practices-app-state) — avoid large objects, granular writes, stale-while-revalidate pattern (HIGH confidence)
- [web.dev: Work with IndexedDB](https://web.dev/articles/indexeddb) — `idb` library usage patterns (HIGH confidence)
- [MDN: Storage Quotas and Eviction Criteria](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria) — Chrome: 60% disk, Firefox: 10% disk or 10GB (HIGH confidence)
- [GitHub: jakearchibald/idb](https://github.com/jakearchibald/idb) — API reference, size, method list (HIGH confidence)
- [Microsoft Edge DevTools: Share Performance Traces](https://learn.microsoft.com/en-us/microsoft-edge/devtools/performance/share-performance-traces) — export/import UX patterns for developer tools (HIGH confidence — official docs, updated Nov 2025)
- [LogRocket: Offline-first frontend apps 2025](https://blog.logrocket.com/offline-first-frontend-apps-2025-indexeddb-sqlite/) — write-through and sync queue patterns, pitfalls (MEDIUM confidence — editorial)
- [Chrome DevTools: New in DevTools 101](https://developer.chrome.com/blog/new-in-devtools-101) — Recorder panel export/import JSON as established DevTools pattern (HIGH confidence)
- PROJECT.md — existing module design decisions, explicit out-of-scope items, tech debt notes (HIGH confidence — source of truth for this codebase)

---

*Feature research for: Local persistence (IndexedDB), trace export/import, trace management in ai_debug v1.3*
*Researched: 2026-02-22*
