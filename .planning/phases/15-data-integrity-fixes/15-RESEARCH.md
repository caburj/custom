# Phase 15: Data Integrity Fixes - Research

**Researched:** 2026-02-24
**Domain:** JavaScript data layer — export/import cascade, IDB hydration ordering, auto-select guard
**Confidence:** HIGH

## Summary

Phase 15 closes three data integrity gaps discovered during the v1.4 milestone audit. All three changes live entirely in `app.js` (and potentially `app.xml` for a minor template guard). No new files, no new dependencies, no schema changes — this is surgical logic work on existing functions.

The most consequential gap is DATA-02 (export cascade). `exportSelected()` currently serializes only the explicitly checked root traces; it silently drops all subagent descendants. Re-importing such a file reconstructs orphaned child traces with dangling `parent_trace_id` pointers that reference traces not in the file. The fix is well-scoped: collect descendant IDs using the already-written `_collectDescendantIds()` helper and include them in the export array.

DATA-03 (two-pass IDB hydration) addresses a subtle ordering hazard. `loadAllTraces()` returns records in IDB insertion order, which is not guaranteed to match parent-before-child. If a child trace record appears before its parent in the array, `sidebarNodes` tries to render it as a root (because `parent_trace_id` is present but the parent trace object does not yet exist in `this.traces` at that moment). The fix is a second pass after all traces are loaded: scan for traces whose `parent_trace_id` points to a loaded trace and confirm they will render correctly as children. No re-hydration is needed — just validation that the parent is present. The current single-pass sort by `created_ts` actually mitigates this in practice (parents are always created before children), but the requirement calls for an explicit second-pass validation as a formal guarantee.

DATA-01 (serializeTrace/hydrateTrace roundtrip) was already fixed in commit `a7ac163` during Phase 14 Plan 01. The three fields (`parent_trace_id`, `parent_tool_call_id`, `session_id`) are now written by `serializeTrace()` and the spread operator in `hydrateTrace()` restores them. This requirement needs formal closure documentation only — no code change.

**Primary recommendation:** Implement DATA-02 (export cascade) and DATA-03 (two-pass validation) as separate tasks. Close DATA-01 with a code verification step only.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | `serializeTrace()` and `hydrateTrace()` preserve parent linkage fields (`parent_trace_id`, `parent_tool_call_id`, `session_id`) across IDB roundtrip | Already implemented in `a7ac163`. `serializeTrace()` lines 52-54 in db.js write all three fields. `hydrateTrace()` spread `...plain` restores them. Formal closure only. |
| DATA-02 | JSON export/import preserves subagent hierarchy — imported traces reconstruct parent-child nesting correctly | `exportSelected()` currently only exports checked root traces. Must be extended to include descendants via `_collectDescendantIds()`. Import path already handles parent linkage via `hydrateTrace()` spread — no import changes needed. |
| DATA-03 | Two-pass IDB hydration: first pass loads all traces, second pass validates parent pointers (handles random IDB record ordering) | `onWillStart` does a single pass with a `created_ts` sort. Need second pass after all traces are loaded to validate that each trace with `parent_trace_id` has a corresponding parent in `this.traces`. Also: auto-select must skip orphan traces. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| OWL (Odoo Web Library) | Project standard | Reactive component framework | All existing code uses OWL |
| IndexedDB (via Odoo `@web/core/utils/indexed_db`) | Project standard | Trace persistence | Already integrated in db.js |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None needed | — | — | Phase is pure logic, no new dependencies |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-memory second-pass scan | IndexedDB secondary index | Index adds schema complexity and requires version bump that wipes existing data — not worth it |
| Recursive export collection | Flat all-at-once export | All-at-once is simpler but no existing mechanism; `_collectDescendantIds` is already written and tested |

**Installation:**
No new packages needed.

## Architecture Patterns

### Recommended Project Structure
No structural changes. All changes confined to:
```
ai_debug/static/src/app/
├── app.js   # exportSelected(), onWillStart hydration, _placeTrace auto-select guard
└── db.js    # No changes needed (DATA-01 already complete)
```

### Pattern 1: Export Cascade via _collectDescendantIds
**What:** Before serializing, expand `ids` to include all descendants using the existing helper.
**When to use:** Whenever a set of root trace IDs needs to be exported completely.
**Example:**
```javascript
// Current (broken for subagent hierarchies):
exportSelected() {
    const ids = [...this.state.checkedTraceIds];
    const records = ids.map((id) => {
        const trace = this.traces.get(id);
        return JSON.parse(JSON.stringify(serializeTrace(trace)));
    }).filter(Boolean);
    // ... download
}

// Fixed (cascade to descendants):
exportSelected() {
    const ids = [...this.state.checkedTraceIds];
    // Collect all descendants — same pattern as deleteCheckedTraces
    const allIds = [...ids];
    for (const id of ids) {
        allIds.push(...this._collectDescendantIds(id));
    }
    const uniqueIds = [...new Set(allIds)];
    const records = uniqueIds.map((id) => {
        const trace = this.traces.get(id);
        if (!trace) return null;
        return JSON.parse(JSON.stringify(serializeTrace(trace)));
    }).filter(Boolean);
    // ... download
}
```
Source: Existing `deleteCheckedTraces()` in app.js (lines 800-825) — identical pattern already proven correct.

### Pattern 2: Two-Pass IDB Hydration with Orphan Validation
**What:** After the first pass loads all traces into `this.traces`, a second pass checks whether each child trace's `parent_trace_id` exists in the loaded set.
**When to use:** During `onWillStart`, immediately after the first-pass loop completes.
**Example:**
```javascript
// After first pass — all traces loaded:
for (const plain of stored) {
    this.traces.set(plain.trace_id, hydrateTrace(plain));
}

// Second pass — validate parent pointers:
for (const [id, trace] of this.traces) {
    if (trace.parent_trace_id && !this.traces.has(trace.parent_trace_id)) {
        // Parent not in store — this is an orphan. Options:
        // (a) Null out the parent fields so it renders as root
        // (b) Remove it from the store entirely (more aggressive)
        // (c) Keep as-is but exclude from auto-select
        // Recommendation: null out parent fields → renders as root trace,
        // consistent with how 30s-promoted orphans from the live buffer are handled.
        trace.parent_trace_id = null;
        trace.parent_tool_call_id = null;
    }
}

// Auto-select: pick the newest ROOT trace (depth===0 after orphan promotion)
if (this.state.selectedId === null && this.traces.size > 0) {
    const rootTraces = [...this.traces.values()].filter(t => !t.parent_trace_id);
    if (rootTraces.length > 0) {
        // Newest first (highest created_ts)
        rootTraces.sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0));
        this.state.selectedId = rootTraces[0].trace_id;
        this.state.selectedType = "trace";
    }
}
```

### Pattern 3: Auto-Select Guard for Non-Orphan Traces
**What:** The current auto-select at `onWillStart` picks the last-keyed trace (`at(-1)`) regardless of whether it is a root or a child. After a page refresh with a hierarchy loaded, `at(-1)` could be a subagent trace (child). The detail panel would show a child trace without its parent hierarchy context being obvious.
**When to use:** Always, as part of the hydration second pass.
**Note:** This is part of DATA-03's success criterion ("orphan traces never appear in the detail panel"). The requirement language says "trace whose `parent_trace_id` points to a non-existent parent" — but restricting auto-select to root traces is the right default regardless of orphan status.

### Anti-Patterns to Avoid
- **Modifying loadAllTraces() in db.js to sort by parent-before-child:** IDB does not expose a reliable topological ordering primitive. Sort by `created_ts` (already done) is the correct approach; the second pass handles any remaining edge cases.
- **Adding a new IDB schema version to enforce referential integrity:** Would require a version bump that wipes all stored traces. Unnecessary given the simplicity of in-memory validation.
- **Making hydrateTrace() aware of the traces Map:** hydrateTrace is a pure function (plain record → hydrated object). Keeping it pure is correct; validation belongs in the onWillStart orchestrator.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Descendant collection | Custom tree walk in exportSelected | `_collectDescendantIds()` already in app.js | Already written, already proven correct in `deleteCheckedTraces` |
| Orphan detection | IDB indexing or schema constraints | In-memory Map lookup after second pass | IDB has no FK constraints; in-memory is O(n) and instant at this scale |

**Key insight:** Every needed primitive already exists in the codebase. This phase is wiring them together correctly, not building new infrastructure.

## Common Pitfalls

### Pitfall 1: Export Order Matters for Import
**What goes wrong:** If descendant traces are exported before their parents in the JSON array, the import sort by `created_ts` may not reliably produce parent-before-child order.
**Why it happens:** `_collectDescendantIds` returns descendants in iteration order over `this.traces`, which is insertion order. If a child was added before its parent was registered (unlikely but possible with out-of-order bus events that were promoted), the child's `created_ts` could be earlier.
**How to avoid:** The import sort by `created_ts` (already in `_applyImport`) handles this correctly in practice because parents always have earlier `created_ts` than children. The second-pass validation also handles any edge case by nulling out unresolvable parent pointers.
**Warning signs:** Re-imported traces appearing at root level when they should be nested.

### Pitfall 2: Auto-Select Selects a Subagent Trace After Hydration
**What goes wrong:** Current code selects `[...this.traces.keys()].at(-1)` — the last key in insertion order after the `created_ts` sort. After a typical session with subagent traces, the last inserted trace is the most recently completed subagent, which is a child trace. The detail panel auto-populates with a subagent's data, and the user may not understand the context without seeing the parent.
**Why it happens:** The existing `at(-1)` selection is trace-type-agnostic.
**How to avoid:** Filter to root traces (`!t.parent_trace_id`) before auto-selecting. Consistent with `rootTracesCount` logic already used for checkboxes.
**Warning signs:** On page load, detail panel shows a trace labeled with an agent name that has no visible parent in the sidebar (because the root trace is collapsed or above it in the list).

### Pitfall 3: Double-Counting Descendants in Export
**What goes wrong:** If two root traces A and B are checked, and B is a descendant of A, then `_collectDescendantIds(A)` already includes B. If B is also in `checkedTraceIds`, B's descendants get collected twice.
**Why it happens:** The deduplication step (`new Set(allIds)`) handles this correctly — same pattern already proven in `deleteCheckedTraces`. Just make sure the Set deduplication is applied before the map/serialize step.
**How to avoid:** Always deduplicate with `[...new Set(allIds)]` before mapping to records. This is already the pattern in `deleteCheckedTraces`.

### Pitfall 4: DATA-01 Treated as Requiring Code Changes
**What goes wrong:** A planner or executor spends time "fixing" `serializeTrace()`/`hydrateTrace()` when the fix is already shipped in `a7ac163`.
**Why it happens:** The requirement is listed as Pending in REQUIREMENTS.md but the code change was committed as a deviation fix during Phase 14 Plan 01.
**How to avoid:** DATA-01 task should be a verification step only: read db.js lines 52-54 and hydrateTrace() spread, confirm the three fields are present, mark closed.

## Code Examples

### DATA-02: Corrected exportSelected()
```javascript
// Source: app.js — modeled on deleteCheckedTraces() lines 800-825
exportSelected() {
    const ids = [...this.state.checkedTraceIds];
    if (ids.length === 0) return;

    // Cascade: include all descendant traces (same pattern as deleteCheckedTraces)
    const allIds = [...ids];
    for (const id of ids) {
        allIds.push(...this._collectDescendantIds(id));
    }
    const uniqueIds = [...new Set(allIds)];

    const records = uniqueIds.map((id) => {
        const trace = this.traces.get(id);
        if (!trace) return null;
        return JSON.parse(JSON.stringify(serializeTrace(trace)));
    }).filter(Boolean);

    if (records.length === 0) return;
    const json = JSON.stringify(records, null, 2);
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10);
    a.href = url;
    a.download = `ai-debug-traces-${today}.json`;
    a.click();
    URL.revokeObjectURL(url);
}
```

### DATA-03: Two-Pass Hydration with Orphan Promotion and Root-Only Auto-Select
```javascript
// Source: onWillStart in app.js — replaces lines 269-284
const stored = await loadAllTraces();
stored.sort((a, b) =>
    (a.created_ts || new Date(a.started_at || 0).getTime()) -
    (b.created_ts || new Date(b.started_at || 0).getTime())
);

// First pass: load all traces
for (const plain of stored) {
    this.traces.set(plain.trace_id, hydrateTrace(plain));
}

// Second pass: validate parent pointers, promote true orphans to root
for (const trace of this.traces.values()) {
    if (trace.parent_trace_id && !this.traces.has(trace.parent_trace_id)) {
        // Parent missing from store — promote to root (retain fields for debugging)
        trace.parent_trace_id = null;
        trace.parent_tool_call_id = null;
    }
}

// Auto-select: pick newest ROOT trace only
if (this.state.selectedId === null && this.traces.size > 0) {
    let bestTrace = null;
    for (const trace of this.traces.values()) {
        if (!trace.parent_trace_id) {
            if (!bestTrace || (trace.created_ts || 0) > (bestTrace.created_ts || 0)) {
                bestTrace = trace;
            }
        }
    }
    if (bestTrace) {
        this.state.selectedId = bestTrace.trace_id;
        this.state.selectedType = "trace";
    }
}
```

### DATA-01: Verification Only (No Code Change)
```javascript
// db.js lines 52-54 — already correct as of commit a7ac163:
parent_trace_id: trace.parent_trace_id,
parent_tool_call_id: trace.parent_tool_call_id,
session_id: trace.session_id,

// hydrateTrace() in app.js line 39 — spread restores all fields:
return {
    ...plain,   // includes parent_trace_id, parent_tool_call_id, session_id
    started_at: plain.started_at ? new Date(plain.started_at) : null,
    // ...
};
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Export only checked traces (no cascade) | Export checked + all descendants | Phase 15 (this phase) | Reimport reconstructs full hierarchy |
| Single-pass hydration (sort by created_ts) | Single-pass + second-pass validation | Phase 15 (this phase) | Orphans nulled out, auto-select restricted to roots |
| Auto-select any trace (`at(-1)`) | Auto-select root traces only | Phase 15 (this phase) | Detail panel never opens on a contextless subagent |
| parent linkage omitted from serializeTrace | All three linkage fields serialized | Phase 14 Plan 01, commit `a7ac163` | Hierarchy survives page refresh and import |

**Deprecated/outdated:**
- `at(-1)` auto-select: replaced by root-filtered newest-first selection.

## Open Questions

1. **Should DATA-03 orphan promotion mutate trace.parent_trace_id = null or remove the trace entirely?**
   - What we know: The live buffer 30s-promotion path (`_onNewTrace`) calls `_placeTrace(payload)` with parent fields intact but no parent in `this.traces` — the trace lands at root with its parent fields present. The `sidebarNodes` getter filters root traces by `!t.parent_trace_id`.
   - What's unclear: If we keep `parent_trace_id` set on a promoted orphan, `sidebarNodes` will never render it (filtered out as a non-root trace that has no matching parent). If we null it out, it renders as root but loses the audit trail.
   - Recommendation: Null out `parent_trace_id` on orphans at hydration time — consistent with how `sidebarNodes` identifies root traces. The `parent_tool_call_id` can be nulled too. This matches the intent of "orphan traces never appear in the detail panel" (they should appear as roots, not disappear entirely).

2. **Is the `created_ts` sort sufficient to guarantee parent-before-child ordering for the first pass?**
   - What we know: `created_ts` is set to `Date.now()` in `_placeTrace` — always at parent trace creation before any child can spawn. IDB records child traces only after `loop_end` fires, which is always after parent `loop_end` (because child sessions run synchronously inside parent tool calls).
   - What's unclear: The ordering guarantee holds for traces from the same browser session. Cross-session imports may have clock skew.
   - Recommendation: The sort is fine for the first pass. The second-pass validation catches any remaining misorderings regardless of cause.

## Validation Architecture

*(nyquist_validation not set in config.json — skipping automated test framework section)*

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection: `/ai_debug/static/src/app/app.js` — `exportSelected()`, `deleteCheckedTraces()`, `_collectDescendantIds()`, `onWillStart` hydration, `_placeTrace` auto-select
- Direct codebase inspection: `/ai_debug/static/src/app/db.js` — `serializeTrace()`, `hydrateTrace()`, `loadAllTraces()`
- Phase 14 Plan 01 SUMMARY.md — confirms DATA-01 was fixed in commit `a7ac163` as a deviation fix
- REQUIREMENTS.md — exact requirement text for DATA-01, DATA-02, DATA-03
- ROADMAP.md Phase 15 success criteria — exact acceptance conditions

### Secondary (MEDIUM confidence)
- STATE.md decisions log — confirms pattern decisions (flat Map, `_pendingChildren` buffer, orphan promotion behavior)

### Tertiary (LOW confidence)
- None needed for this phase — all findings are from authoritative codebase inspection.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, all existing patterns
- Architecture: HIGH — patterns directly derived from existing working code in the same file
- Pitfalls: HIGH — identified from direct code reading, not speculation

**Research date:** 2026-02-24
**Valid until:** Indefinite — codebase is the source of truth, not an external library
