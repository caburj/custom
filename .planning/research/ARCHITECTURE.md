# Architecture Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched:** 2026-02-23 (v1.4 section added); 2026-02-22 (v1.3 and earlier)
**Confidence:** HIGH (all findings derived from direct source reading)

---

# v1.4 Subagent Support Architecture

> This section answers the research questions for the v1.4 milestone: Where in ai_session.py instrumentation should parent trace linkage be captured? How should the reactive store be restructured? How should the sidebar components be refactored for flat + nested rendering? What IDB schema changes are needed?

## The Four Integration Questions

### Q1: Where in ai_session.py to Capture Parent Trace Linkage

**The call chain that creates a subagent:**

```
parent ai.session._run_agentic_loop()        [ai_debug override emits new_trace(A)]
  → super()._run_agentic_loop()
      → _handle_tool_calls()
          → tool._ai_tool_run()
              → agent._ai_tool_request_sub_agent()
                  → child ai.session._generate_next_response()
                      → child._run_agentic_loop()   [ai_debug override runs on child]
                              → emits new_trace(B)   [currently no parent linkage]
```

**Key facts from source reading:**

1. `_ai_tool_request_sub_agent` (in `enterprise/ai/models/ai_agent.py` line 1339) creates a new `ai.session` with `parent_session_id` set. The child session object is created via `self.env["ai.session"].sudo().create(...)` — this inherits the calling env's context.

2. The tool name for the subagent tool follows the pattern `make_tool_name(tool)` = `"ai_request_subagent_{id}"`. The upstream `_handle_tool_calls` already uses this pattern: `if "ai_request_subagent" in tool_call.get("name", "")` (line 221 of enterprise ai_session.py).

3. `parent_session_id` is a model field on `ai.session` — it tells us which session is the parent, but NOT which runtime `trace_id` (a UUID generated only at instrumentation time, not stored in DB) or which `tool_call_id` spawned us.

4. The `_debug_ctx` dict (which carries `trace_id`, `iteration_id`, `tool_call_count`) is threaded via `env.context` in the parent. Child sessions have their own `env`, so `_debug_ctx` is not automatically available to them.

**Solution: Thread parent trace linkage through `env.context` before the subagent tool call.**

In `_handle_tool_calls`, scan `tool_calls` before calling `super()`. If any tool call targets the subagent tool, inject parent linkage into `self`'s context using `self.with_context()`. Because `env.context` propagates through ORM recordset creation (`.create()`, `.sudo()`, `.with_company()`), the child session's env will carry the injected keys when `_run_agentic_loop` is called on it.

```python
# In ai_debug/models/ai_session.py — _handle_tool_calls override:
# Before the super() call:
for tc in tool_calls:
    if "ai_request_subagent" in tc.get("name", ""):
        reserved_tc_id = uuid.uuid4().hex
        _debug_ctx['reserved_subagent_tc_id'] = reserved_tc_id
        self = self.with_context(
            _ai_debug_parent_trace_id=_debug_ctx['trace_id'],
            _ai_debug_parent_tool_call_id=reserved_tc_id,
        )
        break  # one subagent tool call per batch in practice

for item in super()._handle_tool_calls(...):  # self already carries context
    ...
```

Then in `_run_agentic_loop` on the child:

```python
parent_trace_id = self.env.context.get('_ai_debug_parent_trace_id')   # None for root
parent_tool_call_id = self.env.context.get('_ai_debug_parent_tool_call_id')  # None for root

self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'parent_trace_id': parent_trace_id,        # NEW — null for root
    'parent_tool_call_id': parent_tool_call_id, # NEW — null for root
    ...
})
```

**Why `reserved_tc_id` in `_debug_ctx`:** The `tool_call_id` emitted in the subsequent `tool_call` bus event must match the `parent_tool_call_id` the child reports. Generate it once before `super()`, store it in `_debug_ctx['reserved_subagent_tc_id']`, and use it when emitting the `tool_call` event for the subagent tool. This ensures parent and child refer to the same identifier.

**Compatibility:** The separate-cursor `_ai_debug_bus_send` creates a new env from `self.env.registry.cursor()`. This env does NOT carry context — but bus sends only write to `bus_bus`, they don't need parent linkage. No issue.

**Backward compatibility:** `parent_trace_id` and `parent_tool_call_id` are absent from events emitted by existing non-subagent sessions. The JS handlers default these to `null` when missing.

### Q2: Reactive Store — Flat Map with Parent Pointers (NOT Nested Map)

**Options analyzed:**

**Option A: Nested Map** — child traces stored as nested objects inside the parent trace or inside the spawning tool call.

Rejected because:
- Breaks every existing lookup: `getSelectedTrace`, `getSelectedIteration`, `getSelectedToolCall` all assume flat `traces.get(id)`.
- Breaks `deleteCheckedTraces` (iterates top-level traces only).
- Breaks `exportSelected` / `serializeTrace` / `hydrateTrace`.
- Makes color assignment (by agent name across all traces) require recursive traversal.
- Violates the existing IDB decision: "one denormalized record per trace."

**Option B: Flat Map with parent pointers** — keep `traces` flat. Each subagent trace carries `parent_trace_id` and `parent_tool_call_id`. The display hierarchy is derived at render time from these pointers.

Chosen because:
- Zero changes to any existing lookup functions.
- IDB schema change is additive: two new nullable fields.
- Bulk delete, export, import, color assignment all work unchanged.
- Rendering hierarchy is computed once per render in `sidebarNodes` getter.

**Concrete store changes — only additive:**

```javascript
// _onNewTrace handler adds two nullable fields:
this.traces.set(payload.trace_id, {
    trace_id: payload.trace_id,
    parent_trace_id: payload.parent_trace_id || null,       // NEW
    parent_tool_call_id: payload.parent_tool_call_id || null, // NEW
    agent_name: payload.agent_name || "Unknown Agent",
    agent_color: null,   // NEW — assigned by _assignAgentColor()
    ...existing fields unchanged...
});
// After set: assign color
this._assignAgentColor(payload.agent_name, payload.trace_id);
```

**Color assignment:** Add `this.agentColors = useState(new Map())` as a second reactive Map. The `_assignAgentColor(agentName, traceId)` method:
1. Checks `this.agentColors.has(agentName)`
2. If not, picks next color from a fixed palette array (cycling), writes to `agentColors`, and persists to IDB
3. Sets `trace.agent_color = this.agentColors.get(agentName)` on the just-inserted trace object

The trace object itself holds `agent_color` for direct template access without a second Map lookup in the render path.

### Q3: Sidebar — Computed Display List, Not Template Recursion

**Why not nested `t-foreach`:** OWL templates cannot call themselves recursively. Achieving arbitrary nesting depth with static template nesting requires knowing the maximum depth at write time. The v1.4 spec says "arbitrary nesting depth."

**Why not template-level conditional for subagent nesting:** Would require complex conditional logic (check if a tool call has a child trace, render it inline, check if that child trace's tool calls have grandchildren, etc.) that belongs in JavaScript, not XML.

**Solution: `sidebarNodes` computed getter** that produces a flat, ordered array of display node objects. The template iterates this single array with one `t-foreach`.

```javascript
get sidebarNodes() {
    const nodes = [];
    // Root traces: no parent, newest first
    const rootTraces = [...this.traces.values()]
        .filter(t => !t.parent_trace_id)
        .sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0));

    const renderTrace = (trace, depth) => {
        nodes.push({
            type: 'trace',
            id: trace.trace_id,
            depth,
            data: trace,
        });
        if (!trace.expanded) return;

        // Flat within-trace: iterations and tool calls interleaved
        for (const [iterationId, iter] of trace.iterations) {
            nodes.push({
                type: 'iteration',
                id: iterationId,
                depth: depth + 1,
                data: iter,
                traceId: trace.trace_id,
            });
            // Tool calls immediately after their iteration (always shown when trace expanded)
            for (const [tcId, tc] of iter.toolCalls) {
                nodes.push({
                    type: 'tool_call',
                    id: tcId,
                    depth: depth + 1,
                    data: tc,
                    traceId: trace.trace_id,
                });
                // Subagent traces under this tool call — recursive
                const children = [...this.traces.values()]
                    .filter(t => t.parent_tool_call_id === tcId);
                for (const child of children) {
                    renderTrace(child, depth + 2);
                }
            }
        }
    };

    for (const trace of rootTraces) {
        renderTrace(trace, 0);
    }
    return nodes;
};
```

**OWL reactivity:** This getter reads from `this.traces` (a `useState(new Map())` proxy), `trace.iterations` (a `reactive(new Map())`), and `iter.toolCalls` (a `reactive(new Map())`). OWL's reactive proxy records every `.values()`, `.has()`, `.get()` access during render. When any of those Maps mutate, OWL triggers a re-render which re-evaluates the getter. This is identical to how the current template works — the getter merely moves the traversal from XML to JS.

**Template becomes a single `t-foreach` over `sidebarNodes`:**

```xml
<t t-foreach="sidebarNodes" t-as="node" t-key="node.id">
    <!-- depth-based indentation via CSS custom property -->
    <div t-attf-class="ai-tree-row node-{{node.type}}"
         t-attf-style="padding-left: calc({{node.depth}} * 12px + 8px)"
         t-att-class="{
             'selected': state.selectedId === node.id,
             'ancestor': isAncestorOf(node.id)
         }"
         t-att-data-node-id="node.id">
        <!-- color swatch for trace nodes (agent identity) -->
        <span t-if="node.type === 'trace' and node.data.agent_color"
              class="ai-agent-color-swatch"
              t-attf-style="background: {{node.data.agent_color}}"/>
        <!-- ... existing label/status/chevron rendering switched on node.type ... -->
    </div>
</t>
```

**The `iteration.expanded` toggle is removed.** In v1.4's flat layout, tool calls are always visible when the parent trace is expanded (they are at the same depth level as iterations, not nested under them). The `expanded` flag on iterations becomes unused. Remove the expand chevron from iteration rows and the `toggleExpand(traceId, iterationId)` call path.

**`isAncestorOf(nodeId)` helper:** Replaces the current `selectedTraceId` and `selectedIterationId` getters. Given a `nodeId`, returns true if that node is an ancestor of the currently selected node. Needed to apply the `.ancestor` CSS class for breadcrumb tinting.

### Q4: IDB Schema Changes

**No DB_VERSION bump required** for the trace store — changes are additive nullable fields.

**Changes to `serializeTrace` (add three fields):**

```javascript
export function serializeTrace(trace) {
    return {
        ...existing fields...,
        parent_trace_id: trace.parent_trace_id || null,        // NEW
        parent_tool_call_id: trace.parent_tool_call_id || null, // NEW
        agent_color: trace.agent_color || null,                // NEW
    };
}
```

**Changes to `hydrateTrace` (default new fields from null):**

```javascript
function hydrateTrace(plain) {
    return {
        ...plain,
        parent_trace_id: plain.parent_trace_id || null,        // NEW — old records → null
        parent_tool_call_id: plain.parent_tool_call_id || null, // NEW — old records → null
        agent_color: plain.agent_color || null,                // NEW — old records → null
        ...existing reconstructions (dates, reactive Maps)...
    };
}
```

**New `agent_colors` IDB object store:**

```javascript
const COLORS_STORE = "agent_colors";
idb._tables.add(COLORS_STORE);  // add alongside existing STORE = "traces"

export function writeAgentColor(agentName, color) {
    return idb.write(COLORS_STORE, agentName, {
        name: agentName,
        color,
        assignedAt: Date.now(),
    });
}

export async function loadAllAgentColors() {
    return idb.execute((db) => {
        if (!db || !db.objectStoreNames.contains(COLORS_STORE)) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(COLORS_STORE, "readonly");
            const req = tx.objectStore(COLORS_STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
```

**DB_VERSION caveat:** Adding `idb._tables.add(COLORS_STORE)` before the first `idb.execute()` call will cause the Odoo `IndexedDB` utility to create the store in `onupgradeneeded` only if the DB is being created fresh. On an existing DB at version 1, `onupgradeneeded` does not fire unless the version is bumped. If the `agent_colors` store is not created on existing DBs, increment `DB_VERSION = 2`. The `IndexedDB` utility from `@web/core/utils/indexed_db` handles multi-store upgrades — verify empirically whether `_tables.add()` is sufficient or if a version bump is needed.

**Hydration sequence change in `onWillStart`:**

```javascript
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) { this.state.ephemeralMode = true; return; }

    // NEW: load agent colors before traces (traces reference colors on hydration)
    const storedColors = await loadAllAgentColors();
    for (const { name, color } of storedColors) {
        this.agentColors.set(name, color);
    }

    // Existing: load traces
    const stored = await loadAllTraces();
    stored.sort(...);
    for (const plain of stored) {
        const hydrated = hydrateTrace(plain);
        // Assign color from loaded agentColors Map (or allocate new one)
        if (!hydrated.agent_color && hydrated.agent_name) {
            hydrated.agent_color = this._getOrAssignColor(hydrated.agent_name);
        }
        this.traces.set(plain.trace_id, hydrated);
    }
    ...
});
```

---

## System Overview (v1.4)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Python (Odoo Backend)                          │
│                                                                        │
│  ai_debug/models/ai_session.py  (_inherit = 'ai.session')            │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  _run_agentic_loop()                                          │    │
│  │  ├── reads context: _ai_debug_parent_trace_id [v1.4 NEW]     │    │
│  │  ├── reads context: _ai_debug_parent_tool_call_id [v1.4 NEW] │    │
│  │  └── emits new_trace with parent fields (null for root)       │    │
│  │                                                                │    │
│  │  _handle_tool_calls()                                         │    │
│  │  ├── scans tool_calls for "ai_request_subagent" [v1.4 NEW]   │    │
│  │  ├── self = self.with_context(_ai_debug_parent_*) [v1.4 NEW] │    │
│  │  └── emits tool_call with reserved_tc_id [v1.4 MOD]          │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                    │ bus.bus (separate cursor, immediate NOTIFY)       │
└────────────────────┼─────────────────────────────────────────────────┘
                     │ WebSocket (bus_service)
┌────────────────────▼─────────────────────────────────────────────────┐
│                        JavaScript (OWL App)                           │
│                                                                        │
│  this.traces = useState(new Map())    [flat — key: trace_id]          │
│  this.agentColors = useState(new Map()) [key: agent_name] [v1.4 NEW] │
│                                                                        │
│  _onNewTrace:  traces.set(id, {..., parent_trace_id, agent_color})    │
│  _onIteration: trace.iterations.set(iterId, {...})                    │
│  _onToolCall:  iter.toolCalls.set(tcId, {...})                        │
│  _onLoopEnd:   trace.status = ...; writeTrace(trace)  [IDB]           │
│                                                                        │
│  get sidebarNodes() [v1.4 NEW]                                        │
│  ├── filter root traces (parent_trace_id === null)                    │
│  ├── renderTrace(trace, depth=0) → recursive                          │
│  │   ├── push trace node                                              │
│  │   ├── for each iteration: push iteration node (depth+1)            │
│  │   │   └── for each toolCall: push tool_call node (depth+1)         │
│  │   │       └── for child traces: renderTrace(child, depth+2)        │
│  │   └── return flat ordered array                                    │
│  └── template: t-foreach sidebarNodes → depth-based padding-left     │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  IndexedDB (db.js)                                               │  │
│  │  ├── "traces" store  — serializeTrace adds parent + color fields │  │
│  │  └── "agent_colors" store  — key: agent_name, value: hex color   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## New vs Modified Components

| Component | Status | What changes |
|-----------|--------|--------------|
| `ai_debug/models/ai_session.py` | MODIFIED | `_handle_tool_calls`: detect subagent tool, inject context, use `reserved_subagent_tc_id`; `_run_agentic_loop`: read and emit parent fields |
| `app.js` | MODIFIED | Add `agentColors` Map; add `_assignAgentColor`; add `sidebarNodes` getter; update `_onNewTrace` for parent fields + color; update `onWillStart` to load colors; update `hydrateTrace` |
| `app.xml` | MODIFIED | Replace 3-level nested `t-foreach` with single `t-foreach` over `sidebarNodes`; depth-based `padding-left`; color swatch element; remove `iteration.expanded` toggle |
| `db.js` | MODIFIED | `serializeTrace` adds 3 fields; `hydrateTrace` handles new fields; add `COLORS_STORE`, `writeAgentColor`, `loadAllAgentColors` |
| `app.scss` | MODIFIED | Add `.ai-agent-color-swatch` styling; CSS custom property for depth indentation |

**No new files are required for v1.4.**

---

## Build Order (Dependency-Aware)

```
Step 1 — Python instrumentation (independent starting point)
  Files: ai_debug/models/ai_session.py
  Change: detect subagent tool in _handle_tool_calls, inject context,
          read parent fields in _run_agentic_loop, emit in new_trace
  Validates: bus events for subagent sessions carry parent_trace_id + parent_tool_call_id
  Validates: reserved_tc_id in tool_call event matches parent_tool_call_id in child new_trace

Step 2 — IDB schema (parallel with step 1; depends only on existing db.js)
  Files: db.js
  Change: add parent fields to serializeTrace + hydrateTrace;
          add COLORS_STORE, writeAgentColor, loadAllAgentColors
  Validates: write → read round-trip preserves parent_trace_id, parent_tool_call_id, agent_color
  Validates: agent_colors store is created and persists colors across reload

Step 3 — JS store + color assignment (depends on step 1 for live data, step 2 for IDB)
  Files: app.js
  Change: add agentColors Map; add _assignAgentColor + _getOrAssignColor;
          update _onNewTrace to store parent fields + call color assignment;
          update onWillStart to load colors before traces;
          update hydrateTrace wrapper to default new fields
  Validates: traces.get(id).parent_trace_id is set correctly for subagent traces
  Validates: traces.get(id).agent_color is assigned for each distinct agent_name

Step 4 — sidebarNodes getter (depends on step 3 for parent fields being in store)
  Files: app.js (add sidebarNodes getter)
  Change: implement sidebarNodes with renderTrace recursive helper
  Validates: getter returns correct ordered flat array
  Validates: subagent traces appear after the tool call that spawned them

Step 5 — template refactor (depends on step 4 for sidebarNodes API)
  Files: app.xml
  Change: replace nested t-foreach with t-foreach over sidebarNodes;
          add depth-based padding-left; add color swatch; remove iteration expand toggle
  Validates: sidebar renders root traces at depth 0, iterations/tool-calls at depth 1,
             subagent traces at depth 2, grandchildren at depth 4, etc.
  Validates: color swatch visible for subagent traces; absent for root (or all, depending on design)

Step 6 — SCSS (depends on step 5 for element classes)
  Files: app.scss
  Change: add .ai-agent-color-swatch (small circle, inline-block, fixed size);
          add CSS custom property --ai-depth-indent if using variable indentation
  Validates: visual color accent renders correctly in both light and dark themes
```

Steps 1 and 2 are fully parallel — neither depends on the other.

---

## Anti-Patterns

### Anti-Pattern 1: Nested Map for Subagent Traces

**What people might do:** Store child traces as nested objects inside the parent trace's tool call.

**Why it's wrong:** Breaks `getSelectedTrace(id)`, `deleteCheckedTraces()`, `exportSelected()`, `serializeTrace()`, `hydrateTrace()`, and the import validation — all of which assume `traces` is a flat Map keyed by `trace_id`.

**Do this instead:** Keep `traces` flat. Add `parent_trace_id` and `parent_tool_call_id` pointer fields. Derive display hierarchy in the `sidebarNodes` getter.

### Anti-Pattern 2: Template-Level Recursive Rendering

**What people might do:** Use nested `t-foreach` in app.xml to recursively render subagent traces inside tool call rows.

**Why it's wrong:** OWL templates are static — no template recursion is possible. Static nesting only works for a fixed maximum depth. The v1.4 spec requires arbitrary nesting depth.

**Do this instead:** Compute the ordered flat node list in a JavaScript getter (`sidebarNodes`). The template iterates one flat array. Depth is a field on each node object, applied as CSS `padding-left`.

### Anti-Pattern 3: Context Injection After super() Call

**What people might do:** Try to inject `_ai_debug_parent_trace_id` into context in `_handle_tool_calls` after the `super()` generator has already yielded and the child session has already been created.

**Why it's wrong:** The child session is created during `super()._handle_tool_calls()` execution. By the time the ai_debug wrapper processes `tool_results` from `super()`, the child's `_run_agentic_loop` has already emitted its `new_trace` event — without the parent linkage.

**Do this instead:** Set context on `self` before the `super()` call. Scan `tool_calls` upfront to detect subagent calls and pre-inject the context. This ensures the context is available when the child session is created inside the generator chain.

### Anti-Pattern 4: Using `iteration.expanded` to Gate Tool Call Visibility

**What people might do:** Keep the existing `iteration.expanded` flag to toggle tool call visibility in the new flat layout.

**Why it's wrong:** In the v1.4 flat layout, tool calls appear at the same depth level as iterations. The original three-level hierarchy (trace > iteration > tool calls nested under iteration) is replaced by a two-level flat list within a trace. The `expanded` concept at the iteration level no longer applies.

**Do this instead:** Remove `iteration.expanded`. When a trace is expanded (`trace.expanded = true`), ALL its iterations and tool calls are visible. Only the trace-level expand/collapse remains.

---

## Sources

- Direct source read: `ai_debug/models/ai_session.py` (full instrumentation code — all methods)
- Direct source read: `ai_debug/static/src/app/app.js` (reactive store, bus handlers, hydration, full 627 lines)
- Direct source read: `ai_debug/static/src/app/app.xml` (sidebar template — all 201 lines)
- Direct source read: `ai_debug/static/src/app/db.js` (IDB schema and operations — all 143 lines)
- Direct source read: `enterprise/ai/models/ai_session.py` (upstream agentic loop, `_handle_tool_calls` subagent forward, `parent_session_id` field)
- Direct source read: `enterprise/ai/models/ai_agent.py` (`_ai_tool_request_sub_agent`, `agent_ids` M2M, `_get_tools` includes subagent tool conditionally)
- Direct source read: `enterprise/ai/models/ir_actions_server.py` (`_ai_tool_run`, tool name pattern detection)
- Direct source read: `enterprise/ai/data/ir_actions_server_data.xml` (tool XML id `ir_actions_server_request_sub_agent`, name "AI: Request Sub-Agent", schema: `agent_id` + `prompt`)
- Direct source read: `.planning/PROJECT.md` (v1.4 requirements, all key decisions, constraints)

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
│  Database: "ai_debug_traces"                                         │
│  Object store: "traces"                                              │
│  Key: trace_id (string UUID)                                         │
│  Value: plain JS object (serialized trace with nested arrays)        │
└──────────────────────────────────────────────────────────────────────┘
```

## Integration Points

### Integration Point 1: Hydration (page load → reactive Map)

**Location:** `AiDebugApp.setup()` → `onWillStart` callback

**What changes:** Before the first render, the component loads all persisted traces from IDB and populates `this.traces`. `onWillStart` is the correct lifecycle hook — it runs before the first render and supports async/await.

**Sequence:**
```
onWillStart async:
  1. await probeIDB()              → check availability
  2. await loadAllTraces()         → returns plain object array
  3. for each trace: hydrateTrace() → reconstruct reactive Maps
  4. this.traces.set(...)          → populate Map before first render
  5. (bus subscription starts in onMounted, after first render)
```

### Integration Point 2: Write-Through on Bus Events

**Location:** `AiDebugApp._onLoopEnd`

In the actual v1.3 implementation, IDB writes happen on `loop_end` (not on every event). This is a practical optimization: writing the full trace only when it's complete avoids many redundant writes. The `writeTrace` call in `_onLoopEnd` captures the complete trace state.

**Which handlers write to IDB:**

| Handler | IDB action | Reason |
|---------|-----------|--------|
| `_onNewTrace` | No IDB write | Trace incomplete |
| `_onIteration` | No IDB write | Trace incomplete |
| `_onToolCall` | No IDB write | Trace incomplete |
| `_onLoopEnd` | `writeTrace(trace)` | Trace complete — write once |

### Integration Point 3: Delete and Clear

Both IDB calls are fire-and-forget. Delete removes from both reactive Map and IDB. Select-all + bulk delete covers "clear all."

### Integration Point 4: Export and Import

Export serializes from in-memory Map (not IDB). Import hydrates and writes to both Map and IDB. All-or-nothing validation rejects partial imports.

## Serialization: Reactive Maps → Plain Objects

IDB uses structured clone, which cannot handle OWL's reactive Proxy wrapper. Serialize before writing:

```javascript
export function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        // ... scalar fields ...
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                ...iterScalarFields,
                toolCalls: [...iter.toolCalls.entries()].map(([tcId, tc]) => [tcId, {...tcScalarFields}]),
            },
        ]),
    };
}
```

JSON round-trip in `writeTrace` strips OWL reactive Proxies that IDB's structured clone cannot handle.

Deserialize with `hydrateTrace()` which reconstructs `reactive(new Map())` for all nested Maps — essential so bus events after hydration trigger OWL re-renders.

## Build Order (v1.3)

1. `db.js` — IDB wrapper (no dependencies on other new code)
2. Hydration in `onWillStart` — depends on `db.js`
3. Write-through in `_onLoopEnd` — depends on hydration working
4. Delete (reactive Map + IDB) — depends on write-through
5. Export — depends on nothing new (reads in-memory Map)
6. Import — depends on export (need an export file to test)

## Anti-Patterns (v1.3)

- Storing reactive Maps directly in IDB → DataCloneError
- Subscribing to bus before hydration completes → dropped events for existing traces
- Normalizing IDB schema (separate stores) → over-engineered for a developer tool
- Awaiting IDB writes in bus handlers → unnecessary blocking

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

The base `web/models/ir_http.py` returns `"light"` as the hardcoded default. **'system' is not passed through** — the server cannot know the OS preference, so `color_scheme()` never returns `'system'`, only `'light'` or `'dark'`.

### Layer 3: Cookie synchronization

`web_enterprise/controllers/home.py` sets the cookie on every webclient visit. This means: every time the user visits `/odoo`, Odoo sets (or refreshes) the `color_scheme` cookie to `'light'` or `'dark'`. **The ai_debug controller can read this cookie directly.**

## Data Flow: Theme Detection to CSS Bundle

```
User sets theme in Odoo Settings
    → res.users_settings.color_scheme = 'dark'
    → User visits /odoo → Odoo sets cookie: color_scheme='dark'
    → User navigates to /ai-debug
    → AiDebugController reads cookie → color_scheme='dark' → template context
    → QWeb template: t-if="color_scheme == 'dark'" → loads assets_dark CSS
    → Bootstrap CSS vars resolve to dark values (compiled at build time)
    → app.scss's var(--bs-body-bg) etc. get dark colors automatically
```

## Architecture for v1.2

**`controllers/main.py`:** Read `color_scheme` cookie, pass to template via `webclient_rendering_context()`.

**`views/ai_debug_index.xml`:** Split `t-call-assets` into JS-only (base bundle) + conditional CSS-only (light or dark bundle).

**`__manifest__.py`:** Add `ai_debug.assets_dark` bundle:
```python
'ai_debug.assets_dark': [
    ('include', 'web.dark_mode_variables'),
    ('include', 'ai_debug.assets'),
    'ai_debug/static/src/app/**/*.dark.scss',
],
```

**`static/src/app/app.scss`:** Replace all hardcoded hex colors with `var(--bs-*)` CSS custom properties. See the Catppuccin → Bootstrap mapping in the original full section below.

**`static/src/app/app.dark.scss`** (new): Dark-only overrides for values not expressible via `--bs-*` vars (JSON syntax highlighting colors, status dot colors).

## Anti-Patterns (v1.2)

- Using `prefers-color-scheme` CSS media query — conflicts with server-side Odoo preference
- Including `web.assets_web` instead of `web.assets_backend` — duplicates webclient bootstrap JS
- Duplicating JS in dark bundle — causes `@odoo-module` double-registration errors

---

# v1.1 Base Architecture

> The v1.1 standalone OWL app replaced v1.0's persistent DB models + backend XML views. Key decisions that carry forward unchanged:

- Generator yield passthrough for instrumentation (zero behavioral change to agentic loop)
- Separate cursor bus sends (`registry.cursor()`) for immediate NOTIFY before next iteration
- Full bus payloads (no lazy ORM reads, since there is no DB)
- `useState(new Map())` for trace store (not `reactive()` which uses NO_CALLBACK sentinel)
- Standalone OWL app at `/ai-debug` using `mountComponent` from `@web/env`
- Channel access gated by `ir.websocket` override to internal users only

The root component `AiDebugApp` owns all application state. Children receive props. Selection state is separate from trace data (prevents selection loss on bus events).

---

## Sources

**v1.4 sources (HIGH confidence — direct source reads, current date 2026-02-23):**
- `ai_debug/models/ai_session.py` (complete — 334 lines)
- `ai_debug/static/src/app/app.js` (complete — 627 lines)
- `ai_debug/static/src/app/app.xml` (complete — 201 lines)
- `ai_debug/static/src/app/db.js` (complete — 143 lines)
- `enterprise/ai/models/ai_session.py` (complete — 478 lines)
- `enterprise/ai/models/ai_agent.py` (complete — `_ai_tool_request_sub_agent` at line 1339)
- `enterprise/ai/models/ir_actions_server.py` (complete — `_ai_tool_run`, tool name check)
- `enterprise/ai/data/ir_actions_server_data.xml` (subagent tool record)
- `.planning/PROJECT.md` (v1.4 requirements and decisions)

**v1.3 sources (HIGH confidence — direct source reads, 2026-02-22):**
- Same source files above plus MDN IndexedDB API and OWL 2.x reactive proxy mechanics

**v1.2 sources (HIGH confidence — direct source reads, 2026-02-22):**
- `web_enterprise/models/ir_http.py`, `web_enterprise/controllers/home.py`
- `web/models/ir_http.py`, `web/views/webclient_templates.xml`
- `web/__manifest__.py`, `web_enterprise/__manifest__.py`
- `web/static/lib/bootstrap/scss/_root.scss`
- `web_enterprise/static/src/scss/primary_variables.dark.scss`

---
*Architecture research for: AI Debugger v1.4 — Subagent visualization*
*Researched: 2026-02-23*
