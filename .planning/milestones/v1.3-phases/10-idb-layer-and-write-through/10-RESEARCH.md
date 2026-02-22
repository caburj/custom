# Phase 10: IDB Layer and Write-Through - Research

**Researched:** 2026-02-22
**Domain:** IndexedDB write-through, Odoo IndexedDB utility, ephemeral mode detection
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Write timing:**
- Write on trace completion (loop end event), not per bus event
- In-flight traces are not persisted — a reload mid-loop simply loses the incomplete trace (no corruption, no partial records)
- No beforeunload flush — accept the loss of in-progress traces
- Fire-and-forget: write failures are logged via console.warn but do not block the UI
- No retry on write failure

**Degradation UX:**
- Show a subtle ephemeral mode indicator in the header/toolbar area when IndexedDB is unavailable
- Icon (e.g. crossed-out disk) with tooltip explaining: "IndexedDB unavailable — traces won't persist across refreshes"
- Dynamic detection: if a write fails mid-session, switch to ephemeral mode and show the indicator (not just a startup check)
- Console.warn on IDB unavailability in addition to the visual indicator

**Trace record shape:**
- UUID as the IDB key for each trace record (not tied to ai.session.id or any backend identifier)
- No IDB schema versioning until end of milestone — keep it simple, deal with migrations if needed later
- Record metadata beyond raw trace data: Claude's discretion (e.g. storedAt timestamp for Phase 11 hydration ordering)
- Record structure (full blob vs split): Claude's discretion based on existing reactive store data structures

### Claude's Discretion
- Exact record structure (full denormalized blob vs split) — decide based on existing store shape
- Whether to include metadata fields (storedAt, version tag) alongside trace data
- IDB database and store naming
- Exact icon and tooltip styling for ephemeral mode indicator

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PERS-01 | Traces auto-persist to IndexedDB as bus events arrive (fire-and-forget, non-blocking) | Odoo's `IndexedDB.write()` is async and returns a Promise that can be called without await; the write triggers on `loop_end` event when the trace is complete |
| PERS-04 | App degrades gracefully to ephemeral mode if IndexedDB is unavailable (e.g. private browsing) | Odoo's `IndexedDB` silently no-ops in private mode; probe via `execute()` at startup + catch write rejections mid-session to detect and surface ephemeral state |
</phase_requirements>

## Summary

Phase 10 creates `db.js` — a thin wrapper around Odoo's existing `@web/core/utils/indexed_db` utility — and wires fire-and-forget IDB writes into `app.js`'s `_onLoopEnd` handler so completed traces are durably stored. The Odoo `IndexedDB` class handles concurrency via a Mutex, auto-creates object stores lazily, and silently no-ops when the database is unavailable (private browsing), which requires an explicit probe to detect degraded mode.

The write strategy is straightforward: on `loop_end`, serialize the completed trace (with nested Maps converted to arrays of entries) and call `db.write("traces", uuid, serializedRecord)` without awaiting the result. No UI state is blocked. For degradation, a startup probe and write-error handler set `state.ephemeralMode = true`, which shows a subtle indicator in the header.

The key architectural insight is that Odoo's `IndexedDB` uses explicit out-of-line keys (no `keyPath`) — the trace UUID is passed as the second argument to `write()`, not embedded in the record schema. The stored record should be a plain serializable object (Maps converted to entry arrays, Dates kept as-is since IDB's structured clone preserves them) to avoid any proxy/reactive wrapper issues during storage and later hydration.

**Primary recommendation:** Create `db.js` as a plain module (not an OWL service) exporting a single `IndexedDB` instance and a `writeTrace(trace)` function. Keep all IDB knowledge out of `app.js` — `app.js` calls `writeTrace(trace)` in `_onLoopEnd` and ignores the returned Promise.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@web/core/utils/indexed_db` | Odoo master | IDB wrapper with Mutex, auto-schema, error handling | Already in Odoo; used by `menu_service`, `rpc_cache`, `offline_service`; no external dependency needed |
| `@odoo/owl` | Odoo master | `onWillStart`, `reactive`, `useState` for OWL component integration | Already the app framework; `onWillStart` for startup probe before first render |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@web/core/utils/strings` `uuid()` | Odoo master | Generate client-side UUID for IDB key | Use instead of `crypto.randomUUID()` — this is the Odoo convention for UUID generation |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Odoo's `IndexedDB` wrapper | Raw `window.indexedDB` API | Raw API allows `keyPath` in store schema but requires hand-rolling Mutex, version management, and error handling that Odoo already provides |
| Odoo's `IndexedDB` wrapper | `idb` npm library | `idb` is not available in Odoo's asset bundle; adding it requires manifest changes and is unnecessary given the existing utility |
| `uuid()` from `@web/core/utils/strings` | `crypto.randomUUID()` | Both work; `uuid()` is the established Odoo pattern (used in properties fields etc.) |

**Installation:** No new packages — all dependencies already available in Odoo.

## Architecture Patterns

### Recommended Project Structure
```
ai_debug/static/src/app/
├── app.js          # Modified: import writeTrace, add ephemeral state, wire _onLoopEnd
├── app.xml         # Modified: add ephemeral mode indicator to header
├── app.scss        # Modified: add .ai-ephemeral-indicator styles
├── db.js           # NEW: IDB instance + writeTrace() + probe
└── main.js         # Unchanged
```

### Pattern 1: Odoo IndexedDB Usage
**What:** Construct once at module level, use table name as first arg to all operations. Keys are explicit (out-of-line), not embedded in records.
**When to use:** Any IDB read/write in this project.
**Example:**
```javascript
// Source: /addons/web/static/src/webclient/menus/menu_service.js
import { IndexedDB } from "@web/core/utils/indexed_db";

const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";

const idb = new IndexedDB(DB_NAME, DB_VERSION);

// Write: key is the explicit UUID, value is the serialized record
await idb.write(STORE, traceUUID, serializedRecord);

// Read (for hydration in Phase 11):
const record = await idb.read(STORE, traceUUID);

// All keys (for hydration in Phase 11):
const keys = await idb.getAllKeys(STORE);
```

### Pattern 2: Fire-and-Forget Write
**What:** Call the async write function without `await`, catch and handle errors asynchronously.
**When to use:** `_onLoopEnd` handler — must not block the bus event processing or UI update.
**Example:**
```javascript
// In app.js _onLoopEnd handler:
this._onLoopEnd = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    // ... update trace status, ended_at, duration_ms ...

    // Fire-and-forget: do NOT await
    writeTrace(trace).catch((err) => {
        console.warn("[ai_debug] IDB write failed:", err);
        this.state.ephemeralMode = true;  // switch to ephemeral mid-session
    });
};
```

### Pattern 3: Startup Probe for Ephemeral Mode Detection
**What:** Use `idb.execute()` (public method) to probe IDB availability before first render.
**When to use:** `onWillStart` in `AiDebugApp.setup()`.

**Key insight about Odoo's degradation behavior:** When `indexedDB.open()` fires `onerror` (private browsing), Odoo's `_execute` calls `callback(undefined)` — the `(db) => { if (db) ... }` guard silently no-ops and the Promise **resolves** (not rejects) with `undefined`. This means writes in private mode appear to succeed. To detect this, probe with a test that distinguishes `db` being falsy.

```javascript
// In db.js:
export async function probeIDB() {
    // execute() is public on IndexedDB - passes db (truthy) or undefined (private/blocked)
    const result = await idb.execute((db) => (db ? "ok" : null));
    return result === "ok";  // false means IDB unavailable
}
```

Then in `app.js` `setup()`:
```javascript
import { onWillStart } from "@odoo/owl";
// ...
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) {
        console.warn("[ai_debug] IndexedDB unavailable — ephemeral mode");
        this.state.ephemeralMode = true;
    }
});
```

### Pattern 4: Trace Serialization (Maps → Entry Arrays)
**What:** Convert the reactive store's nested Map structure to a plain serializable object before writing to IDB.
**When to use:** In `writeTrace()` in `db.js`.

**Why explicit serialization:** OWL's `reactive(new Map())` returns a Proxy. Passing a Proxy to IDB's `put()` (which uses structured clone internally) may work in some browsers but is not guaranteed. Explicit serialization avoids any proxy-related issues and produces a well-defined record shape for Phase 12 export and Phase 11 hydration.

**IDB's structured clone DOES support Date objects** — store them as-is (not ISO strings). Phase 11 hydration will reconstruct `reactive(new Map())` from the arrays.

```javascript
// In db.js:
function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        storedAt: Date.now(),  // metadata for Phase 11 hydration ordering
        agent_name: trace.agent_name,
        model_name: trace.model_name,
        status: trace.status,
        started_at: trace.started_at,   // Date — preserved by structured clone
        ended_at: trace.ended_at,       // Date — preserved by structured clone
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        // Map → array of [iterationId, iterationRecord] pairs
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                iteration_id: iter.iteration_id,
                trace_id: iter.trace_id,
                iteration_index: iter.iteration_index,
                has_error: iter.has_error,
                receivedAt: iter.receivedAt,  // Date
                is_final: iter.is_final,
                error: iter.error,
                messages_sent: iter.messages_sent,
                raw_response: iter.raw_response,
                // Map → array of [toolCallId, toolCallRecord] pairs
                toolCalls: [...iter.toolCalls.entries()],
            }
        ]),
    };
}

export async function writeTrace(trace) {
    const record = serializeTrace(trace);
    return idb.write(STORE, trace.trace_id, record);
}
```

**Note on trace_id as IDB key:** The CONTEXT says "UUID as the IDB key." The `trace_id` field in the bus payload is already used as the Map key in the reactive store. The CONTEXT also says "not tied to ai.session.id." Verify whether the existing `trace_id` from the bus is already a UUID or a backend integer. If it's a backend integer, generate a client-side UUID at `new_trace` time and store it as an additional field. If it's already a UUID string, use it directly.

### Pattern 5: Ephemeral Mode Indicator in Header
**What:** Add a small icon+tooltip to the header when `state.ephemeralMode` is true.
**When to use:** In `app.xml` header section.

```xml
<!-- In app.xml, inside .ai-debug-header-status -->
<span t-if="state.ephemeralMode"
      class="ai-ephemeral-indicator"
      title="IndexedDB unavailable — traces won't persist across refreshes">
    &#x1F4BE;&#x20E0;  <!-- disk + combining enclosing circle backslash (or use text/CSS) -->
</span>
```

Alternative: a simple text badge is more reliable than Unicode combining characters. The SCSS can use CSS to show a crossed-out disk symbol. The existing status dot pattern (`.ai-debug-status-dot`) in `app.scss` provides a model for simple indicator styling.

### Anti-Patterns to Avoid
- **Awaiting IDB writes in bus handlers:** Never `await writeTrace()` inside `_onNewTrace`, `_onIteration`, `_onToolCall`, or `_onLoopEnd`. Bus handlers must return synchronously to keep the reactive store updates non-blocking.
- **Using markRaw on the IndexedDB instance:** The offline service does `markRaw(new IndexedDB(...))` because it stores the instance on a reactive class. Since `db.js` exports a module-level constant (not stored in OWL reactive state), `markRaw` is not needed.
- **Passing the reactive trace proxy directly to IDB:** Always serialize (extract plain values) before calling `idb.write()`. Never pass `this.traces.get(id)` directly.
- **Checking `indexedDB` global availability as the probe:** `window.indexedDB` exists in private browsing (the API is present but the database opens with an error). The correct probe is an actual `execute()` round-trip.
- **Writing on every bus event:** The CONTEXT locks write-on-loop-end. Do not write on `new_trace`, `iteration`, or `tool_call` events.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| IDB concurrency | Custom promise queue | Odoo's `IndexedDB` Mutex | Race conditions between reads, schema upgrades, and writes are already handled |
| IDB schema migration | Custom version detection | Odoo's `_checkVersion` mechanism | Odoo auto-wipes and recreates on version change — just bump the version string |
| UUID generation | `Math.random()` string | `uuid()` from `@web/core/utils/strings` | Odoo standard; uses `crypto.getRandomValues` for adequate uniqueness |
| Error silencing | Try/catch wrappers | Odoo's `if (db)` guard + fire-and-forget `.catch()` | Already handled by the library; just add `.catch()` on the returned Promise |

**Key insight:** Odoo's `IndexedDB` wrapper handles the hardest parts of raw IDB (concurrency via Mutex, lazy store creation, version management, quota errors). Phase 10 is thin glue code, not a full IDB implementation.

## Common Pitfalls

### Pitfall 1: Assuming Write Failures Reject in Private Browsing
**What goes wrong:** Developer expects `idb.write()` to reject when IDB is unavailable, catches the rejection to set ephemeral mode — but in private browsing the write silently resolves as `undefined`.
**Why it happens:** Odoo's `_execute` onerror handler calls `callback(undefined)` and then `resolve(undefined)` — it does not `reject`. The `if (db)` guard in write/read callbacks converts failure into a no-op that resolves.
**How to avoid:** Use `probeIDB()` at startup via `onWillStart`. For mid-session failures (storage quota, transaction abort), those DO propagate as rejections (from `_write`'s `transaction.onerror`/`onabort`) — catch them on the write Promise.
**Warning signs:** Unit tests pass but traces disappear in private browsing with no console errors.

### Pitfall 2: Writing the reactive Proxy to IDB
**What goes wrong:** `idb.write("traces", id, this.traces.get(id))` stores the Proxy object. The structured clone algorithm may fail or clone incorrectly depending on the browser's handling of Proxy objects.
**Why it happens:** `this.traces.get(id)` returns an OWL reactive Proxy, not a plain object.
**How to avoid:** Always call `serializeTrace(trace)` to produce a plain serializable object before the write call.
**Warning signs:** `DataCloneError` in the browser console during write.

### Pitfall 3: Writing Before Loop Ends (Incomplete Trace)
**What goes wrong:** If `writeTrace` is called during `_onNewTrace` or `_onIteration`, the stored record will be incomplete — no `ended_at`, `duration_ms`, and iterations may be partial.
**Why it happens:** Temptation to persist early "in case of crash."
**How to avoid:** The CONTEXT locks write to loop-end. Only write in `_onLoopEnd` after updating `trace.status`, `trace.ended_at`, and `trace.duration_ms`.
**Warning signs:** Hydrated traces in Phase 11 show `status: "running"` and no duration.

### Pitfall 4: IDB Key Conflicts if trace_id is Not a Client UUID
**What goes wrong:** If the backend's `trace_id` in bus payloads is a database integer (not a UUID), two different browser sessions could collide on the same key in IDB.
**Why it happens:** The bus payload `trace_id` may be a Postgres serial ID, not a UUID.
**How to avoid:** Inspect the bus payload in `_onNewTrace` — check `payload.trace_id` type. If it's numeric/sequential, generate a client UUID with `uuid()` at `new_trace` time and store it as a separate `clientId` field. Use `clientId` as the IDB key.
**Warning signs:** After running multiple sessions, hydrated traces overwrite each other.

### Pitfall 5: The `storedAt` Field Missing Breaks Phase 11 Ordering
**What goes wrong:** Phase 11 hydration needs to reconstruct the sidebar in the correct order (by original insertion order or time). Without a `storedAt` timestamp, ordering requires the IDB insertion order (not guaranteed to be stable or accessible).
**Why it happens:** Omitting `storedAt` to keep the record minimal.
**How to avoid:** Include `storedAt: Date.now()` in `serializeTrace()`. This is low cost and future-proofs Phase 11.

### Pitfall 6: Ephemeral Mode Not Reactive
**What goes wrong:** `state.ephemeralMode` is set to `true` in a `.catch()` callback that runs outside of OWL's render cycle — the indicator never appears.
**Why it happens:** OWL's `useState` is observable, but mutations from async callbacks must still be tracked properly.
**How to avoid:** Ensure `state.ephemeralMode` is declared in `useState({..., ephemeralMode: false})` and mutated via `this.state.ephemeralMode = true`. OWL tracks mutations to `useState`-created objects reactively, so setting the property in any async context will schedule a re-render.

## Code Examples

### db.js — Complete Module
```javascript
// Source: Pattern derived from /addons/web/static/src/webclient/menus/menu_service.js
//         and /addons/web/static/src/core/utils/indexed_db.js (Odoo master)
/** @odoo-module **/
import { IndexedDB } from "@web/core/utils/indexed_db";

const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";

const idb = new IndexedDB(DB_NAME, DB_VERSION);

/**
 * Probe whether IndexedDB is available in this session.
 * Returns true if available, false if blocked (e.g., private browsing).
 *
 * Technique: idb.execute() passes db to the callback when open succeeds,
 * or calls callback(undefined) when onerror fires. We distinguish by checking
 * if db is truthy.
 */
export async function probeIDB() {
    const result = await idb.execute((db) => (db ? "ok" : null));
    return result === "ok";
}

/**
 * Serialize a trace from the reactive store into a plain IDB-storable record.
 * Maps are converted to arrays of [key, value] entries (structured clone would
 * preserve Maps, but explicit serialization avoids Proxy-related issues and
 * produces a well-defined schema for Phase 11 hydration and Phase 12 export).
 */
function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        storedAt: Date.now(),
        agent_name: trace.agent_name,
        model_name: trace.model_name,
        status: trace.status,
        started_at: trace.started_at,
        ended_at: trace.ended_at,
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                iteration_id: iter.iteration_id,
                trace_id: iter.trace_id,
                iteration_index: iter.iteration_index,
                has_error: iter.has_error,
                receivedAt: iter.receivedAt,
                is_final: iter.is_final,
                error: iter.error,
                messages_sent: iter.messages_sent,
                raw_response: iter.raw_response,
                toolCalls: [...iter.toolCalls.entries()],
            },
        ]),
    };
}

/**
 * Write a completed trace to IndexedDB.
 * Returns a Promise that resolves when written or silently when IDB is unavailable.
 * Caller should .catch() to detect mid-session failures.
 */
export function writeTrace(trace) {
    const record = serializeTrace(trace);
    return idb.write(STORE, trace.trace_id, record);
}
```

### app.js Integration Points
```javascript
// Add to imports:
import { onWillStart } from "@odoo/owl";
import { probeIDB, writeTrace } from "./db";

// Add to useState in setup():
this.state = useState({
    connectionStatus: "connecting",
    selectedId: null,
    selectedType: null,
    ephemeralMode: false,   // NEW: true when IDB unavailable
});

// Add onWillStart (before onMounted):
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) {
        console.warn("[ai_debug] IndexedDB unavailable — running in ephemeral mode");
        this.state.ephemeralMode = true;
    }
});

// Modify _onLoopEnd to add fire-and-forget write:
this._onLoopEnd = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    trace.status = /* ... existing status logic ... */;
    trace.ended_at = new Date();
    trace.duration_ms = payload.duration_ms;

    // Fire-and-forget: do NOT await
    writeTrace(trace).catch((err) => {
        console.warn("[ai_debug] IDB write failed — switching to ephemeral mode:", err);
        this.state.ephemeralMode = true;
    });
};
```

### app.xml Ephemeral Indicator
```xml
<!-- Inside .ai-debug-header-status, after the connection status span: -->
<span t-if="state.ephemeralMode"
      class="ai-ephemeral-indicator"
      title="IndexedDB unavailable — traces won't persist across refreshes">
    &#x26A0;&#xFE0F;
</span>
```

### app.scss Ephemeral Indicator
```scss
.ai-ephemeral-indicator {
    font-size: 12px;
    opacity: 0.8;
    cursor: default;
    user-select: none;
    margin-left: 4px;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hand-rolled IDB with `onupgradeneeded` | Odoo's `IndexedDB` utility with lazy auto-schema | Odoo ~16/17 | No schema declarations needed; Mutex handles concurrency |
| `idb` npm library | Odoo's built-in `IndexedDB` wrapper | N/A (never used in Odoo) | No external dependency; stays within Odoo ecosystem |
| `indexedDB.transaction('relaxed')` workaround | `{ durability: "relaxed" }` in `IDBTransaction` options | Supported in modern browsers | Odoo already uses this for write performance |

**Deprecated/outdated:**
- `window.mozIndexedDB`, `window.webkitIndexedDB`, `window.msIndexedDB`: These vendor prefixes are obsolete. Odoo's `IndexedDB` uses the standard `indexedDB` global.

## Open Questions

1. **Is `trace_id` from the bus payload a UUID or a sequential integer?**
   - What we know: The bus payload sends `payload.trace_id` in `_onNewTrace`. The CONTEXT says "not tied to ai.session.id or any backend identifier" and "use client-generated UUID."
   - What's unclear: Whether `trace_id` is already a UUID string (from the backend model) or a Postgres serial integer that would conflict across sessions.
   - Recommendation: Inspect `ai_session.py` or the bus payload shape in `ir_websocket.py`. If it's an integer, generate a `clientId = uuid()` at `_onNewTrace` time and store it alongside the trace. Use `clientId` as the IDB key in `writeTrace`. If it's already a UUID string, use `trace_id` directly.

2. **Does the Odoo `IndexedDB` `execute()` method correctly distinguish private browsing from success?**
   - What we know: In `_execute`, `request.onerror` calls `callback(undefined)` and resolves. The callback `(db) => (db ? "ok" : null)` would return `null` when `db` is undefined.
   - What's unclear: Whether Firefox's private mode fires `onerror` vs some other failure path (e.g., `onsuccess` with a restricted db object).
   - Recommendation: Test the probe in Firefox private mode before completing the phase. The `probeIDB()` function should be easy to validate in DevTools console.

3. **Should `expanded` and `selectedId` UI state be excluded from the serialized record?**
   - What we know: `expanded` and `selectedId` are ephemeral UI state (collapse/expand, selection). They shouldn't be persisted.
   - What's unclear: Whether `expanded: true` on a new trace (a locked decision from Phase 6) should be the default on hydration too.
   - Recommendation: Exclude `expanded` from `serializeTrace()`. Phase 11's `hydrateTrace()` can set `expanded: true` as the default (consistent with the existing `_onNewTrace` behavior).

## Sources

### Primary (HIGH confidence)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — Full source read; Mutex usage, API, error handling, private browsing behavior
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/webclient/menus/menu_service.js` — Real-world IndexedDB usage pattern in Odoo
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/network/rpc_cache.js` — Fire-and-forget write pattern, IDBQuotaExceededError handling
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/offline/offline_service.js` — markRaw pattern, IndexedDB in reactive context
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/strings.js` — `uuid()` implementation
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — Full source read; existing reactive store structure, bus handlers, onMounted lifecycle

### Secondary (MEDIUM confidence)
- OWL source in `owl.js` — `onWillStart` confirmed available (line 2726); confirmed it hooks into component lifecycle before mounting

### Tertiary (LOW confidence)
- Firefox private mode IDB behavior: Known from general web knowledge that `indexedDB.open()` fires `onerror` in Firefox private mode; Safari and Chrome have similar behavior but may vary. Mark for validation during implementation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — source code read directly, all imports verified
- Architecture: HIGH — Odoo's IndexedDB API is stable, patterns derived from existing usages
- Pitfalls: HIGH for structural pitfalls (Proxy issue, private mode no-op); MEDIUM for browser-specific degradation behavior (requires test validation)

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (stable APIs; only concern is if Odoo master changes indexed_db.js)
