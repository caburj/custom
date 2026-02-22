# Phase 11: Hydration and Trace Management - Research

**Researched:** 2026-02-22
**Domain:** OWL reactive store hydration from IndexedDB + checkbox-based bulk-delete UI
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Hydration experience:**
- Instant render on page load — no loading skeleton or spinner. IDB reads are assumed fast enough.
- Load ALL stored traces from IDB, not just the most recent session.
- Hydrated traces have a subtle visual indicator distinguishing them from live traces (Claude picks the specific indicator style).
- The indicator persists for the entire session — it does not disappear even if the trace receives new live events. It's about source, not staleness.

**Delete interaction:**
- Always-visible checkboxes on every trace entry in the sidebar — no hover-to-reveal.
- Checkbox selection is separate from clicking a trace to view its detail. Checkboxes are for bulk actions only.
- "Select all" checkbox in the sidebar header to toggle all traces selected/deselected.
- Action buttons (delete, and later export) always visible in the header area, but disabled when nothing is selected.
- Delete is always instant — no confirmation dialog, no undo toast, regardless of how many traces are selected.

**Clear all flow:**
- No separate "Clear all" button — select-all + delete covers this use case.
- After deleting all traces, the sidebar returns to its original empty state message.
- Note: This deviates from MGMT-02's confirmation dialog requirement — user explicitly chose instant delete with no confirmation.

**Sidebar state transitions:**
- Latest traces always at the top, consistent with current ordering behavior.
- Empty state message shown when IDB is empty (first visit or after clearing all). Disappears when first trace arrives.
- Orphan bus events (arriving for a trace that wasn't persisted because it was incomplete at refresh) are dropped silently — accepted data loss for incomplete traces.

### Claude's Discretion
- Specific style of the hydrated-trace indicator (muted opacity, small icon, color treatment, etc.)
- Ordering behavior when a hydrated trace receives new live events
- Any animation/transition when traces are deleted from the sidebar

### Deferred Ideas (OUT OF SCOPE)
- Export button in the header action area — Phase 12
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PERS-02 | All traces hydrate from IndexedDB on page load before first render (no flash of empty state) | `onWillStart` hook blocks initial render; `loadAllTraces()` function added to `db.js`; `hydrateTrace()` deserializer reconstructs `reactive(new Map())` for nested Maps |
| PERS-03 | Live bus events continue to update the UI in real time after hydration without regression | Hydrated traces use `reactive(new Map())` for `iterations` and `toolCalls` — bus event handlers call `.set()` on these Maps and OWL re-renders normally. Orphan bus events (for unhydrated trace IDs) silently dropped by existing guard `if (!trace) return`. |
| MGMT-01 | User can delete an individual trace (removed from both UI and IndexedDB) | Checkbox-based selection + bulk delete; `deleteTrace()` already exported from `db.js`; reactive Map delete + IDB delete; deselect if deleted trace was selected |
| MGMT-02 | User can clear all traces with a confirmation dialog before execution | User decision overrides this requirement: select-all + delete replaces the "Clear all" confirmation dialog. No confirmation dialog implemented. |
</phase_requirements>

---

## Summary

Phase 10 produced `db.js` with `probeIDB()`, `writeTrace()`, and `deleteTrace()`. The `onWillStart` hook already runs the IDB probe. Phase 11 has three independent work streams: (1) add `loadAllTraces()` to `db.js` and wire hydration into `onWillStart`; (2) add a `hydrateTrace()` deserializer that reconstructs `reactive(new Map())` Maps and parses ISO date strings; (3) add checkbox-based multi-select UI to the sidebar with a header action bar for delete.

The critical technical constraint is the exact IDB serialization format used in Phase 10. The `serializeTrace()` function stores iterations as an array of `[iterId, iterRecord]` pairs (not an object), and similarly for `toolCalls`. The hydration deserializer must mirror this exact format. Dates are stored as ISO strings (from the JSON round-trip in `writeTrace`). Only completed traces (those that received a `loop_end` event) are persisted — incomplete traces are accepted data loss and orphan bus events for them are silently dropped.

The select/delete UI is a standard email-client pattern (Gmail-style). OWL has no built-in "selected items" state management — a `Set` in `useState` tracks selected `trace_id` values. The header action bar's disabled state is derived from `selectedTraceIds.size === 0`. This is the entire complexity of the UI layer; there are no reactivity edge cases specific to the selection state.

**Primary recommendation:** Add `loadAllTraces()` to `db.js` first (using `execute()` with `getAll()`), wire hydration into the existing `onWillStart` block in `app.js`, then add the checkbox/selection/delete UI to `app.xml` and `app.js`.

---

## Standard Stack

### Core (already in project — no new dependencies)

| API | Source | Purpose | Why Standard |
|-----|--------|---------|--------------|
| `IndexedDB.execute(callback)` | `@web/core/utils/indexed_db` (already in `db.js`) | Bulk-read all traces from IDB using native `getAll()` | The `IndexedDB` class has no `getAll()` wrapper — `execute()` exposes the raw `IDBDatabase` and allows `objectStore.getAll()`. Already verified in STACK.md. |
| `reactive()` from `@odoo/owl` | Already imported in `app.js` | Wrap hydrated Map structures so bus event handlers trigger re-renders | Already used by `_onNewTrace`, `_onIteration` for new-trace Maps. Hydration must use the same wrapper. |
| `onWillStart` from `@odoo/owl` | Already in `app.js` | Block initial render until hydration completes — no flash of empty state | Already used for the IDB probe. Hydration goes in the same hook. |
| `useState` from `@odoo/owl` | Already in `app.js` | Track selected trace IDs as a reactive Set | New selection state added to `this.state` alongside existing `connectionStatus`, `selectedId`, etc. |
| `deleteTrace()` from `./db` | Already exported in `db.js` | Delete one trace record from IDB by trace_id | Already implemented in Phase 10. |

### No New Dependencies

No new npm packages, Odoo services, or module dependencies are needed. Everything required is already in the bundle.

---

## Architecture Patterns

### Pattern 1: `loadAllTraces()` Using `execute()` + `getAll()`

The Odoo `IndexedDB` class exposes `execute(callback)` which passes a live `IDBDatabase` instance to the callback. This is the correct path for bulk reads because the class has no `getAll()` wrapper.

**Two valid approaches:**

Option A — `getAllKeys()` then per-key `read()` (simpler, sequential):
```javascript
export async function loadAllTraces() {
    const keys = await idb.getAllKeys(STORE);
    if (!keys || keys.length === 0) return [];
    const results = [];
    for (const key of keys) {
        const record = await idb.read(STORE, key);
        if (record) results.push(record);
    }
    return results;
}
```

Option B — single `execute()` with native `getAll()` (one IDB operation, faster):
```javascript
export async function loadAllTraces() {
    return idb.execute((db) => {
        if (!db) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readonly");
            const req = tx.objectStore(STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
```

**Recommendation: Option B.** One IDB operation vs N sequential operations. For typical trace counts (dozens) the difference is negligible but Option B is more correct. The `STORE` constant is already defined as `"traces"` in `db.js`.

Note: `idb.execute()` uses a mutex internally. This is fine — hydration runs once, and the mutex ensures the `_checkVersion` migration from construction has completed before our `loadAllTraces()` call runs.

### Pattern 2: `hydrateTrace()` Deserializer

The `serializeTrace()` function (Phase 10) stores iterations as `[iterId, iterRecord]` pair arrays. The hydrator must mirror this exactly.

**Critical: the exact Phase 10 IDB format**

From `db.js` `serializeTrace()`:
```javascript
iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
    iterId,
    { ...iter fields..., toolCalls: [...iter.toolCalls.entries()].map(([tcId, tc]) => [tcId, {...tc}]) }
])
```

So the IDB record has:
- `iterations`: Array of `[iterationId, iterationRecord]` pairs
- Each `iterationRecord.toolCalls`: Array of `[toolCallId, toolCallRecord]` pairs
- All dates stored as ISO strings (from the `JSON.parse(JSON.stringify(...))` round-trip in `writeTrace`)
- `expanded` field NOT stored (it's excluded by `serializeTrace`)

**Hydration function:**
```javascript
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const [iterId, iter] of plain.iterations ?? []) {
        const toolCalls = reactive(new Map());
        for (const [tcId, tc] of iter.toolCalls ?? []) {
            toolCalls.set(tcId, tc);
        }
        iterations.set(iterId, {
            ...iter,
            receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
            expanded: false,  // UI state always starts collapsed on hydration
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        expanded: false,   // collapsed on hydration (locked decision)
        hydrated: true,    // permanent marker: this trace was loaded from IDB
        iterations,
    };
}
```

**The `hydrated: true` field** is how the template detects whether to show the hydrated-trace indicator. It is set during deserialization and never removed, even if the trace receives subsequent live bus events (locked decision: indicator is about source, not staleness).

### Pattern 3: Wiring Hydration into `onWillStart`

The existing `onWillStart` block runs `probeIDB()`. Hydration goes in the same block, after the probe succeeds:

```javascript
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) {
        this.state.ephemeralMode = true;
        return;
    }
    // Hydrate from IDB before first render
    const stored = await loadAllTraces();
    for (const plain of stored) {
        this.traces.set(plain.trace_id, hydrateTrace(plain));
    }
    // Auto-select first trace if any hydrated (matches existing SESS-03 auto-select logic)
    if (this.state.selectedId === null && this.traces.size > 0) {
        const firstId = [...this.traces.keys()].at(-1); // last key = top of reversed list
        this.state.selectedId = firstId;
        this.state.selectedType = "trace";
    }
});
```

Note: import `loadAllTraces` from `./db` alongside the existing `probeIDB`, `writeTrace`, `deleteTrace` imports.

### Pattern 4: Selection State for Checkbox-Based Bulk Delete

The selection state (which trace checkboxes are ticked) is entirely separate from `state.selectedId` (which trace is shown in the detail panel). This separation is locked by SIDE-05 and the CONTEXT.md decisions.

Add to `this.state`:
```javascript
this.state = useState({
    connectionStatus: "connecting",
    selectedId: null,
    selectedType: null,
    ephemeralMode: false,
    // Phase 11: checkbox selection for bulk delete
    checkedTraceIds: new Set(),  // reactive Set — OWL observes .add(), .delete(), .clear()
});
```

**OWL and reactive Set:** OWL's `useState` wraps the object with a reactive proxy. Mutations on nested objects (including `Set.add()`, `Set.delete()`, `Set.clear()`) ARE observed by OWL when accessed through the reactive proxy. This is confirmed by OWL's reactive proxy forwarding property access and mutation interception to nested objects.

**Header "select all" checkbox state:**
```javascript
get allChecked() {
    return this.traces.size > 0 && this.state.checkedTraceIds.size === this.traces.size;
}

get someChecked() {
    return this.state.checkedTraceIds.size > 0 && !this.allChecked;
}
```

The `someChecked` getter drives the indeterminate state of the header checkbox (`indeterminate` DOM property — must be set via a ref or `t-ref`, not `t-att-indeterminate` since `indeterminate` is a property not an attribute).

### Pattern 5: Delete Implementation

```javascript
async deleteCheckedTraces() {
    const ids = [...this.state.checkedTraceIds];
    // Clear selection state first
    this.state.checkedTraceIds.clear();
    // Clear detail panel selection if the selected trace is being deleted
    if (ids.includes(this.state.selectedId)) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    // Remove from reactive Map (triggers OWL re-render)
    for (const id of ids) {
        this.traces.delete(id);
    }
    // Delete from IDB (fire-and-forget per item — deleteTrace is already exported)
    for (const id of ids) {
        deleteTrace(id).catch((err) => {
            console.warn("[ai_debug] IDB delete failed:", err);
        });
    }
}
```

Note: `deleteTrace` is already exported from `db.js`. No changes needed to `db.js` for the delete path.

### Pattern 6: Header Checkbox Indeterminate State

The `indeterminate` property on a checkbox element is a JavaScript property, not an HTML attribute. It cannot be set with `t-att-indeterminate`. The correct OWL pattern uses `t-ref` and `onPatched`:

```javascript
this.selectAllRef = useRef("selectAll");

onPatched(() => {
    if (this.selectAllRef.el) {
        this.selectAllRef.el.indeterminate = this.someChecked;
    }
    // ... existing scroll/flash logic ...
});
```

In the template:
```xml
<input type="checkbox"
       t-ref="selectAll"
       t-att-checked="allChecked"
       t-on-change="toggleSelectAll"/>
```

### Pattern 7: Hydrated Trace Visual Indicator

**Recommendation:** A small `(archived)` text label in muted color alongside the agent name in the trace row. Rationale: consistent with the existing "Ephemeral" text label pattern in the header (Phase 10 decision: use text labels over Unicode for cross-platform reliability). Could alternatively use a subtle clock icon (`⏱`) or a muted badge. The indicator persists because `hydrated: true` is set at hydration time and never removed.

Implementation in `app.xml` trace row:
```xml
<span t-if="trace.hydrated" class="ai-tree-hydrated-badge" title="Loaded from storage">archived</span>
```

SCSS:
```scss
.ai-tree-hydrated-badge {
    font-size: 0.7em;
    opacity: 0.55;
    font-style: italic;
    margin-left: 4px;
}
```

Alternative options (for Claude's discretion): a faded clock emoji, a subtle left-border color change, or an opacity reduction on the entire row. The text label approach is most consistent with existing code style.

### Pattern 8: Sidebar Header Action Bar Layout

The header must accommodate a future Export button (Phase 12). Design the layout with that in mind:

```xml
<div class="ai-tree-header">
    <div class="ai-tree-header-left">
        <input type="checkbox" t-ref="selectAll" .../>
        <span>Traces</span>
    </div>
    <div class="ai-tree-header-actions">
        <!-- Delete button — visible always, disabled when nothing checked -->
        <button class="ai-tree-action-btn"
                t-att-disabled="state.checkedTraceIds.size === 0"
                t-on-click="deleteCheckedTraces"
                title="Delete selected traces">
            🗑
        </button>
        <!-- Phase 12 will add Export button here -->
    </div>
</div>
```

SCSS for the header layout:
```scss
.ai-tree-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    // ... existing padding/border styles ...
}

.ai-tree-header-left {
    display: flex;
    align-items: center;
    gap: 6px;
}

.ai-tree-header-actions {
    display: flex;
    align-items: center;
    gap: 4px;
}

.ai-tree-action-btn {
    background: none;
    border: none;
    cursor: pointer;
    opacity: 0.7;
    padding: 2px 4px;
    border-radius: 3px;

    &:hover:not(:disabled) { opacity: 1; background: var(--bs-tertiary-bg); }
    &:disabled { opacity: 0.3; cursor: not-allowed; }
}
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Bulk IDB read | Custom IDB transaction code | `idb.execute((db) => objectStore.getAll())` | The `IndexedDB` class's `execute()` method handles mutex, open, and error wrapping |
| IDB delete | Custom transaction | `deleteTrace()` already in `db.js` | Already implemented in Phase 10 |
| Indeterminate checkbox | CSS hack or visibility toggle | Standard DOM `indeterminate` property via `t-ref` + `onPatched` | Only settable as a JS property, not an HTML attribute |
| Reactive Set tracking | Array-based filter | `new Set()` inside `useState({})` | OWL reactive proxy intercepts Set mutations; no custom observable needed |

---

## Common Pitfalls

### Pitfall 1: Hydrating in `onMounted` Instead of `onWillStart`
**What goes wrong:** User sees flash of "No traces" state on every page load even when IDB has data.
**Why it happens:** `onMounted` runs after the first render; `onWillStart` blocks the first render.
**How to avoid:** Put hydration in `onWillStart`. The existing `onWillStart` block for `probeIDB()` is the correct extension point.
**Verified:** Confirmed by the `onWillStart` decision in STATE.md: "Hydration goes in `onWillStart`, not `onMounted` — prevents flash of empty state."

### Pitfall 2: Not Wrapping Hydrated Maps in `reactive()`
**What goes wrong:** Bus events after hydration (`_onIteration`, `_onToolCall`) call `trace.iterations.set(...)` but OWL does not re-render because the `iterations` Map is a plain Map, not reactive.
**Why it happens:** IDB returns plain objects; reactive proxy wrappers are stripped by the JSON round-trip.
**How to avoid:** `hydrateTrace()` must explicitly call `reactive(new Map())` for `iterations` and for each iteration's `toolCalls`.
**Verified:** Confirmed by STATE.md: "`hydrateTrace()` must explicitly reconstruct `reactive(new Map())` for all nested Maps — plain objects from IDB break live-event reactivity."

### Pitfall 3: Mismatching the Phase 10 IDB Serialization Format
**What goes wrong:** `hydrateTrace()` tries to iterate `plain.iterations` as if it were an object (`Object.entries(...)`) but the Phase 10 `serializeTrace()` stored it as an array of `[key, value]` pairs.
**Why it happens:** The research archives (STACK.md) show both `Object.fromEntries` and `[...Map.entries()]` patterns. The actual Phase 10 implementation used array-of-pairs.
**How to avoid:** Read `db.js` `serializeTrace()` directly. Iterations: `[...trace.iterations.entries()].map(([iterId, iter]) => [...])` → stored as array of `[iterId, iterRecord]`. ToolCalls: same. The hydrator uses `for (const [iterId, iter] of plain.iterations)` and `for (const [tcId, tc] of iter.toolCalls)`.

### Pitfall 4: Dates Are ISO Strings, Not Date Objects
**What goes wrong:** `getIterationDuration()` returns `NaN ms` for hydrated traces because it computes `trace.ended_at - iter.receivedAt` and both are strings.
**Why it happens:** `writeTrace()` in Phase 10 does `JSON.parse(JSON.stringify(serializeTrace(trace)))` before the IDB write. This converts all `Date` objects to ISO strings. The native IDB structured clone would have preserved Date objects, but the JSON round-trip converts them to strings.
**How to avoid:** `hydrateTrace()` must do `new Date(plain.started_at)`, `new Date(plain.ended_at)`, and `new Date(iter.receivedAt)` for all date fields.
**Verified:** Confirmed by STATE.md: "Dates become ISO strings — Phase 11 hydration must parse them back." The comment in `db.js` `writeTrace()` says exactly this.

### Pitfall 5: Reactive Set and OWL — Checking `.size` in Templates
**What goes wrong:** Template uses `state.checkedTraceIds.size === 0` but the template doesn't re-render when the Set changes because OWL doesn't track `.size` on a reactive Set automatically.
**Why it happens:** OWL's reactive proxy intercepts mutations (`add`, `delete`, `clear`) but size tracking depends on the proxy implementation.
**How to avoid:** Verify the `Set.size` reactivity in OWL before relying on it. Safe alternative: store the count as a separate reactive field `checkedCount: 0` and update it alongside Set mutations. Or use a simple array instead of a Set and derive size from `array.length`. The array approach is safer and OWL arrays are well-tested in templates.

**Alternative approach (safer):**
```javascript
this.state = useState({
    ...
    checkedTraceIds: new Set(),  // source of truth for fast lookups
});
// In template use: state.checkedTraceIds.size — test whether OWL tracks this
// Safe fallback: add checkedCount field and keep it in sync
```

### Pitfall 6: Checkbox Clicks Triggering Trace Selection (Row Click Handlers)
**What goes wrong:** The user ticks a checkbox and the detail panel also changes to show that trace — because the checkbox is inside the trace row div which has a click handler for selection.
**Why it happens:** Click events bubble. The checkbox `change` or `click` event bubbles up to the row's `t-on-click` handler.
**How to avoid:** Use `.stop` modifier on the checkbox's event handler to stop propagation: `t-on-change.stop="toggleTraceCheck(traceId)"` — or use `t-on-click.stop` on the checkbox wrapper. The existing `toggleExpand` already uses `.stop`: `t-on-click.stop="() => this.toggleExpand(traceId, 'trace')"`. Same pattern applies to checkboxes.

### Pitfall 7: Orphan Bus Events After Hydration
**What goes wrong:** A `new_trace` event arrives (or `iteration` / `tool_call`) for a `trace_id` that was never persisted (because the loop was mid-run at the time of the last refresh). The handler tries to find the trace in `this.traces` and fails, but the concern is whether this causes any observable error.
**Behavior:** The existing bus handlers already guard: `const trace = this.traces.get(payload.trace_id); if (!trace) return;`. Orphan events are silently dropped. This is the accepted data loss documented in CONTEXT.md. No additional handling required.

### Pitfall 8: `deleteTrace()` Race with Active `writeTrace()` Call
**What goes wrong:** A `loop_end` event fires, `writeTrace()` is called (fire-and-forget). Before it completes, the user deletes the trace, `deleteTrace()` runs and removes the IDB record. Then `writeTrace()` completes and re-creates the record in IDB.
**Why it happens:** Both operations are fire-and-forget. IDB operations are serialized by the `IndexedDB` class's internal mutex, so `deleteTrace()` waits for `writeTrace()` to complete, then deletes. Then the `writeTrace()` Promise has already resolved (there's only one — it was already the first in the mutex queue). So actually this race does NOT exist — the mutex ensures FIFO ordering. The delete always runs after the write completes.
**Conclusion:** No special handling needed. The mutex in `IndexedDB` prevents write-after-delete reappearance.

---

## Code Examples

### Loading All Traces from IDB (new function for `db.js`)

```javascript
/**
 * Load all stored traces from IndexedDB.
 * Returns an array of plain serialized trace records.
 * Returns [] if IDB is unavailable or store is empty.
 *
 * Note: records contain iterations as [iterId, iterRecord] pair arrays
 * and dates as ISO strings — hydrateTrace() reconstructs the reactive
 * Maps and Date objects.
 */
export async function loadAllTraces() {
    return idb.execute((db) => {
        if (!db) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readonly");
            const req = tx.objectStore(STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
```

### `hydrateTrace()` (new function in `app.js`)

```javascript
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const [iterId, iter] of plain.iterations ?? []) {
        const toolCalls = reactive(new Map());
        for (const [tcId, tc] of iter.toolCalls ?? []) {
            toolCalls.set(tcId, tc);
        }
        iterations.set(iterId, {
            ...iter,
            receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
            expanded: false,
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        expanded: false,
        hydrated: true,  // persistent marker: trace was loaded from storage
        iterations,
    };
}
```

### Updated `onWillStart` in `app.js`

```javascript
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) {
        console.warn("[ai_debug] IndexedDB unavailable — running in ephemeral mode");
        this.state.ephemeralMode = true;
        return;
    }
    // Hydrate from IDB before first render (PERS-02)
    const stored = await loadAllTraces();
    for (const plain of stored) {
        this.traces.set(plain.trace_id, hydrateTrace(plain));
    }
    // Auto-select first trace if any (SESS-03: auto-select when nothing selected)
    if (this.state.selectedId === null && this.traces.size > 0) {
        const firstKey = [...this.traces.keys()].at(-1); // at(-1) = top of reversed list
        this.state.selectedId = firstKey;
        this.state.selectedType = "trace";
    }
});
```

### Selection State and Delete Method (new in `app.js`)

```javascript
// In setup(), add to this.state:
this.state = useState({
    connectionStatus: "connecting",
    selectedId: null,
    selectedType: null,
    ephemeralMode: false,
    checkedTraceIds: new Set(),  // Phase 11: checkbox selection
});

// Select-all header checkbox ref
this.selectAllRef = useRef("selectAll");

// Getter for header checkbox state
get allChecked() {
    return this.traces.size > 0 && this.state.checkedTraceIds.size === this.traces.size;
}

get someChecked() {
    return this.state.checkedTraceIds.size > 0 && !this.allChecked;
}

// Toggle one trace checkbox
toggleTraceCheck(traceId) {
    if (this.state.checkedTraceIds.has(traceId)) {
        this.state.checkedTraceIds.delete(traceId);
    } else {
        this.state.checkedTraceIds.add(traceId);
    }
}

// Toggle all-selected / none-selected
toggleSelectAll() {
    if (this.allChecked) {
        this.state.checkedTraceIds.clear();
    } else {
        for (const id of this.traces.keys()) {
            this.state.checkedTraceIds.add(id);
        }
    }
}

// Delete all checked traces from UI and IDB
async deleteCheckedTraces() {
    const ids = [...this.state.checkedTraceIds];
    if (ids.length === 0) return;
    // Clear checkbox selection
    this.state.checkedTraceIds.clear();
    // Clear detail panel selection if deleted
    if (ids.includes(this.state.selectedId)) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    // Remove from reactive Map (OWL re-renders)
    for (const id of ids) {
        this.traces.delete(id);
    }
    // Delete from IDB (fire-and-forget per item)
    for (const id of ids) {
        deleteTrace(id).catch((err) => {
            console.warn("[ai_debug] IDB delete failed for", id, err);
        });
    }
}
```

### `onPatched` update for indeterminate checkbox

```javascript
// Add to existing onPatched callback:
onPatched(() => {
    // Indeterminate state for select-all checkbox (cannot be set via HTML attribute)
    if (this.selectAllRef.el) {
        this.selectAllRef.el.indeterminate = this.someChecked;
    }
    // ... existing scroll/flash logic ...
});
```

### Template Additions (`app.xml`)

**Header row:**
```xml
<div class="ai-tree-header">
    <div class="ai-tree-header-left">
        <input type="checkbox"
               class="ai-tree-select-all"
               t-ref="selectAll"
               t-att-checked="allChecked"
               t-on-change.stop="toggleSelectAll"/>
        <span>Traces</span>
    </div>
    <div class="ai-tree-header-actions">
        <button class="ai-tree-action-btn"
                t-att-disabled="state.checkedTraceIds.size === 0 or undefined"
                t-on-click="deleteCheckedTraces"
                title="Delete selected">
            &#x1F5D1;
        </button>
    </div>
</div>
```

Note: `t-att-disabled="... or undefined"` — the `or undefined` idiom removes the attribute entirely when false, avoiding `disabled="false"` which still disables in some browsers.

**Per-trace row (Level 0), add checkbox before chevron:**
```xml
<div class="ai-tree-row level-0" ...>
    <input type="checkbox"
           class="ai-tree-row-check"
           t-att-checked="state.checkedTraceIds.has(traceId)"
           t-on-change.stop="() => this.toggleTraceCheck(traceId)"/>
    <!-- hydrated indicator -->
    <span t-if="trace.hydrated" class="ai-tree-hydrated-badge" title="Loaded from storage">archived</span>
    <span class="ai-tree-chevron" ...>...</span>
    <span class="ai-tree-label" ...>...</span>
    <!-- status indicator -->
    ...
</div>
```

---

## State of the Art

| Phase 10 State | Phase 11 Change | Impact |
|----------------|-----------------|--------|
| `onWillStart` only probes IDB availability | `onWillStart` also hydrates all traces from IDB | No flash of empty state on page load |
| Traces from previous sessions are lost on refresh | Hydrated traces appear immediately | PERS-02 satisfied |
| Live bus events always work (reactive Maps from `_onNewTrace`) | Live events also work for hydrated traces (reactive Maps from `hydrateTrace`) | PERS-03 satisfied |
| `deleteTrace()` exported from `db.js` but unused in UI | Checkbox-based bulk delete UI wires up `deleteTrace()` | MGMT-01 satisfied |
| Header has "Clear all" button + trash emoji | Header has select-all checkbox + delete action button | Replaces old clear-all with user's preferred select-all+delete pattern |
| `clearAll()` method clears reactive Map but not IDB | `deleteCheckedTraces()` clears both | Correct dual-delete as per STATE.md decision |

**Deprecated by Phase 11:**
- `clearAll()` method: superseded by `deleteCheckedTraces()`. Should be removed or left dead to avoid confusion.
- The existing trash-emoji `<button class="ai-tree-clear">` in the sidebar header: replaced by the new action bar.

---

## Open Questions

1. **OWL reactive Set `.size` tracking**
   - What we know: OWL's reactive proxy intercepts mutations on nested objects. The OWL docs confirm `useState({})` makes the object reactive, and property access on nested objects through the proxy is observed.
   - What's unclear: Whether `Set.size` specifically is tracked for re-renders in OWL 2.x. The reactive proxy needs to intercept the `size` getter.
   - Recommendation: Test in the browser after implementation. Safe fallback: add a `checkedCount: 0` field to `this.state` and increment/decrement it alongside `checkedTraceIds.add()`/`delete()`/`clear()`. Use `state.checkedCount` in the template instead of `state.checkedTraceIds.size`.

2. **Auto-select behavior after hydration when `selectedId` was already set**
   - What we know: The auto-select logic in `_onNewTrace` fires `if (this.state.selectedId === null)`. This guard exists to preserve explicit user selections (SIDE-05).
   - What's unclear: After hydration sets `selectedId` to the first trace, should a subsequent `_onNewTrace` event (arriving for a genuinely new live trace) still auto-select the new trace? Currently yes — `selectedId` would be non-null after hydration (pointing to a hydrated trace), so the auto-select in `_onNewTrace` would NOT fire. This may be the desired behavior (preserve user focus) but deserves a deliberate decision.
   - Recommendation: Keep current logic. After hydration sets `selectedId`, new live traces do NOT auto-steal focus. This is consistent with the SIDE-05 principle that only explicit user actions or the initial `selectedId === null` condition should change the selection.

3. **`checkedTraceIds` cleanup when traces are deleted externally**
   - What we know: The `deleteCheckedTraces()` method clears `checkedTraceIds` before deleting.
   - What's unclear: If a live trace is replaced (same `trace_id`, new `new_trace` event) while it's checked, the checkbox stays checked for the new trace. This is a corner case that only occurs in unusual circumstances (reused trace_id, which shouldn't happen since trace IDs are UUIDs).
   - Recommendation: No special handling needed. UUIDs are unique. This edge case is not reachable in normal operation.

---

## Sources

### Primary (HIGH confidence — direct source reads)

- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/db.js` — exact Phase 10 IDB schema, `serializeTrace()` format (iterations as `[key, value]` pairs, JSON round-trip for dates), `deleteTrace()` implementation, `STORE` constant
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — current `onWillStart` block, all bus handlers, `this.state` structure, `useRef`, `onPatched` usage
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` — current sidebar header markup, trace row structure
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — `IndexedDB` class API: `execute()`, `getAllKeys()`, `read()`, `delete()` absence, mutex behavior
- `/Users/joseph/clones/odoo/custom/.planning/STATE.md` — key decisions: `onWillStart` for hydration, `hydrateTrace()` reactive Map reconstruction, dual delete
- `/Users/joseph/clones/odoo/custom/.planning/research/STACK.md` — `execute()` + `getAll()` pattern for bulk reads, `getAllKeys()` + `read()` alternative
- `/Users/joseph/clones/odoo/custom/.planning/research/PITFALLS.md` — `onWillStart` vs `onMounted` pitfall, reactive Map reconstruction pitfall, Date type loss pitfall, dual-delete pitfall

### Secondary (MEDIUM confidence)

- `app.xml` existing pattern of `t-on-click.stop` for chevron — confirms `.stop` modifier works as expected for preventing event bubbling in OWL templates
- Phase 10 commit history — `edc4a8b fix(10-01): strip reactive proxies before IDB write` confirms JSON round-trip approach and ISO date string storage

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs already in use in the project; no new dependencies
- Architecture: HIGH — `hydrateTrace()` format derived directly from `serializeTrace()` in `db.js`; all patterns verified from existing codebase
- Pitfalls: HIGH — directly verified from Phase 10 implementation and existing STATE.md decisions; one MEDIUM item (OWL Set reactivity)

**Research date:** 2026-02-22
**Valid until:** Stable — no external dependencies, derived from own codebase
