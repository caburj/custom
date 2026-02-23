# Pitfalls Research

**Domain:** Adding subagent nesting, recursive trace linking, and color-coding to an existing OWL reactive Map store (ai_debug v1.4)
**Researched:** 2026-02-23
**Confidence:** HIGH (direct codebase inspection of current v1.3 implementation + OWL source-level reasoning + empirical IDB behavior)

This document supersedes the v1.3 PITFALLS.md for the purposes of v1.4 planning. V1.3 pitfalls are resolved and confirmed — see Sources. This document focuses exclusively on the new surface area: adding parent/child trace linking, restructuring the flat Map store for recursive nesting, flattening the 3-level tree to a flat+nested rendering model, persisting color assignments to IDB alongside trace data, handling bus event ordering, and hydrating nested trace relationships.

---

## Critical Pitfalls

### Pitfall 1: Child `new_trace` Bus Event Arrives Before Parent `tool_call` Event

**What goes wrong:**

Bus events are sent via separate database cursors (`registry.cursor()`) and committed independently. The parent agent's `tool_call` event is sent when `_handle_tool_calls` yields a result — but the subagent's `_run_agentic_loop` may emit its `new_trace` event before the parent's cursor has committed (depending on Postgres NOTIFY delivery timing and Python execution order). The JS event handler for `new_trace` looks up `payload.parent_tool_call_id` in the parent trace's tool call map — which doesn't exist yet. Without an out-of-order buffer, the subagent trace is silently dropped or inserted at root level.

**Why it happens:**

Two separate cursors commit independently. There is no ordering guarantee between a parent `tool_call` commit and a child `new_trace` commit on the bus channel. The Python execution order is: parent yields tool results → sends `tool_call` event → subagent `_run_agentic_loop` is called → sends `new_trace`. But NOTIFY processing on the Postgres side and WebSocket delivery can reorder these. Even a 1ms delivery delta causes the child to arrive first.

**How to avoid:**

Implement a pending-child buffer. When a `new_trace` event arrives with a `parent_tool_call_id` that is not yet in any trace's tool call map, add the child payload to a `Map<parent_tool_call_id, payload[]>` buffer. When a `tool_call` event arrives, after inserting the tool call, check the buffer for any pending children with that `tool_call_id` and process them in order. The buffer needs a TTL or a max size to prevent unbounded growth if a child event arrives for a tool call that is never seen (e.g., dropped `tool_call` event).

```javascript
// In setup():
this._pendingChildren = new Map(); // parent_tool_call_id → [payload, ...]

// In _onNewTrace:
if (payload.parent_tool_call_id) {
    const parentFound = this._attachChildTrace(payload);
    if (!parentFound) {
        // Buffer for later
        const pending = this._pendingChildren.get(payload.parent_tool_call_id) || [];
        pending.push(payload);
        this._pendingChildren.set(payload.parent_tool_call_id, pending);
    }
    return;
}
// Root trace: handle as before

// In _onToolCall, after inserting the tool call:
const waiting = this._pendingChildren.get(payload.tool_call_id);
if (waiting) {
    this._pendingChildren.delete(payload.tool_call_id);
    for (const child of waiting) this._attachChildTrace(child);
}
```

**Warning signs:**

- Subagent traces appear at root level in the sidebar (not nested under parent tool call)
- Console logs show "parent tool call not found" or equivalent for traces with `parent_tool_call_id`
- The pending buffer grows unboundedly (a `tool_call` event was dropped)

**Phase to address:** Phase 1 (backend events + JS event handlers) — buffer must exist before any subagent can trigger the race

---

### Pitfall 2: Nested Subagent Traces Stored in the Flat Top-Level Map Break the IDB Write

**What goes wrong:**

The current IDB write is triggered in `_onLoopEnd` per trace: `writeTrace(trace)` serializes the trace as a self-contained record keyed by `trace_id`. If subagent traces are stored as nested objects inside the parent trace (e.g., `parentTrace.children.set(childTraceId, childTrace)`), the IDB record for the parent trace grows unboundedly with each level of subagent nesting, and the structured clone cost per write multiplies. Worse: if both the parent and child have their own `_onLoopEnd` events, they will both try to write, and the child's write will serialize an object that's not a top-level trace record.

Alternatively, if subagent traces remain in the top-level `this.traces` Map (flat storage with `parent_tool_call_id` pointer), then `serializeTrace` must be updated to include the linkage fields — otherwise the relationship is lost on hydration.

**Why it happens:**

The natural first instinct is "nest child traces inside parent" to mirror the rendering hierarchy. But the current IDB schema is one record per `trace_id`. Nesting produces a schema mismatch with the write layer and the hydration layer.

**How to avoid:**

Keep subagent traces flat in `this.traces` (keyed by their own `trace_id`). Add linkage fields to each trace record: `parent_trace_id` and `parent_tool_call_id`. The rendering layer computes the tree from these pointers rather than from nested data structure. IDB stores each trace independently. Hydration reconstructs the parent–child relationship by linking after loading all records.

This is the same approach used by distributed tracing systems (OpenTelemetry span model) and is the correct design for a fire-and-forget IDB write pattern.

Update `serializeTrace` to include `parent_trace_id` and `parent_tool_call_id`. Update `hydrateTrace` to preserve them. No change to IDB schema version required if both fields are nullable.

**Warning signs:**

- `serializeTrace` does not include `parent_trace_id` or `parent_tool_call_id` fields
- Subagent traces are stored as properties of their parent trace object rather than as entries in `this.traces`
- After reload, subagent traces appear at root level even though they nested correctly in the live session

**Phase to address:** Phase 1 (data model design) and Phase 2 (IDB serialization) — decide flat vs. nested storage before writing any code

---

### Pitfall 3: `reactive()` Without a Render Observer Silently Breaks Nested Map Mutations

**What goes wrong:**

In OWL, `reactive(obj)` creates a proxy that notifies observers when properties are read/written. However, if `reactive()` is called without a callback argument (the second parameter), it uses OWL's `NO_CALLBACK` sentinel — meaning mutations are tracked but there is no observer to notify. Re-renders only happen when the mutation is observed through a `useState()` proxy chain.

When subagent traces are added to the flat `this.traces` Map (which IS a `useState`-wrapped Map), the traces themselves are reactive by association — OWL tracks reads through the proxy chain. But the subagent's `children` relationship is computed by iterating `this.traces.values()` and filtering on `parent_tool_call_id`. This is a computed derived view, not a stored reactive property. If the rendering template calls a method to build the tree (e.g., `getChildren(traceId)`), OWL tracks that call during render and re-renders when `this.traces` changes — which is correct.

The failure mode is when intermediate objects are created outside of a render cycle (e.g., in a `setup()` helper or a one-time computation) and stored as plain objects. Those objects are not in the proxy chain and mutations to them do not trigger renders.

**Why it happens:**

The pattern `reactive(new Map())` for `iterations` and `toolCalls` worked in v1.3 because those Maps were explicitly created inside `_onNewTrace` (inside a bus handler that's called during rendering or triggers a render via `useState`). If subagent nesting introduces a new level (e.g., `trace.childTraces = reactive(new Map())`), the new Map must be created with the same care — but developers may skip `reactive()` assuming the parent trace's proxy chain handles it.

**How to avoid:**

Use the same flat `this.traces` Map for all traces (root and subagent). Never add a `childTraces` or `children` property to a trace object. The tree is a view computed from the flat Map on every render. This avoids the nested-reactive problem entirely.

If a precomputed child index is needed for performance (many traces), store it in a `useState({})` plain object (not a Map), keyed by `parent_tool_call_id`. OWL tracks plain object property reads through `useState`, so mutations trigger renders correctly.

**Warning signs:**

- A `childTraces` or `children` property appears on trace objects
- `reactive(new Map())` called inside a function that's not a bus event handler or `setup()`
- Subagent trace additions don't trigger sidebar re-renders even though the data is in the store

**Phase to address:** Phase 1 (data model design) — decide the reactive structure before writing rendering code

---

### Pitfall 4: Flattening the 3-Level Tree to Flat+Nested Rendering Breaks Existing Selection Logic

**What goes wrong:**

The current sidebar renders a 3-level hierarchy: Loop > Iteration > Tool Call. The template iterates `trace.iterations` and within each iteration, `iteration.toolCalls`. Selection state (`selectedId`, `selectedType`) and ancestor highlighting (`selectedTraceId`, `selectedIterationId`) depend on this 3-level structure.

V1.4 flattens within-trace rendering (iterations and tool calls at the same level) and adds a new fourth dimension: subagent traces indented under the parent tool call. The existing `selectedTraceId` getter does a nested scan of all iterations to find which trace owns the selected iteration — this scan must now also descend into subagent traces.

If the selection getters are not updated, selecting an item inside a subagent trace returns `null` for `selectedTraceId` (because the scan only traverses root traces), breaking the ancestor-highlighting CSS classes and the detail panel "which agent's color accent to show."

**Why it happens:**

The existing getters `getSelectedIteration()`, `getSelectedToolCall()`, `selectedTraceId`, and `selectedIterationId` assume all traces are top-level entries in `this.traces`. Subagent traces are also in `this.traces` (flat model), so the getters will find them — but the ancestor walk for `selectedTraceId` when a `tool_call` is selected inside a subagent will return the subagent's `trace_id`, not the root agent's `trace_id`. This is technically correct but breaks the visual "which root loop owns this selection" expectation.

**How to avoid:**

When flattening the rendering tree, audit every selection getter and update it to work with the new flat+recursive model. Define clearly: does "selected trace" mean the immediate containing trace or the root-level trace? For color-coding and breadcrumbs, the immediate trace is correct. For checkbox selection, the root trace is correct (only root traces have checkboxes). Document this distinction.

Add a `getRootTraceId(traceId)` helper that walks `parent_trace_id` pointers up to the root. Use this consistently in all places that need "the root trace for a given selection."

**Warning signs:**

- Selecting an item inside a subagent trace causes the parent tool call highlight to disappear
- The detail panel shows no color accent or wrong color accent for subagent content
- Checkbox state becomes confused when subagent traces appear in the sidebar

**Phase to address:** Phase 3 (rendering flatten + nesting) — selection logic audit must be a required step when restructuring the template

---

### Pitfall 5: Color Assignment Stored in a Plain Object Inside `useState` Loses Reactivity on Color Map Growth

**What goes wrong:**

The per-agent color assignment (agent_name or trace_id → CSS color token) needs to be reactive: the first time an agent appears (new `new_trace` event), a color is assigned and the sidebar must re-render to show that color. The simplest storage is `this.agentColors = useState({})`, keyed by `agent_name`.

The problem: `useState({})` makes the top-level object reactive (its direct properties are tracked). Adding a new key (`this.agentColors[agentName] = 'color-3'`) triggers a re-render. But if the template reads `agentColors[trace.agent_name]` during render, OWL tracks that specific key access. A new agent name being added (new key) triggers a full re-render of the traces list — which is correct.

The failure mode is when colors are stored in a plain `Map` (not reactive): `this.agentColors = new Map()` without `useState` or `reactive()`. Map mutations are not observable by OWL. Adding a new color for a new agent does not trigger a render, so the new agent's sidebar row appears without its color until the next render triggered by something else (e.g., the next iteration event).

**Why it happens:**

The color assignment feels like "configuration state" rather than "UI data," so developers may store it in a module-level Map or a plain instance property rather than a reactive store.

**How to avoid:**

Store color assignments in `useState({})` (plain object, not Map). Keys are agent names (strings). Values are CSS class names or color tokens. The first time a `new_trace` event arrives for an agent not yet in the map, assign a color and add it to `this.agentColors`. This triggers a re-render that applies the color to the new trace row immediately.

Persist color assignments to IDB as a separate record (not embedded in trace records), keyed by a fixed key (e.g., `__agent_colors__`). Load from IDB in `onWillStart` before first render — same as trace hydration. This ensures color consistency across page refreshes.

**Warning signs:**

- `agentColors` is a plain `Map` or a plain instance property (not `useState`)
- New agent's first trace row appears without its color chip until the next render
- After page reload, all agents revert to color 1 (no persistence)

**Phase to address:** Phase 2 (color assignment + IDB persistence) — reactive storage and persistence design must be decided before implementing color assignment

---

### Pitfall 6: IDB DB Version Not Bumped When Adding `agentColors` Store — Upgrade Silently Fails

**What goes wrong:**

V1.3 opened IndexedDB at version 1 with a single `traces` store. V1.4 needs to persist color assignments (a separate logical record). If the color data is added to the existing `traces` store as a special record (e.g., keyed by `__agent_colors__`), no version bump is required. But if a new `agent_colors` object store is added, the IDB version must be bumped to 2 and `onupgradeneeded` must create the new store.

The current `db.js` uses `@web/core/utils/indexed_db` (Odoo's IDB wrapper), which uses `idb._tables.add(STORE)` to register stores. If a second store is registered without bumping the version, `onupgradeneeded` is not called (it only fires on version change), so the new store is never created. All writes to the new store fail with `NotFoundError: The operation failed because the requested database object could not be found`.

**Why it happens:**

Developers assume that adding `idb._tables.add('agent_colors')` is sufficient to create the store. It is only sufficient when the DB is being created for the first time (version 0 → 1). For an existing DB (already at version 1), adding to `_tables` without bumping the version means `onupgradeneeded` never fires and the store is never created.

**How to avoid:**

Two options:
1. **No version bump**: Store agent colors as a special sentinel record in the existing `traces` store (key `__agent_colors__`, value is the color map object). This avoids the schema migration entirely and is acceptable for a simple key-value payload.
2. **Version bump to 2**: Change `DB_VERSION = 2`, add `idb._tables.add('agent_colors')`. The `onupgradeneeded` handler (which Odoo's IDB util calls) creates the new store. Existing `traces` data is preserved.

Option 1 is simpler and recommended — it avoids a migration and keeps the IDB schema minimal.

**Warning signs:**

- `DB_VERSION` is still 1 but a new object store is being added
- `NotFoundError` in the console when writing to the new store
- Color assignments are lost on page reload (write silently failed)

**Phase to address:** Phase 2 (IDB persistence for colors) — decide the storage strategy before implementing

---

### Pitfall 7: Hydrating Nested Traces From IDB Requires a Two-Pass Load to Reconstruct Parent Pointers

**What goes wrong:**

On page load, `loadAllTraces()` returns all trace records from IDB. Currently, each record is independently hydrated with `hydrateTrace()` and inserted into `this.traces`. This works for flat traces.

With subagent nesting, some traces have `parent_trace_id` and `parent_tool_call_id`. For correct rendering, those pointer fields must reference traces that are ALSO in the store. But the IDB records are loaded in arbitrary order — there is no guarantee the parent trace record is processed before the child. If the rendering logic does a parent-pointer lookup during hydration (e.g., to validate linkage), it may not find the parent yet.

More subtly: after hydration, the pending-child buffer (from Pitfall 1) must be initialized empty — but the rendering template builds the tree by walking `parent_tool_call_id` pointers, not by looking up a buffer. So the ordering issue only affects the buffer, not rendering.

**Why it happens:**

IDB's `getAll()` returns records in key-path order (alphabetical by `trace_id` UUID strings, which are random — so effectively random order). If any hydration code does a parent lookup during the load loop, it will sometimes find the parent (already loaded) and sometimes not (not yet loaded).

**How to avoid:**

Do the hydration in two passes:
1. First pass: call `hydrateTrace()` on every record and insert into `this.traces`. No parent-linking logic.
2. Second pass: for every trace with `parent_trace_id`, verify the parent exists in `this.traces`. Log a warning if the parent is missing (orphaned trace — parent was deleted). No structural repair needed; the rendering template handles missing parents gracefully by rendering the orphan at root level.

The pending-child buffer (`_pendingChildren`) should be initialized empty and NOT pre-populated during hydration — it is only for in-flight live events. Hydrated traces are already complete records; there are no "pending" relationships to resolve.

**Warning signs:**

- Hydration loop does parent-pointer validation inline (single pass)
- `_pendingChildren` is populated during IDB hydration (should only be for live events)
- Subagent traces appear at root level after reload (parent pointer not being used in template)

**Phase to address:** Phase 2 (IDB hydration) — two-pass design must be explicit in the implementation plan

---

### Pitfall 8: Export Format Does Not Include `parent_trace_id` — Nesting Is Lost on Import

**What goes wrong:**

The current `serializeTrace()` function does not include `parent_trace_id` or `parent_tool_call_id` (they don't exist yet in v1.3). If these fields are added to trace objects in v1.4 but not added to `serializeTrace()`, the export file contains all the traces (both root and subagent) but with no parent linkage. When imported into a fresh session, all traces appear at root level — the hierarchy is gone.

**Why it happens:**

`serializeTrace()` explicitly lists every field it preserves (it's not a `{...trace}` spread — it's a manual field enumeration). Adding a new field to the trace object requires a matching addition to `serializeTrace()`. This is easy to forget because the export still works (no error), it just silently drops the relationship field.

**How to avoid:**

Add `parent_trace_id: trace.parent_trace_id || null` and `parent_tool_call_id: trace.parent_tool_call_id || null` to `serializeTrace()`. Add the same fields to the import validation: a trace with `parent_trace_id` but no matching trace in the import set is an orphan — log a warning but don't reject the import (the user may have exported a subset).

Update the import validator to also accept `parent_trace_id` as an optional string field. The import should reconstruct nesting after all traces are loaded (same two-pass approach as hydration).

**Warning signs:**

- `serializeTrace()` does not include `parent_trace_id` or `parent_tool_call_id`
- After export + import, all traces are flat (no nesting) even if they were nested in the original session
- Import validation rejects traces with `parent_trace_id` (unexpected field)

**Phase to address:** Phase 2 (IDB serialization) and Phase 4 (export/import) — `serializeTrace` must be updated in the same phase as the data model change

---

### Pitfall 9: Color Assignment Keyed by `agent_name` Collides When Two Different Agents Have the Same Name

**What goes wrong:**

The color assignment is intended to visually distinguish different agents. If the key is `agent_name` (a human-readable string like "Research Agent"), two completely different agent configurations with the same display name get the same color — which is correct by definition if the name is the identity key.

But if the user has two agents with the same name in different Odoo configurations, or if an agent's name changes between runs, the color assignment becomes confusing: a "new" agent gets the color of an old one, or two unrelated agents share a color.

The deeper problem: what is the correct identity key? `agent_name` (human-readable, collides), `agent_id` (database ID, stable across name changes), or `trace_id` (unique but gives every trace a different color, making comparison impossible)?

**Why it happens:**

The first implementation reaches for `agent_name` because it's what the user sees and expects to map to a color. The collision case isn't obvious until two same-named agents appear in the same session.

**How to avoid:**

Use `agent_name` as the color key. The collision is intentional: if two agents share a name, they share a color (the user probably treats them as equivalent). Document this decision explicitly. If `agent_id` is available in the bus payload, prefer it as the key (more stable than name).

Per the PROJECT.md, `agent_name` is already available in `new_trace` payloads. Check whether `agent_id` (database record ID) is also available — if so, use it and display `agent_name` as the label.

**Warning signs:**

- Color assignment keyed by `trace_id` (every trace gets a unique color — defeats the purpose)
- No documentation of what the identity key means
- Two agents with the same name display different colors (key is more granular than `agent_name`)

**Phase to address:** Phase 2 (color assignment design) — decide the identity key before implementing

---

### Pitfall 10: Rendering Subagent Nesting With Recursive OWL Components Causes Double-Render Cascades

**What goes wrong:**

The natural approach to rendering a recursive tree is a recursive OWL component: `<TraceRow>` renders itself for each child trace. But OWL renders components depth-first. If a subagent trace's data arrives via a bus event while the parent is being re-rendered (a common pattern during fast loops), the component mount/patch lifecycle for the recursive child may fire during the parent's patch cycle. This is not a correctness problem (OWL queues patches), but it can cause visual flicker — the parent renders without the child, then the child renders, producing two visible updates in rapid succession.

The more significant problem is with `t-key` assignment. The current template uses `traceId` as the key for trace rows. If a subagent trace is rendered inside the parent trace's subtree (as a child of a tool call row), its `t-key` must be globally unique to prevent OWL from reusing the wrong DOM node. Using just `traceId` inside a nested `t-foreach` could cause key collisions if the same `traceId` appears at multiple rendering levels (which it won't in this model, but is worth documenting).

**Why it happens:**

Recursive OWL components are uncommon in Odoo codebases. The pattern is supported (OWL is a full component framework) but requires explicit attention to lifecycle ordering. Developers may use a flat template loop with indentation via CSS margin instead of a recursive component — this is actually the correct approach for the ai_debug use case, since the nesting is bounded (not truly unbounded-recursive in practice).

**How to avoid:**

Do NOT use recursive OWL components. Instead, flatten the render loop: after each root trace's rows, check if any subagent traces reference a tool call in that trace, and render those subagent rows immediately after (with CSS indentation). This is a depth-first iterative walk, not a recursive component tree. It keeps the rendering logic in a single template, avoids component lifecycle complexity, and is consistent with how the v1.3 template already works (flat `t-foreach` loops with conditional expansion).

```xml
<!-- Pseudocode: flat iterative rendering with depth-aware indentation -->
<t t-foreach="orderedTraceIds" t-as="traceId" t-key="traceId">
    <!-- render trace row with depth-dependent indent class -->
    <!-- then recurse via a helper that yields child trace IDs in order -->
</t>
```

**Warning signs:**

- A recursive OWL component (`TraceRow` that renders `<TraceRow>` inside itself) is being introduced
- Double-render flicker on fast bus events (parent re-renders, then child re-renders separately)
- Template has nested `t-foreach` loops with the same key variable name at different depths

**Phase to address:** Phase 3 (rendering restructure) — decide flat-iterative vs. recursive-component before writing any template code

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip the pending-child buffer (assume events arrive in order) | Simpler bus handlers | Subagent traces silently dropped or misplaced under race conditions | Never — race is real, buffer is cheap |
| Nest subagent traces inside parent trace objects | Mirrors visual hierarchy | IDB write complexity multiplies; structured clone on large parent; selection logic breaks | Never — flat model is correct |
| Key agentColors by `trace_id` instead of `agent_name` | No collision risk | Each trace gets a unique color; color-coding loses its purpose | Never |
| Recursive OWL component for tree rendering | Elegant code | Double-render cascades; t-key complexity; lifecycle ordering bugs | Never for this use case |
| Store colors embedded in trace records | No new IDB key | Colors change when any trace is updated (incorrect coupling) | Never — colors are orthogonal to traces |
| Single-pass hydration with inline parent validation | Simpler code | Occasionally fails when child record is processed before parent | Never — two-pass is the correct approach |
| Skip bumping DB version when adding agent_colors to sentinel key in traces store | No migration needed | Acceptable — sentinel key approach does not require version bump | Acceptable only for the sentinel key approach |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Bus events + subagent ordering | Assume `tool_call` always arrives before child `new_trace` | Buffer pending children; check buffer on every `tool_call` arrival |
| OWL reactive Map + computed tree view | Store parent-child relationships in nested Map properties | Store in flat Map; compute tree from `parent_tool_call_id` pointers at render time |
| IDB + subagent fields | Forget to add `parent_trace_id` to `serializeTrace()` | Audit `serializeTrace()` and `hydrateTrace()` together when adding any new field |
| IDB + color store | Bump DB version without migration code | Use sentinel key in existing store, or bump version with proper `onupgradeneeded` |
| IDB hydration + parent pointers | Single-pass with inline parent lookup (sometimes fails) | Two-pass: load all traces first, then validate/link parent pointers |
| Export + nesting | Export traces without parent linkage fields | Always include `parent_trace_id` and `parent_tool_call_id` in serialization |
| OWL template + recursive tree | Recursive component for subagent nesting | Flat iterative render with CSS indentation; depth computed from pointer walk |
| Color assignment + identity | Key by `trace_id` (too granular) or `agent_id` (may not be in payload) | Key by `agent_name`; document the collision semantics |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Computing the full tree on every render (no memoization) | Render time scales with total number of traces × nesting depth | Use a precomputed `childIndex` map in state; update only on `new_trace` events | When >50 total traces (root + subagent) are in the store |
| Pending-child buffer grows unboundedly | Memory increases monotonically during multi-agent session | Add a buffer size cap (100 entries) and TTL (clear entries older than 30s) | During sessions where `tool_call` events are dropped |
| Walking all traces for `getSelectedTrace()` and `getRootTraceId()` during render | Getter called per render, scans all traces | Cache the root-trace lookup when selection changes, not per-render | When trace count exceeds ~200 |
| Serializing nested subagent hierarchy in `serializeTrace()` | Structured clone includes child trace data duplicated in parent | Keep flat model; parent record only stores `parent_trace_id` pointer, not child data | When nesting depth exceeds 3 levels |

---

## "Looks Done But Isn't" Checklist

- [ ] **Race condition handled:** Trigger a subagent that emits `new_trace` before parent emits `tool_call`; verify the child trace appears nested correctly, not at root level
- [ ] **Color persists across refresh:** Assign colors to 3 agents, reload the page, verify the same agents get the same colors
- [ ] **Color not in trace record:** Inspect IDB trace records directly; confirm no `agent_color` field on trace objects (colors are stored separately)
- [ ] **Subagent nesting survives IDB roundtrip:** Run a nested session, reload the page, verify subagent traces are still nested under the correct parent tool call
- [ ] **Export preserves nesting:** Export a session with subagent traces, import into a fresh session, verify the hierarchy is intact
- [ ] **`serializeTrace` includes linkage fields:** Inspect exported JSON; confirm `parent_trace_id` and `parent_tool_call_id` are present on subagent trace records
- [ ] **Selection works inside subagent traces:** Select a tool call inside a 2-deep subagent trace; verify the detail panel shows correct data and the correct ancestor rows are highlighted
- [ ] **Pending-child buffer is cleared:** After a session ends, verify `_pendingChildren.size === 0` (no orphaned pending children from dropped events)
- [ ] **Flat rendering: no recursive components:** Inspect the component tree in OWL devtools; confirm only one level of `AiDebugApp` exists (no `TraceRow` inside `TraceRow`)
- [ ] **Orphaned subagent traces render gracefully:** Manually delete a parent trace from IDB while leaving a child trace; reload and verify the child renders at root level without errors

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Child arrives before parent (no buffer) | MEDIUM | Add `_pendingChildren` buffer to `setup()`; update `_onToolCall` to drain buffer after insert; retest ordering scenarios |
| Subagent traces nested in parent objects | HIGH | Refactor data model to flat Map; update all selection getters, serialization, and rendering — major refactor if nesting is deep in the codebase |
| Color stored in trace record | LOW | Extract color to separate `agentColors` state; update serialization to exclude color from trace records |
| IDB version not bumped for new store | LOW | Bump `DB_VERSION`; add `idb._tables.add()` for new store; existing traces are preserved |
| Export missing parent linkage fields | LOW | Add fields to `serializeTrace()`; existing IDB records need re-write (trigger via next `loop_end`) |
| Single-pass hydration breaks | LOW | Add second pass after load loop; validate parent pointers with warnings for orphans |
| Recursive component double-render | MEDIUM | Replace recursive component with flat iterative template loop; update all CSS indentation logic |
| Color key too granular (per-trace) | LOW | Change key from `trace_id` to `agent_name`; wipe existing color assignments and re-assign |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Child `new_trace` before parent `tool_call` | Phase 1: Bus event handlers | Manual test with artificial delay on parent `tool_call` send |
| Subagent traces nested in parent objects | Phase 1: Data model design | Code review: `this.traces` is the only store; no `.children` property on traces |
| `reactive()` without render observer | Phase 1: Data model design | OWL devtools shows renders firing when any child trace is added |
| Selection logic breaks with flat+nested rendering | Phase 3: Template restructure | Select tool call inside level-2 subagent; ancestor highlight is correct |
| Color assignment not reactive | Phase 2: Color assignment | New agent's first trace row shows color immediately without a second event |
| IDB version not bumped | Phase 2: IDB persistence for colors | No `NotFoundError` in console; colors survive reload |
| Two-pass hydration for parent pointers | Phase 2: IDB hydration | Reload after subagent session; nesting is intact |
| Export missing linkage fields | Phase 2: Serialization + Phase 4: Export | Exported JSON contains `parent_trace_id`; import restores nesting |
| Color collision semantics undocumented | Phase 2: Color assignment | Code comment explains key choice; behavior is intentional |
| Recursive component double-render | Phase 3: Template restructure | OWL devtools shows single render cycle per bus event; no flicker |

---

## Sources

- Direct codebase inspection: `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — current flat `this.traces` Map, `hydrateTrace()`, `serializeTrace()` in `db.js`, bus event handler structure
- OWL reactive model: `reactive()` without callback uses `NO_CALLBACK` sentinel — mutations tracked but no observer notification; `useState()` wraps the Map so OWL's render function observes mutations — confirmed from PROJECT.md "Key Decisions" table and OWL source
- IDB `onupgradeneeded` semantics: fires only on version change, not on `_tables.add()` — confirmed from v1.3 PITFALLS.md Pitfall 9 and MDN IndexedDB documentation
- Bus event ordering: separate `registry.cursor()` per event means NOTIFY is committed independently per event; no ordering guarantee between two separate cursors — confirmed from `ai_session.py` `_ai_debug_bus_send()` implementation
- OpenTelemetry span model: flat span storage with parent pointer is the standard distributed tracing pattern — used as the reference model for the flat `parent_trace_id` approach
- PROJECT.md v1.4 requirements: "subagent traces indent under the parent tool call, with arbitrary nesting depth"; "per-agent color assignment on first appearance, persisted to IDB" — requirements as stated
- v1.3 PITFALLS.md (superseded): IDB write patterns, `hydrateTrace()` reactive reconstruction, `onWillStart` vs `onMounted` — all confirmed resolved in the current codebase

---
*Pitfalls research for: Odoo AI Debugger v1.4 — Subagent nesting, recursive trace linking, color-coding*
*Researched: 2026-02-23*
