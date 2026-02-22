# Project Research Summary

**Project:** AI Debugger — IndexedDB Persistence, Export/Import, Trace Management (v1.3)
**Domain:** Browser-side persistence layer for an Odoo standalone OWL developer tool
**Researched:** 2026-02-22
**Confidence:** HIGH

## Executive Summary

The v1.3 milestone adds durable persistence to the `ai_debug` standalone OWL app, which previously lost all captured agentic loop traces on page refresh. The app already has a working reactive store (`useState(new Map())` with nested `reactive(new Map())` for iterations and tool calls) and a live bus subscription. The v1.3 work adds a write-through IndexedDB layer beneath this existing store, hydrates it on startup, and exposes delete/clear/export/import controls to the user. All required APIs — the Odoo `IndexedDB` class, `downloadFile`, `notification` service, `ConfirmationDialog`, and `FileReader` — exist in the current `web.assets_backend` bundle without adding any new dependencies.

The recommended approach is a write-through cache pattern: the reactive Map remains the single source of truth for the UI; every mutation also fires an async IDB write (fire-and-forget, non-blocking). On page load, `onWillStart` (not `onMounted`) hydrates the Map from IDB before the first render, ensuring traces appear immediately without a flash of empty state. The only new file needed is `db.js`, a plain ES module wrapping the Odoo `IndexedDB` class. The STACK.md research confirms that Odoo's own `@web/core/utils/indexed_db` wrapper handles schema versioning, mutex-serialized transactions, and quota errors — it is already used in production by `menu_service`, `localization_service`, `rpc_cache`, and `offline_service`. No external npm packages are required.

The primary risks are all async/sync boundary mistakes that are well-documented and entirely avoidable with the right patterns. The three most critical: (1) awaiting IDB writes inside bus event handlers causes main-thread jank during fast loops — use fire-and-forget; (2) hydrating in `onMounted` instead of `onWillStart` causes a flash of empty state — use `onWillStart`; and (3) failing to wrap hydrated Map data in `reactive()` breaks live-event reactivity for traces loaded from IDB — always reconstruct nested reactive Maps during deserialization. These are binary right/wrong design decisions that must be made correctly in Phase 1 and Phase 2 before any other code is written.

## Key Findings

### Recommended Stack

All persistence, download, notification, and confirmation functionality is available via Odoo-native imports already present in the `web.assets_backend` bundle. No new npm dependencies, Python packages, or Odoo module additions are required. The serialization strategy requires explicit `serializeTrace()` and `hydrateTrace()` helpers because OWL reactive proxies cannot be stored by IndexedDB's structured clone algorithm and nested reactive Maps must be reconstructed on hydration.

**Core technologies:**

- `IndexedDB` from `@web/core/utils/indexed_db` — structured local storage for trace data; handles schema versioning, quota errors (`IDBQuotaExceededError`), and mutex-serialized transactions; used in production by `menu_service`, `rpc_cache`, and `offline_service`; database name `"ai_debug_traces"`, version `1`, object store `"traces"`, key = `trace_id`
- `downloadFile` from `@web/core/network/download` — triggers browser file download from a `Blob`; handles cross-browser edge cases including Safari and object URL lifecycle; already in the bundle via `web.assets_backend`
- Native `FileReader` API — reads user-selected JSON file client-side via `readAsText(file)`; `FileInput` from OWL is explicitly wrong here (it uploads to server routes)
- `notification` service via `useService("notification")` — surfaces import errors and quota-exceeded failures; `notification.add(message, { type: "danger" })`
- `dialog` service + `ConfirmationDialog` from `@web/core/confirmation_dialog/confirmation_dialog` — confirmation modal before destructive clear-all operations
- `serializeTrace()` / `hydrateTrace()` helpers — convert between OWL reactive Maps and plain IDB-storable objects; `Date` objects serialized as ISO strings; `expanded` UI state reset to `false` on hydration; nested `reactive(new Map())` explicitly reconstructed on deserialization

**What not to use:** `localStorage` (5-10 MB limit; silent data loss on large RAG traces), the `idb` npm package (not in Odoo's asset pipeline; duplicates what `@web/core/utils/indexed_db` already provides), `FileInput` component (server-upload only), or any `await` on non-IDB Promises inside an IDB transaction scope (Safari auto-close risk).

### Expected Features

v1.3 delivers five table-stakes features and two differentiators. All are P1 priority. All are low implementation complexity. No anti-features should be built.

**Must have (table stakes):**
- IndexedDB store initialization and hydration on page load — this is the definition of persistence; without it the feature doesn't exist
- Write-through on every bus event — required for hydration to have anything to read on the next page load
- Delete individual trace — users accumulate traces across sessions; being able to discard stale ones is fundamental; no confirmation needed (low-stakes, reversible by re-running the agent)
- Clear all traces — essential clean-slate mechanism; must include a `ConfirmationDialog` step (irreversible)
- New live traces appear in real time without regression — persistence layer must not block bus event delivery

**Should have (differentiators):**
- Export all/selected traces as a JSON file — enables cross-machine sharing, bug report attachment, archival; format: `{ version: 1, exported_at, traces: [...] }`
- Import a previously exported JSON file — closes the sharing loop; merge semantics (additive, not replace); validate schema before inserting; user-facing error via `notification` on failure

**Defer (v2+):**
- Search/filter within the sidebar — explicitly deferred in PROJECT.md; bounded tree depth makes it low priority
- Export selected traces only — add when volume makes "export all" too coarse; trigger: user feedback
- OpenTelemetry/OTLP export — listed as v2+ candidate EXPT-01 in PROJECT.md
- Selective import picker — low-priority edge case; import all and delete unwanted is the sufficient solution

**Anti-features (do not build):**
- Auto-expiry/TTL — would delete traces the developer still needs; storage quota is not a practical constraint (Chrome: up to 60% of disk)
- Server-side sync — adds models, migrations, ORM overhead; the module's explicit design decision is no database persistence; export/import covers cross-machine sharing
- Per-event streaming writes with a normalized IDB schema — wrong persistence unit; a partial in-flight trace is useless; persist on `loop_end` or fire-and-forget on each event overwriting the full trace record

### Architecture Approach

The architecture is additive: a new `db.js` plain ES module wraps the Odoo `IndexedDB` class and exposes five async functions. The existing `app.js` is modified at six integration points. No new Odoo services, no backend model changes, no asset bundle changes are required. New files (`db.js`, optionally `toolbar.js` / `toolbar.xml`) are picked up automatically by the `**/*.js` and `**/*.xml` globs in `ai_debug.assets`. The IDB storage format is identical to the export JSON format — the same `serializeTrace()` function produces output for both.

**Major components:**

1. `db.js` (new) — plain ES module wrapping Odoo's `IndexedDB` class; owns all IDB schema and CRUD; not an OWL service; exports `openDB`, `loadAllTraces`, `saveTrace`, `deleteTrace`, `clearAllTraces`
2. `serializeTrace()` / `hydrateTrace()` helpers (new, in `app.js` or a shared util) — convert between OWL reactive Maps and plain IDB-storable objects; critical for correctness; `hydrateTrace()` must explicitly call `reactive(new Map())` for all nested Maps
3. `AiDebugApp.onWillStart` hydration block (modified) — reads all IDB records before bus subscription starts; ensures event handlers can always find parent traces in the Map
4. Bus event handlers: `_onNewTrace`, `_onIteration`, `_onToolCall`, `_onLoopEnd` (modified) — each calls `db.saveTrace(serializeTrace(...))` fire-and-forget after the existing Map mutation
5. `deleteTrace(id)` (new method) + modified `clearAll()` — symmetric dual delete from reactive Map and IDB; deletions must be immediate and unconditional, not deferred to a flush cycle
6. `exportTraces()` (new method) — reads from in-memory Map, serializes with `serializeTrace()`, creates Blob, calls `downloadFile`
7. `importTraces(file)` (new method) — `FileReader.readAsText()` → `JSON.parse` → validate shape → `hydrateTrace()` → `this.traces.set()` + `db.saveTrace()`; show `notification` on validation failure
8. `toolbar.js` / `toolbar.xml` (new, optional) — export/import/clear controls; handles hidden file input and programmatic click for the import file picker

**IDB schema:** Database `"ai_debug_traces"`, version `1`, single object store `"traces"`, keyPath = `"trace_id"`. One denormalized record per trace; iterations stored as plain arrays (not normalized stores). No secondary indexes needed. The Odoo `IndexedDB` class auto-deletes and re-creates the database on version change (`_checkVersion()` behavior) — acceptable for a dev tool.

**Build order:** `db.js` → `onWillStart` hydration → write-through in bus handlers → `deleteTrace` + `clearAll` → `exportTraces` → `importTraces`. Steps 5 (delete/clear) and 6-7 (export/import) are independent of each other after step 3.

### Critical Pitfalls

1. **Awaiting IDB writes inside bus event handlers** — bus events fire multiple times per second during active agentic loops; awaiting each write adds main-thread structured-clone overhead per event and causes UI jank. Prevention: fire-and-forget all IDB writes (`db.saveTrace(...).catch(console.error)` — no `await` in bus handlers). Bus handlers must remain synchronous.

2. **Hydrating in `onMounted` instead of `onWillStart`** — `onMounted` runs after the first render, causing a visible flash of empty state and a second render cycle. Prevention: all IDB hydration goes in `onWillStart`, which runs before the first render and blocks it until the hook resolves.

3. **Not reconstructing `reactive()` Maps during hydration** — IDB returns plain objects; OWL reactive proxy wrappers are stripped by structured clone. If hydrated traces have plain `Map` objects, live bus events that call `trace.iterations.set(...)` post-hydration will not trigger re-renders. Prevention: `hydrateTrace()` must explicitly call `reactive(new Map())` for every nested Map.

4. **Not pairing IDB deletes with reactive Map deletes** — `this.traces.delete(id)` removes the trace visually, but the trace returns on the next page load unless `db.deleteTrace(id)` is also called. Prevention: every delete operation (single trace and clear-all) must be dual: reactive Map + IDB. Deletions must be immediate, not deferred to a flush cycle.

5. **Missing import validation** — a malformed or version-mismatched JSON file inserts broken trace objects; rendering exceptions then appear deep in template code with cryptic stack traces. Prevention: validate required fields (`trace_id`, `agent_name`, `status`, `iterations` as array) before inserting; reject with `notification.add(err.message, { type: "danger" })` on failure.

## Implications for Roadmap

Based on the research, this milestone maps to three sequential implementation phases driven by hard dependency ordering. The phases are small, focused, and verifiable independently.

### Phase 1: IDB Layer and Write-Through

**Rationale:** The `db.js` module and the write-through pattern are prerequisites for everything else. Hydration has nothing to read unless writes exist first. Delete/clear has nothing to remove from IDB unless writes exist. Export/import has nothing to validate unless the schema is defined. All schema and error-handling decisions — version strategy, IDB availability fallback, fire-and-forget vs await — must be locked in here before any other code is written. Four of the ten identified pitfalls (1, 8, 9, 10) require decisions made at this layer; they cannot be patched later without refactoring the write strategy.

**Delivers:** Working `db.js` module with all five functions. Modified bus event handlers with fire-and-forget `db.saveTrace()`. IDB schema at version 1. `serializeTrace()` helper. IDB availability try/catch in place from the start (graceful degradation to ephemeral mode if IDB is unavailable in private browsing).

**Addresses:** IndexedDB initialization, write-through on bus events, schema version strategy, graceful IDB failure handling.

**Avoids:** Pitfall 1 (jank from awaiting writes in handlers), Pitfall 8 (delete not durable — deletion semantics part of layer design), Pitfall 9 (schema mismatch — version and upgrade strategy defined upfront), Pitfall 10 (IDB crash in private browsing — try/catch on open).

### Phase 2: Hydration and Delete/Clear

**Rationale:** Hydration depends on Phase 1 writes having persisted data to read. Delete/clear depends on Phase 1's `deleteTrace` and `clearAllTraces` functions existing. The `onWillStart` hook choice and `hydrateTrace()` reactive Map reconstruction are the most correctness-critical decisions in the entire milestone — they must be implemented correctly the first time. Verification of the full round-trip (write → reload → read → live events still work) is the acceptance criterion before proceeding to Phase 3.

**Delivers:** `onWillStart` hydration block in `app.js`. `hydrateTrace()` deserializer that reconstructs nested `reactive(new Map())` Maps and converts ISO strings back to `Date` objects. Modified `clearAll()` that also calls `db.clearAllTraces()`. New `deleteTrace(id)` method that removes from both reactive Map and IDB. Delete button per trace in `app.xml`. Updated `clearAll` button with `ConfirmationDialog`.

**Addresses:** Page load hydration (traces survive refresh), delete individual trace, clear all traces, new live traces still appear in real time post-hydration.

**Avoids:** Pitfall 3 (hydration flash — use `onWillStart`), Pitfall 4 (reactivity not reconstructed — explicit `reactive(new Map())` in `hydrateTrace()`), Pitfall 5 (Date type loss on hydration — explicit `new Date()` reconstruction), Pitfall 8 (delete not durable — must pass the reload test as part of phase verification).

### Phase 3: Export and Import

**Rationale:** Export reads from the in-memory Map and does not depend on Phase 2 for its read path — but it depends on Phase 1's `serializeTrace()` for the export format, since the export format is identical to the IDB storage format. Import depends on Phase 2's `hydrateTrace()` and `db.saveTrace()`. Implementing export first provides a real export file to test import against, which is the correct verification sequence.

**Delivers:** `exportTraces()` method using `serializeTrace()` + Blob + `downloadFile`. `importTraces(file)` method using `FileReader.readAsText()` + `JSON.parse` + shape validation + `hydrateTrace()` + `this.traces.set()` + `db.saveTrace()`. Export/import controls in toolbar (inline in `app.xml` or extracted to `toolbar.js`). User-facing error notifications for invalid imports via `notification` service.

**Addresses:** Export as JSON (differentiator P1), import from JSON (differentiator P1).

**Avoids:** Pitfall 5 (Date type loss on import — explicit `new Date()` reconstruction in import path), Pitfall 6 (large export blocking main thread — stringify per-trace in a loop; measure actual payload size with a real RAG session before deciding on chunking), Pitfall 7 (import without validation — validate before inserting into store).

### Phase Ordering Rationale

- Phase 1 must come first because the IDB schema and write strategy are the foundation all other phases build on. A wrong decision here (like using `await` in bus handlers, or skipping the IDB availability try/catch) requires refactoring the entire write strategy — it cannot be patched incrementally.
- Phase 2 must follow Phase 1 because hydration has nothing to read until writes have persisted data. The delete/clear operations also require the IDB layer functions from Phase 1. The `onWillStart` bus subscription sequencing (hydrate fully, then subscribe) requires the hydration functions from Phase 1 to exist.
- Phase 3 can begin as soon as Phase 1's schema and `serializeTrace()` are done. Export reads from the in-memory Map and does not require Phase 2 to be complete. Import depends on `hydrateTrace()` from Phase 2 and `db.saveTrace()` from Phase 1.
- Within each phase, the build order in ARCHITECTURE.md applies: `db.js` → hydration → write-through → delete/clear → export → import. This order respects the dependency graph and ensures each step is verifiable before the next begins.

### Research Flags

No phase needs `/gsd:research-phase`. The research is comprehensive and all patterns are verified against Odoo master source code at local worktree paths.

**Standard patterns (skip research-phase):**
- **Phase 1:** IDB layer design is fully documented in STACK.md with verified Odoo source patterns for `IndexedDB`, `serializeTrace()`, and fire-and-forget. The `IDBQuotaExceededError` catch pattern is verified in `rpc_cache.js`. The schema and version strategy are fully specified.
- **Phase 2:** `onWillStart` usage, `hydrateTrace()` implementation, OWL reactive Map reconstruction, and `ConfirmationDialog` usage are all fully specified in ARCHITECTURE.md and PITFALLS.md. The delete/clear dual-operation pattern is specified at code level.
- **Phase 3:** Export (`downloadFile`, `serializeTrace()`) and import (`FileReader`, shape validation, `hydrateTrace()`) patterns are fully specified in STACK.md and ARCHITECTURE.md. The export file format is defined. No additional research needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All APIs verified against Odoo master source at `/Users/joseph/clones/odoo/odoo/.worktrees/master/`. Odoo `IndexedDB` class confirmed used in production by `menu_service`, `rpc_cache`, `offline_service`. `downloadFile` and `ConfirmationDialog` confirmed available in `web.assets_backend`. `FileInput` confirmed wrong for local import (verified server-upload implementation). |
| Features | HIGH | Feature set is small and unambiguous, defined by PROJECT.md. MDN, web.dev, Chrome DevTools, and Edge DevTools docs confirm what a persistence + export/import feature set for a developer tool should contain. Anti-features and deferral decisions are clearly justified with PROJECT.md citations. |
| Architecture | HIGH | Architecture grounded in direct inspection of the existing `app.js` source, OWL lifecycle documentation, and the Odoo `IndexedDB` class source. All integration points, data flow changes, and serialization patterns are specified at the code level in ARCHITECTURE.md. Build order is derived from dependency analysis. |
| Pitfalls | HIGH | All ten pitfalls grounded in direct source inspection (existing `app.js`, `clearAll()` method), OWL source (`onWillStart` vs `onMounted` semantics), IDB spec (transaction auto-close behavior), and official web.dev documentation on structured clone performance. Each pitfall includes specific "warning signs" and recovery cost. |

**Overall confidence:** HIGH

### Gaps to Address

- **RAG session payload sizes are empirically unknown:** PROJECT.md notes this as tech debt. A RAG-enabled trace could be 1-5MB per trace depending on conversation length. The export implementation (Phase 3) should measure actual payload sizes with a real RAG session before deciding whether per-trace chunked stringify is needed. The threshold for concern is approximately 2MB per trace — below that, `JSON.stringify` is fast enough for a developer tool. This is a verify-during-implementation decision, not a blocker.

- **Conflicting hook recommendations between ARCHITECTURE.md and PITFALLS.md:** ARCHITECTURE.md discusses using `onMounted` in some places while PITFALLS.md explicitly recommends `onWillStart` for hydration. The correct answer is `onWillStart` for hydration (PITFALLS.md is right). Bus subscription should start after hydration completes inside `onWillStart`. Confirm the existing `app.js` lifecycle structure before implementing to ensure the hydration and bus subscription sequence is correct.

- **Odoo `IndexedDB.invalidate()` exact behavior for single-store clear:** STACK.md states `invalidate("traces")` clears one store. Verify this against the `_invalidate` implementation at `indexed_db.js` lines 215-244 at implementation time to confirm the string-argument behavior before using it in `clearAllTraces()`.

## Sources

### Primary (HIGH confidence — direct source inspection at local worktree paths)

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — full Odoo `IndexedDB` class: `read`, `write`, `getAllKeys`, `invalidate`, `execute`, `_checkVersion`, `IDBQuotaExceededError`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/network/download.js` — `downloadFile` implementation: Blob + object URL lifecycle
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/confirmation_dialog/confirmation_dialog.js` — `ConfirmationDialog` props: `body`, `confirm`, `cancel`, `confirmLabel`, `confirmClass`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/file_input/file_input.js` — confirmed NOT suitable for local import (server-upload only)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/network/rpc_cache.js` — `IDBQuotaExceededError` catch pattern + `execute()` usage
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/webclient/menus/menu_service.js` — `new IndexedDB("webclient_menu", ...)` + `read`/`write` pattern in production
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — existing reactive store (`useState(new Map())`), bus event handlers, `onMounted` lifecycle, existing `clearAll()` method
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` — existing template structure (sidebar tree, header controls)
- `/Users/joseph/clones/odoo/custom/ai_debug/__manifest__.py` — asset bundle glob patterns confirming new files are picked up automatically
- `/Users/joseph/clones/odoo/custom/.planning/PROJECT.md` — v1.3 requirements, out-of-scope items, tech debt notes
- [MDN: Using IndexedDB](https://developer.mozilla.org/en-US/docs/Web/API/IndexedDB_API/Using_IndexedDB) — schema design, transactions, versioning
- [web.dev: IndexedDB Best Practices for App State](https://web.dev/articles/indexeddb-best-practices-app-state) — structured clone blocks main thread; per-record storage; stale-while-revalidate pattern

### Secondary (MEDIUM confidence)

- [Microsoft Edge DevTools: Share Performance Traces](https://learn.microsoft.com/en-us/microsoft-edge/devtools/performance/share-performance-traces) — export/import UX patterns for developer tools (official docs, updated Nov 2025)
- [Chrome DevTools: New in DevTools 101](https://developer.chrome.com/blog/new-in-devtools-101) — Recorder panel export/import JSON as established DevTools pattern
- [nolanlawson.com: Speeding up IndexedDB reads and writes](https://nolanlawson.com/2021/08/22/speeding-up-indexeddb-reads-and-writes) — write batching performance benchmark: 1k records one-at-a-time ~2s vs batched ~80ms
- [github.com/pesterhazy: Safari IDB transaction auto-close](https://gist.github.com/pesterhazy/4de96193af89a6dd5ce682ce2adff49a) — Safari closes transactions more aggressively; `Promise.resolve().then()` can close mid-transaction

### Tertiary (LOW confidence — verify at implementation)

- [LogRocket: Offline-first frontend apps 2025](https://blog.logrocket.com/offline-first-frontend-apps-2025-indexeddb-sqlite/) — write-through and sync queue patterns (editorial, not official docs)
- [dexie.org: Export/Import](https://dexie.org/docs/ExportImport/dexie-export-import) — streaming Blob construction for large IDB exports (reference only; not using Dexie)

---
*Research completed: 2026-02-22*
*Ready for roadmap: yes*
