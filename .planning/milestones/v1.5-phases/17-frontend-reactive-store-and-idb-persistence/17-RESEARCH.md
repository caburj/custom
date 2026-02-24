# Phase 17: Frontend Reactive Store and IDB Persistence - Research

**Researched:** 2026-02-24
**Domain:** OWL reactive store extension, IDB serialization/hydration, bus event handler wiring
**Confidence:** HIGH — research is entirely against the existing codebase (no external libraries needed)

## Summary

Phase 17 is pure data-plumbing: extend the existing OWL reactive iteration objects in `app.js` to carry `tokens`, `duration_ms`, and `ai_provider` fields sourced from the Phase 16 bus events, then symmetrically update `serializeTrace` and `hydrateTrace` in `db.js` so the data survives IDB round-trips. No new files, no new dependencies, no schema migrations.

The implementation touches five specific locations in two existing files: the `_onIteration` handler, a new `normalizeTokens()` helper, one or two trace-level aggregation getter methods (for Phase 18 consumption), the `serializeTrace` function, and the `hydrateTrace` function. All changes follow patterns already present in the codebase.

One naming mismatch between the Phase 16 backend token schema and the CONTEXT.md store schema must be resolved at the `_onIteration` boundary: the backend emits `tokens.cached` (single field), but the user decided the store uses `tokens.cache_read` and `tokens.cache_write` separately. The normalization helper handles this translation.

**Primary recommendation:** All changes go in `app.js` and `db.js`. Follow existing patterns exactly — `_onIteration` mutation pattern, `serializeTrace` field enumeration pattern, `hydrateTrace` spread pattern.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Full breakdown stored per iteration: input, output, cache_read, cache_write, reasoning, total
- Nested object shape: `iteration.tokens = { input, output, cache_read, cache_write, reasoning, total }`
- `duration_ms` stored as flat field on the iteration (server-measured value from Phase 16, stored as-is)
- `ai_provider` string stored on each iteration (e.g. 'openai', 'google') for Phase 18 metrics table
- Trace-level computed getters for: total_input, total_output, total_cached, total_reasoning, total_tokens, total_duration_ms
- Computed from iteration list (OWL reactive sum on access), not incremental accumulator
- Per-iteration + per-trace aggregation levels only (no per-tool-call aggregation)
- Store exposes raw numbers only — formatting (abbreviation, locale, units) is Phase 18's concern
- Errored iterations: all token fields default to 0, duration_ms defaults to 0
- No separate hasTokenData flag — existing iteration error/status field is sufficient for Phase 18 to distinguish
- Hydration backfill: hydrateTrace fills missing token/timing fields with zero defaults for pre-Phase 17 IDB data
- Uniform shape guaranteed — no null checks needed downstream
- In-memory reactive store updates instantly per bus event (OWL reactivity)
- IDB persist fires on loop_end only (not per-event write-through for token/timing data)
- Mid-trace refresh loses in-progress token data — acceptable since trace is interrupted anyway
- Extend existing serializeTrace to include tokens and duration_ms fields — no separate persist path

### Claude's Discretion
- Exact computed getter naming and implementation pattern
- How to wire bus event handler to update iteration tokens/timing fields
- serializeTrace/hydrateTrace field mapping details
- Any needed OWL reactive wrapper specifics

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIDE-02 | Sidebar token/time counters increment visually as new iteration events arrive (OWL reactive count-up) | OWL reactivity: any reactive property read in a template re-renders when mutated. Setting `iteration.tokens` in `_onIteration` triggers re-render of any template expression reading it. The "count-up" is the natural consequence — no animation infrastructure needed. |
| PERS-01 | Token and timing data persists through IDB round-trip (serializeTrace/hydrateTrace updated symmetrically) | serializeTrace enumerates every field to serialize; hydrateTrace spreads the plain record back. Adding `tokens`, `duration_ms`, `ai_provider` to both functions is a symmetric 3-field extension. |
| PERS-02 | IDB schema version remains unchanged (no DB_VERSION bump) | Adding fields to the iteration JSON blob is purely additive — IndexedDB stores the full JSON blob under the `traces` key. No object store structure changes. `DB_VERSION` stays at 1. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| OWL (via `@odoo/owl`) | Odoo 17 bundled | Reactive UI, `useState`, `reactive` | Already in use throughout app.js |
| Odoo `IndexedDB` utility (`@web/core/utils/indexed_db`) | Odoo 17 bundled | IDB abstraction | Already in use in db.js |

### Supporting
No additional libraries needed. All patterns are already present in the codebase.

### Alternatives Considered
None applicable — locked to existing OWL + Odoo IDB stack.

**Installation:** None required.

## Architecture Patterns

### Recommended Project Structure
No structural changes. All work goes into existing files:
```
ai_debug/static/src/app/
├── app.js   ← _onIteration, normalizeTokens, trace aggregation getters, hydrateTrace
└── db.js    ← serializeTrace iteration field additions
```

### Pattern 1: OWL Reactive Plain Object Mutation

**What:** The iteration objects are plain JS objects stored as values in a `reactive(new Map())`. OWL tracks property reads on reactive proxies. When `_onIteration` sets `iteration.tokens = ...`, all template expressions that read `iter.tokens` (or any sub-property) re-render.

**When to use:** Any time a bus event updates a field on an existing reactive object.

**Example (existing pattern from `_onToolCallCompleted`):**
```js
// Source: app.js lines 230-235
tc.result = payload.result;
tc.success = payload.success;
tc.error = payload.error || null;
tc.triggered_confirmation = payload.triggered_confirmation || false;
tc.confirmation_message = payload.confirmation_message || null;
tc.status = "completed";
```

Following the same pattern for `_onIteration` token/timing fields:
```js
// In _onIteration, after the iterations.set() block:
const iter = trace.iterations.get(payload.iteration_id);
if (iter) {
    iter.tokens = normalizeTokens(payload.tokens);
    iter.duration_ms = payload.duration_ms ?? 0;
    iter.ai_provider = payload.provider ?? null;
}
```

However, there is a subtlety: `_onIteration` currently only creates the iteration if it does not already exist (the `if (!trace.iterations.has(...))` guard). Since iteration events are typically one-shot (one `iteration` bus event per LLM call), the fields can be set directly in the initial `iterations.set()` call rather than in a separate mutation step. Either approach works; setting them inside the initial object literal is cleaner.

### Pattern 2: normalizeTokens Helper

**What:** Translate the sparse backend token dict `{input, output, total, cached?, reasoning?}` to the full store shape `{input, output, cache_read, cache_write, reasoning, total}` with zero defaults.

**Key translation:** `payload.tokens.cached` → `cache_read` (backend uses `cached`, store uses `cache_read`). `cache_write` is always 0 since no backend field exists.

```js
function normalizeTokens(t) {
    if (!t) return { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0, total: 0 };
    return {
        input: t.input ?? 0,
        output: t.output ?? 0,
        cache_read: t.cached ?? 0,   // backend 'cached' → store 'cache_read'
        cache_write: t.cache_write ?? 0,  // always 0 (no backend field)
        reasoning: t.reasoning ?? 0,
        total: t.total ?? 0,
    };
}
```

This function lives at module scope in `app.js`, alongside `hydrateTrace`.

### Pattern 3: Trace-Level Aggregation Getters

**What:** Compute sum totals across all iterations of a trace. Called from Phase 18 templates.

**When to use:** Phase 18 templates will call these to display trace-level metrics.

**Implementation options:**
- **Method on AiDebugApp** (like existing `getIterationDuration`): `getTraceTotals(trace)` returns `{total_tokens, total_duration_ms, total_input, total_output, total_cached, total_reasoning}`. Called from template as `this.getTraceTotals(node.trace)`.
- **Plain getter on the App class**: `get selectedTraceTotals()` returning aggregation for the currently selected trace.

The existing pattern in the codebase is methods for data-dependent computations (e.g., `getIterationDuration`, `getSelectedTrace`). A single `getTraceTotals(trace)` method returning the full aggregation object is the cleanest match to this pattern.

```js
getTraceTotals(trace) {
    let total_tokens = 0, total_duration_ms = 0,
        total_input = 0, total_output = 0,
        total_cached = 0, total_reasoning = 0;
    for (const iter of trace.iterations.values()) {
        const t = iter.tokens;
        if (t) {
            total_input += t.input || 0;
            total_output += t.output || 0;
            total_cached += t.cache_read || 0;
            total_reasoning += t.reasoning || 0;
            total_tokens += t.total || 0;
        }
        total_duration_ms += iter.duration_ms || 0;
    }
    return { total_tokens, total_duration_ms, total_input, total_output, total_cached, total_reasoning };
}
```

Because `trace.iterations` is a `reactive(new Map())`, this method is reactive when called from an OWL template — each call tracks the `.values()` iteration and any `.tokens` / `.duration_ms` reads.

### Pattern 4: serializeTrace Extension

**What:** Add `tokens`, `duration_ms`, `ai_provider` to the per-iteration serialization in `db.js`.

**Existing pattern (from db.js lines 59-85):**
```js
iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
    iterId,
    {
        iteration_id: iter.iteration_id,
        // ... existing fields ...
        raw_response: iter.raw_response,
        // ADD:
        tokens: iter.tokens,
        duration_ms: iter.duration_ms,
        ai_provider: iter.ai_provider,
    },
])
```

`tokens` is a plain object `{input, output, cache_read, cache_write, reasoning, total}` — JSON-serializable, no special handling needed. The existing `JSON.parse(JSON.stringify(...))` call in `writeTrace` handles OWL Proxy stripping.

### Pattern 5: hydrateTrace Backfill

**What:** Fill missing token/timing fields with zero defaults when loading pre-Phase 17 IDB records.

**Existing pattern (from app.js lines 31-35):**
```js
iterations.set(iterId, {
    ...iter,
    receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
    expanded: true,
    toolCalls,
});
```

Extend to add defaults:
```js
iterations.set(iterId, {
    ...iter,
    receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
    expanded: true,
    toolCalls,
    // Phase 17: zero-default for pre-17 IDB records that lack these fields
    tokens: iter.tokens ?? { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0, total: 0 },
    duration_ms: iter.duration_ms ?? 0,
    ai_provider: iter.ai_provider ?? null,
});
```

The `?? operator` ensures pre-Phase 17 records (where these fields are absent) get zero defaults, while Phase 17+ records keep their stored values.

### Anti-Patterns to Avoid

- **Adding a `hasTokenData` flag**: Locked decision says no separate flag. Use `iter.has_error` for distinguishing errored iterations in Phase 18.
- **Per-event IDB writes for token data**: Persist only on `loop_end` (already the case). Don't add `writeTrace` calls in `_onIteration`.
- **Incremental accumulator on the trace object**: Don't maintain a running `trace.total_tokens` that gets incremented per event. Compute on access via `getTraceTotals()`.
- **Bumping DB_VERSION**: PERS-02 explicitly forbids this. Additive JSON fields require no schema migration.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Reactivity for new iteration fields | Custom event bus / manual DOM updates | OWL reactive plain object mutation (existing pattern) | Setting properties on reactive-wrapped Map values triggers OWL re-render automatically |
| IDB schema migration for new fields | Migration code, DB_VERSION bump | None — JSON blob is additive | IDB stores the whole trace as one JSON blob; new fields appear transparently |
| Token normalization at display time | Per-template normalization | `normalizeTokens()` at ingestion time | Normalize once, read many times; downstream code always sees uniform shape |

**Key insight:** OWL reactivity tracks property reads on reactive proxy chains. Iteration objects stored in a `reactive(new Map())` are automatically reactive — setting any property triggers re-render for templates reading that property. No additional reactive wrapper is needed.

## Common Pitfalls

### Pitfall 1: Setting Fields on the Iteration BEFORE It Exists in the Map

**What goes wrong:** If `_onIteration` creates the iteration object in `iterations.set(...)` and then tries to mutate it via `trace.iterations.get(payload.iteration_id).tokens = ...`, there's a redundant lookup. Worse, if the guard `if (!trace.iterations.has(...))` is bypassed, the `.get()` returns undefined and the property assignment throws.

**Why it happens:** The handler has an early-return guard: if the iteration already exists, it skips creation. This means token/timing fields set only in the creation block would NOT be applied to pre-existing iterations (though this edge case shouldn't occur in practice — iteration IDs are unique per LLM call).

**How to avoid:** Set `tokens`, `duration_ms`, `ai_provider` inside the initial object literal passed to `iterations.set()`, not as a post-creation mutation. This is the cleaner and safer approach.

**Warning signs:** `iter.tokens` is `undefined` in Phase 18 templates despite bus events flowing.

### Pitfall 2: OWL Proxy vs. Plain Object in IDB Write

**What goes wrong:** `serializeTrace` accesses `iter.tokens` through the reactive proxy. The existing `writeTrace` already wraps with `JSON.parse(JSON.stringify(...))` to strip OWL Proxy wrappers. The `tokens` object is a plain object literal — no special handling needed.

**Why it happens:** OWL wraps reactive objects in Proxy. IDB's structured clone algorithm cannot serialize Proxies (DataCloneError). The existing JSON round-trip in `writeTrace` handles this.

**How to avoid:** No change needed — existing `JSON.parse(JSON.stringify(serializeTrace(trace)))` in `writeTrace` handles it.

### Pitfall 3: `cache_read` vs. `cached` Naming Mismatch

**What goes wrong:** Backend emits `tokens.cached`. Phase 18 components expect `tokens.cache_read`. If `normalizeTokens` maps incorrectly, cache token data is silently lost or shown under wrong field.

**Why it happens:** The CONTEXT.md uses `cache_read`/`cache_write` (future-proofed for separate read/write tracking), but the current backend only extracts a single `cached` field for both providers.

**How to avoid:** `normalizeTokens` must translate: `cache_read: t.cached ?? 0`. Document this mapping in a comment.

### Pitfall 4: Hydration Clobbers Existing Fields with Wrong Defaults

**What goes wrong:** If `hydrateTrace` sets `tokens: iter.tokens ?? defaultObj`, but `iter.tokens` is `{}` (empty object, not null/undefined), the `??` operator passes through the empty object. Phase 18 then reads `iter.tokens.total` as `undefined`.

**Why it happens:** `??` only triggers on `null`/`undefined`, not on empty objects.

**How to avoid:** The backend `normalizeTokens` guarantees all 6 fields are present with zero defaults when called at ingestion time. For hydration, use `iter.tokens ?? normalizeTokens(null)` — if the stored record has `tokens`, it was written by Phase 17 code and already has the full shape.

## Code Examples

### Complete _onIteration Extension
```js
// Source: app.js _onIteration handler
this._onIteration = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    if (!trace.iterations.has(payload.iteration_id)) {
        const toolCalls = reactive(new Map());
        trace.iterations.set(payload.iteration_id, {
            iteration_id: payload.iteration_id,
            trace_id: payload.trace_id,
            iteration_index: payload.iteration_index,
            has_error: !!payload.error,
            receivedAt: new Date(),
            expanded: true,
            toolCalls,
            messages_sent: payload.messages_sent || [],
            raw_response: payload.raw_response || null,
            is_final: payload.is_final || false,
            error: payload.error || null,
            // Phase 17: token/timing/provider fields
            tokens: normalizeTokens(payload.tokens),
            duration_ms: payload.duration_ms ?? 0,
            ai_provider: payload.provider ?? null,
        });
        this._lastArrivedId = payload.iteration_id;
        this._needsScroll = true;
    }
};
```

### serializeTrace Iteration Record Extension
```js
// Source: db.js serializeTrace, inside the .map() callback
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
    // Phase 17: token/timing/provider fields
    tokens: iter.tokens,
    duration_ms: iter.duration_ms,
    ai_provider: iter.ai_provider,
    // toolCalls: [...] unchanged
}
```

### hydrateTrace Iteration Backfill
```js
// Source: app.js hydrateTrace function, inside the for-loop
iterations.set(iterId, {
    ...iter,
    receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
    expanded: true,
    toolCalls,
    // Phase 17: zero-default for pre-17 IDB records
    tokens: iter.tokens ?? { input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0, total: 0 },
    duration_ms: iter.duration_ms ?? 0,
    ai_provider: iter.ai_provider ?? null,
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No token data in iteration objects | `iteration.tokens` + `iteration.duration_ms` + `iteration.ai_provider` | Phase 17 | Phase 18 can display metrics without any additional data fetching |
| IDB iteration records lack token fields | `serializeTrace` includes token/timing in iteration blob | Phase 17 | IDB round-trip preserves data transparently (no schema version change) |

## Open Questions

1. **SIDE-02 display scope conflict**
   - What we know: REQUIREMENTS.md maps SIDE-02 to Phase 17. SIDE-02 is "Sidebar token/time counters increment visually as new iteration events arrive (OWL reactive count-up)." The phase success criterion #3 says: "The sidebar token/time counters increment visually as each new iteration event arrives during a live run."
   - What's unclear: CONTEXT.md says "This phase handles data plumbing and persistence only — visual display components and formatting are Phase 18's concern." If counter display is purely Phase 18, then SIDE-02 cannot be verified until Phase 18 exists. But SIDE-02 is mapped to Phase 17.
   - Recommendation: The planner should clarify whether Phase 17 includes any sidebar display work or whether SIDE-02 is satisfied by the reactive store update (OWL re-renders Phase 18 display automatically when data changes). Given CONTEXT.md is the authoritative user decision, the most defensible interpretation is: Phase 17 stores reactive data (which makes SIDE-02 mechanically achievable), and Phase 18 adds the display elements that exercise it. Success criterion #3 may need to be deferred as a joint Phase 17+18 verification. The planner can add a minimal iteration-row token count to the existing sidebar (extending the duration display already in app.xml lines 144-150) as the simplest path to satisfying SIDE-02 in Phase 17 without requiring full Phase 18 display infrastructure.

2. **`getTraceTotals` naming and placement**
   - What we know: User said "Claude's Discretion" on exact getter naming. The computed getter should sum all iteration token fields.
   - What's unclear: Whether this method goes on `AiDebugApp` (callable from template as `this.getTraceTotals(trace)`) or as a module-level utility function.
   - Recommendation: Method on `AiDebugApp`, matching existing `getIterationDuration` / `getSelectedTrace` pattern. Name: `getTraceTotals(trace)`.

## Validation Architecture

> `nyquist_validation` key not present in `.planning/config.json` — skip this section.

## Sources

### Primary (HIGH confidence)
- Direct codebase inspection — `app.js`, `db.js`, `ai_session.py`, `ai_provider_patch.py` read in full
- `app.xml` — existing iteration row display pattern confirmed

### Secondary (MEDIUM confidence)
- OWL reactivity behavior (plain object in reactive Map, property mutation triggers re-render) — from existing working code patterns in app.js

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries; all existing
- Architecture: HIGH — all patterns are direct extrapolations of existing code
- Pitfalls: HIGH — identified from direct code inspection, not hypothetical

**Research date:** 2026-02-24
**Valid until:** 2026-03-24 (stable codebase; no external dependencies)
