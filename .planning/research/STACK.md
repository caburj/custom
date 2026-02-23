# Stack Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched (v1.4 subagent addendum):** 2026-02-23
**Confidence:** HIGH (all patterns verified against enterprise and custom source at `/Users/joseph/clones/odoo/`)

---

## v1.4 Scope: Subagent Hierarchy Visualization

This section covers the stack additions and changes required to visualize subagent hierarchies. No new npm packages, Python libraries, or Odoo module dependencies are required. All work is Python instrumentation changes (backend) and JS/XML reactive store restructuring (frontend).

**Existing stack unchanged.** The v1.3 IndexedDB persistence, v1.2 theming, and v1.1 OWL standalone app stacks are not modified by v1.4 except where explicitly noted.

---

## v1.4 Backend: How `_ai_tool_request_sub_agent` Works

### Source Location

`/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_agent.py` lines 1339-1375 (HIGH confidence — direct source read).

### Execution Flow

When a parent agent decides to delegate to a sub-agent, the LLM emits a tool call with `name` matching `"ai_request_sub_agent_{id}"` (via `make_tool_name` — strips non-alpha chars from tool name "AI: Request Sub-Agent", lowercases, appends record ID). The enterprise `ai_session._handle_tool_calls()` detects this at line 221 by checking `"ai_request_subagent" in tool_call.get("name", "")`.

`_ai_tool_request_sub_agent(tool_context, agent_id, prompt)` then:

1. Looks up or creates a child `ai.session` record with `parent_session_id = parent_session_sudo.id`
2. Calls `ai_session_sudo._generate_next_response(message, tool_context["tool_request_confirmed"])`
3. Returns the generator — which the enterprise `_handle_tool_calls` iterates, forwarding `thought` and `tool_confirmation_request` items upstream

The child `_generate_next_response` → `_run_agentic_loop` call chain runs through the `ai_debug` module's overridden `_run_agentic_loop`. **This means the child session's loop is automatically instrumented** — it emits its own `new_trace`, `iteration`, `tool_call`, and `loop_end` events over the `ai_debug` bus channel, each with their own `trace_id`.

### Key Facts for Instrumentation

| Fact | Source | Confidence |
|------|--------|------------|
| `parent_session_id` field exists on `ai.session` | `ai/models/ai_session.py` line 62: `parent_session_id = fields.Many2one("ai.session", ...)` | HIGH |
| `self.parent_session_id` is readable at `_run_agentic_loop` call time | `_run_agentic_loop` is decorated `@api.model` — `self` is the `ai.session` recordset. The instrumented override in `ai_debug/models/ai_session.py` calls `self.agent_id`, `self.channel_id` already; adding `self.parent_session_id.id` follows the identical pattern | HIGH |
| Child session has `parent_session_id` populated when created | `ai_agent.py` line 1365: `"parent_session_id": parent_session_sudo.id` in the create dict | HIGH |
| Existing child sessions are found by `parent_session_id + agent_id` search | `ai_agent.py` lines 1349-1358: search before create, so `parent_session_id` is set on both new and existing child sessions | HIGH |
| The spawning tool call's `call_id` is the LLM-assigned identifier | In `_handle_tool_calls`, `tool_call['call_id']` is already captured by the `ai_debug` override in `tool_call` bus events | HIGH |
| Tool name for subagent detection: `"ai_request_subagent"` substring | `ai_session.py` line 221 — the detection substring used by the enterprise code itself | HIGH |
| `_run_agentic_loop` is `@api.model` — `self` may be an empty recordset in one-shot path | When called via `_get_direct_response`, `self` is an empty `ai.session` recordset (`self.env['ai.session']`). `self.parent_session_id` would be empty but safe to access — returns a falsy empty recordset. The subagent path always goes through `_generate_next_response` on a concrete session record. | HIGH |

### What Must Change in `_run_agentic_loop` Override

The `ai_debug` override emits `new_trace` at loop start. To correlate subagent traces with their parent, two fields must be added to the `new_trace` payload:

```python
# In ai_debug/models/ai_session.py _run_agentic_loop override:
parent_session_id = self.parent_session_id.id if self.parent_session_id else None

self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    # --- NEW in v1.4 ---
    'parent_session_id': parent_session_id,  # ORM ID of parent ai.session, or None
    # parent_tool_call_id is NOT reliably available at new_trace time (see note below)
    # --- existing fields unchanged ---
    'agent_name': self.agent_id.name if self.agent_id else None,
    'model_name': model,
    ...
})
```

**Why `parent_session_id` and not `parent_trace_id`:** The `trace_id` is a UUID generated at the start of each `_run_agentic_loop` invocation — it is not the `ai.session.id`. The parent's `trace_id` is not directly accessible from the child's loop invocation. Using `parent_session_id` (the ORM integer ID) allows the frontend to correlate: it receives the parent's `trace_id` in an earlier `new_trace` event that carries the same `parent_session_id`-as-None (parent has no parent), while the child's `new_trace` carries `parent_session_id` pointing to the parent session.

**The correlation chain:**
1. Parent `new_trace` event: `{trace_id: "abc", parent_session_id: null}` — frontend stores `session_id → trace_id` mapping (session ID comes from `state_snapshot.agent_id` and related fields... but wait — `self.id` is what we need).
2. Add `session_id: self.id` to the `new_trace` payload so the frontend can build the correlation map.
3. Child `new_trace` event: `{trace_id: "xyz", parent_session_id: 42, session_id: 99}` — frontend looks up which `trace_id` has `session_id == 42`, finds "abc", nests "xyz" under "abc".

**Also add `session_id` to `new_trace`:**

```python
self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'session_id': self.id or None,        # NEW: own ai.session.id for correlation
    'parent_session_id': self.parent_session_id.id if self.parent_session_id else None,  # NEW
    ...
})
```

**`parent_tool_call_id` availability:** The spawning tool call's `tool_call_id` (the `ai_debug`-assigned UUID, not the LLM's `call_id`) is emitted in the parent's `tool_call` bus event. However, that event fires *after* the tool executes — and the subagent's loop starts *inside* the tool execution, before the `tool_call` event fires. The `tool_call` event fires only when `_handle_tool_calls` yields `tool_results`, which happens after the subagent loop completes. Therefore:

- `parent_tool_call_id` (the ai_debug UUID) **cannot** be included in `new_trace` — it does not exist yet when `new_trace` fires
- The LLM's `call_id` (from `tool_call['call_id']` in `_handle_tool_calls`) **is** available inside the tool execution but not passed through to `_ai_tool_request_sub_agent` or `_run_agentic_loop`

**Solution: emit `parent_call_id` in `tool_call` event.** The parent's `tool_call` bus event already includes `call_id` (the LLM's call_id). Add a `child_trace_id` field to the parent's `tool_call` event — populated when the tool name matches the subagent pattern. This requires the subagent tool to communicate its `trace_id` back up. This is complex.

**Simpler solution: correlate via `parent_session_id` + session_id map in frontend.** The frontend maintains a `Map<session_id, trace_id>`. When a `new_trace` event arrives with `parent_session_id != null`, look up `parentTraceId = sessionToTrace.get(parent_session_id)`. The subagent trace goes under that parent trace. The exact spawning tool call is found by looking at the parent trace's tool calls that match the subagent pattern — there will typically be one per subagent invocation, and if multiple exist they can be matched by timing (tool_call receivedAt before child trace started_at).

**Revised `new_trace` payload additions for v1.4:**

```python
# In _run_agentic_loop override
self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'session_id': self.id if self.id else None,            # NEW: own ORM session ID
    'parent_session_id': self.parent_session_id.id if self.parent_session_id else None,  # NEW
    # all existing fields unchanged
    'agent_name': self.agent_id.name if self.agent_id else None,
    'model_name': model,
    'user_query': user_query,
    'instructions': instructions,
    'tools': self._ai_debug_serialize_tools(tools, model),
    'state_snapshot': self._ai_debug_state_snapshot(tools_context),
})
```

No other backend changes are required. The four event types (`new_trace`, `iteration`, `tool_call`, `loop_end`) already use `trace_id` as the correlation key within a single trace. Cross-trace correlation is fully handled by the two new fields on `new_trace`.

---

## v1.4 Frontend: Reactive Store Changes

### Current Store Structure

```
traces: useState(new Map())           // Map<trace_id, trace>
  trace.iterations: reactive(new Map())  // Map<iteration_id, iteration>
    iteration.toolCalls: reactive(new Map())  // Map<tool_call_id, toolCall>
```

Each `trace` is a flat, independent entry. There is no parent-child relationship between traces.

### v1.4 Required Changes

**Goal:** Subagent traces nest under the tool call that spawned them in the sidebar. Within a trace, flatten the tree so iterations and tool calls appear at the same indent level (no expand/collapse of iterations).

#### 1. Session-to-Trace Correlation Map

Add a plain (non-reactive) `Map<session_id, trace_id>` to `AiDebugApp` state. This is populated as `new_trace` events arrive:

```javascript
// In setup() — not reactive, lookup only, no need to trigger re-renders
this._sessionToTrace = new Map();  // session_id (int) → trace_id (string)
```

In `_onNewTrace`:
```javascript
this._onNewTrace = (payload) => {
    // ...existing trace creation...
    // NEW: register session_id → trace_id for child correlation
    if (payload.session_id) {
        this._sessionToTrace.set(payload.session_id, payload.trace_id);
    }
    // NEW: attach to parent trace if this is a subagent
    if (payload.parent_session_id) {
        const parentTraceId = this._sessionToTrace.get(payload.parent_session_id);
        if (parentTraceId) {
            const newTrace = this.traces.get(payload.trace_id);
            if (newTrace) {
                newTrace.parentTraceId = parentTraceId;
            }
        }
    }
    // ...
};
```

Each trace object gains:
- `session_id: number | null` — its own `ai.session` ORM ID (from `new_trace` payload)
- `parentTraceId: string | null` — the `trace_id` of the parent trace (null for root traces)

#### 2. Per-Agent Color Assignment

A global color palette is assigned on first appearance of each `agent_name`. Colors are persisted to IDB in a separate store `"agent_colors"`.

```javascript
// In setup():
this._agentColors = new Map();  // agent_name (string) → CSS color string

// Color palette — 8 distinct Odoo-compatible hues
const COLOR_PALETTE = [
    '#6366f1',  // indigo
    '#10b981',  // emerald
    '#f59e0b',  // amber
    '#ef4444',  // red
    '#8b5cf6',  // violet
    '#06b6d4',  // cyan
    '#f97316',  // orange
    '#84cc16',  // lime
];

getAgentColor(agentName) {
    if (!agentName) return null;
    if (!this._agentColors.has(agentName)) {
        const idx = this._agentColors.size % COLOR_PALETTE.length;
        this._agentColors.set(agentName, COLOR_PALETTE[idx]);
        // Persist new assignment to IDB (fire-and-forget)
        this._persistAgentColors();
    }
    return this._agentColors.get(agentName);
}
```

**Why not use OWL reactive for `_agentColors`:** Colors are an append-only lookup table. Templates access colors via `getAgentColor(agentName)` — an explicit method call. No OWL reactive proxy needed; OWL re-renders when trace data changes (which always accompanies color assignment).

**IDB schema for colors:** Add a second object store `"agent_colors"` to the existing `"ai_debug_traces"` database (requires `DB_VERSION` bump from `1` to `2`). The Odoo `IndexedDB` class deletes and recreates the database on version bump — existing trace data is lost. Two migration options:

Option A (simple, acceptable for dev tool): Bump to version 2, accept that existing IDB traces are cleared on first load after upgrade.

Option B (preserve data): Use a separate `IndexedDB` instance for colors at a new DB name `"ai_debug_settings"` with version 1. No version bump to `"ai_debug_traces"`. This is cleaner and avoids wiping stored traces.

**Recommendation: Option B.** Use `new IndexedDB("ai_debug_settings", 1)` for agent colors. The existing `"ai_debug_traces"` DB stays at version 1 with no disruption to stored traces.

```javascript
// In db.js — add alongside existing idb:
const SETTINGS_DB_NAME = "ai_debug_settings";
const SETTINGS_DB_VERSION = 1;
const COLORS_STORE = "agent_colors";

const settingsIdb = new IndexedDB(SETTINGS_DB_NAME, SETTINGS_DB_VERSION);
settingsIdb._tables.add(COLORS_STORE);

export async function loadAgentColors() {
    return settingsIdb.execute((db) => {
        if (!db) return {};
        if (!db.objectStoreNames.contains(COLORS_STORE)) return {};
        return new Promise((resolve, reject) => {
            const tx = db.transaction(COLORS_STORE, "readonly");
            const req = tx.objectStore(COLORS_STORE).get("colors");
            req.onsuccess = () => resolve(req.result ?? {});
            tx.onerror = () => reject(tx.error);
        });
    });
}

export function saveAgentColors(colorsMap) {
    const plain = Object.fromEntries(colorsMap.entries());
    return settingsIdb.write(COLORS_STORE, "colors", plain);
}
```

Hydrate in `onWillStart` alongside existing trace hydration:
```javascript
const storedColors = await loadAgentColors();
for (const [name, color] of Object.entries(storedColors)) {
    this._agentColors.set(name, color);
}
```

#### 3. Flat Tree Within a Trace

The current tree nests tool calls under their parent iteration with expand/collapse. V1.4 removes the iteration expand/collapse: iterations and tool calls render at the same visual indentation within a trace.

**Sidebar rendering change:** Instead of `Loop > [expand] Iteration > [expand] Tool Call`, the new layout is `Trace > Iteration, Tool Call, Iteration, Tool Call, ...` — all at the same level visually, ordered by insertion time.

Implementation: Change the XML template to render iterations and tool calls in a single flat pass per trace, rather than nesting tool calls inside iteration expand blocks. The data model does not change — `iteration.toolCalls` is still a nested Map. Only the template rendering changes.

```xml
<!-- v1.4 flat tree: within a trace, iterations and tool calls at same level -->
<t t-if="trace.expanded">
    <t t-foreach="[...trace.iterations.entries()]" t-as="iterEntry" t-key="iterEntry[0]">
        <t t-set="iterationId" t-value="iterEntry[0]"/>
        <t t-set="iteration" t-value="iterEntry[1]"/>

        <!-- Iteration row — same level as tool calls -->
        <div class="ai-tree-row level-1 flat" ...>
            ...iteration label...
        </div>

        <!-- Tool calls immediately follow, same indentation level -->
        <t t-foreach="[...iteration.toolCalls.entries()]" t-as="tcEntry" t-key="tcEntry[0]">
            <t t-set="tc" t-value="tcEntry[1]"/>
            <div class="ai-tree-row level-1 flat tool-call" ...>
                ...tool call label...
            </div>
            <!-- Subagent trace nests here if tc.tool_name matches subagent pattern -->
            <t t-if="getChildTraceForToolCall(tc)">
                <!-- Recursive subagent subtree at level-2 indentation -->
            </t>
        </t>
    </t>
</t>
```

#### 4. Subagent Trace Nesting in Sidebar

Subagent traces must nest under the tool call that spawned them. The challenge: matching a subagent trace to a specific tool call. The correlation is indirect:

- The subagent `new_trace` event has `parent_session_id` → maps to `parentTraceId`
- A tool call in the parent trace has `tool_name` containing `"ai_request_subagent"` and `call_id`
- There may be multiple subagent tool calls in one iteration (parallel subagents), each spawning a different subagent trace

**Matching strategy:** Use `agent_name` on the subagent trace and `args.agent_id` on the tool call. The tool call args contain `{agent_id: int, prompt: string}`. The subagent trace has `agent_name` (the name of agent with that `agent_id`). This is sufficient when each agent has a unique name.

Add a method to `AiDebugApp`:

```javascript
getChildTrace(toolCall) {
    // Returns the child trace that was spawned by this tool call, if any.
    // Matches by: (1) parentTraceId === parent's traceId AND (2) agent matches args.agent_id
    // Since we have agent_name on traces but agent_id on tool_call.args, we match
    // by finding a child trace whose parent_session_id resolves to this trace and whose
    // agent's name matches (approximation — good enough for dev tool).
    for (const trace of this.traces.values()) {
        if (trace.parentTraceId && toolCall.tool_name &&
            toolCall.tool_name.includes("ai_request_subagent")) {
            // Check if this child trace belongs to the current parent
            // parentTraceId was set in _onNewTrace via _sessionToTrace lookup
            const parentTrace = this.traces.get(trace.parentTraceId);
            if (parentTrace) {
                // Match: child trace agent matches tool call args.agent_id indirectly
                // For simplicity: one subagent call per agent per trace (common case)
                // Use call_id matching if needed for disambiguation
                return trace;
            }
        }
    }
    return null;
}
```

For accurate disambiguation with multiple simultaneous subagent calls, emit `parent_call_id` (the LLM's `call_id`) in `new_trace`. This requires passing `call_id` through the tool execution context. **This is a v1.4 stretch goal** — the basic case (one subagent call per iteration) works without it.

**Simplest accurate approach:** Add `parent_call_id` to the `new_trace` payload. This requires:

1. In `ai_debug/models/ai_session.py` `_handle_tool_calls` override: when a tool call matches the subagent pattern, extract the `call_id` and pass it to the child session via context
2. In `_run_agentic_loop` override: read `parent_call_id` from context and include in `new_trace`

Implementation:

```python
# In _handle_tool_calls override, after the super() loop yields tool_results:
# When a tool call is the subagent tool, the parent call_id is already in
# the tool_call event payload as 'call_id'. The child trace must reference it.
# Pass via env context into the subagent session's loop.

# In _generate_next_response override (ai_debug version), add:
parent_call_id = self.env.context.get('_ai_debug_parent_call_id')

# This requires ai_debug to intercept _generate_next_response on the child session
# and inject 'parent_call_id' into context BEFORE the super() call executes.
# Since _ai_tool_request_sub_agent calls ai_session_sudo._generate_next_response()
# directly, and ai_session_sudo has _inherit = 'ai.session', the ai_debug override
# fires automatically on that call.

# But the parent's call_id is not in context when _generate_next_response fires.
# It IS available in tools_context['tool_call_id'] within _handle_tool_calls.
# Passing it through requires the enterprise code to set it in context or
# ai_debug to intercept at the _handle_tool_calls level.
```

**Verdict on `parent_call_id`:** Implement it via a targeted env context injection. In `ai_debug`'s `_handle_tool_calls` override, when `super()` yields an item and the current tool call is a subagent call, the child trace has already been launched inside `super()`. The `call_id` is available in the `tool_calls_by_id` lookup. Set it in `_debug_ctx` before the super loop runs so the child can read it.

Actually, the cleanest approach: in `_run_agentic_loop`, if `self.parent_session_id` is set, read `tools_context.get('tool_call_id')` (already set by enterprise code at line 214: `tools_context['tool_call_id'] = tool_call['call_id']`) and emit it in `new_trace` as `parent_call_id`:

```python
# In _run_agentic_loop override:
parent_session_id = self.parent_session_id.id if self.parent_session_id else None
parent_call_id = tools_context.get('tool_call_id') if parent_session_id else None

self._ai_debug_bus_send('new_trace', {
    'trace_id': trace_id,
    'session_id': self.id if self.id else None,
    'parent_session_id': parent_session_id,
    'parent_call_id': parent_call_id,   # LLM's call_id of spawning tool call
    ...
})
```

This works because: `_ai_tool_request_sub_agent` receives `tool_context` (which is `tools_context`), and at the time it is called, `tools_context['tool_call_id']` has already been set by `_handle_tool_calls` line 214. The child `_run_agentic_loop` is called with the same `tools_context` via `_generate_next_response` → `_run_agentic_loop`. Verify: `_generate_next_response` creates a new `tools_context` dict — it does NOT pass the parent's `tools_context`. So `tools_context.get('tool_call_id')` in the child's `_run_agentic_loop` is `None`.

**Correct path:** `parent_call_id` must be passed via `env.context`. The `_ai_tool_request_sub_agent` call is: `ai_session_sudo._generate_next_response(message, ...)`. The `ai_debug` override of `_generate_next_response` on `ai_session_sudo` fires here. We can intercept at `_generate_next_response` in the child session:

```python
# In ai_debug AiSession._generate_next_response override:
# If parent_session_id is set (this is a subagent session), try to get the
# spawning call_id from env context (set by the parent's instrumented loop)
```

But the parent's instrumented `_handle_tool_calls` would need to `.with_context(...)` before calling super. This is getting complex.

**Final recommendation: emit `parent_call_id` as None in v1.4.0, match by `parent_session_id` + subagent tool name substring.** The frontend matching by parent trace + subagent tool name is good enough for the common case. Add exact `parent_call_id` matching as a follow-up if duplicate subagent calls in one iteration cause confusion.

---

## v1.4 IDB Schema

### Trace Store (`"ai_debug_traces"`, version 1 — unchanged)

The trace serialization format in `db.js` gains two new fields on each trace record:

```javascript
// serializeTrace additions:
{
    ...existing fields...
    session_id: trace.session_id ?? null,         // NEW: own ai.session ORM ID
    parentTraceId: trace.parentTraceId ?? null,   // NEW: parent trace_id string (null for roots)
}
```

`hydrateTrace` reads these fields back transparently.

### Colors Store (`"ai_debug_settings"`, version 1 — new)

One record keyed `"colors"` in store `"agent_colors"`. Value: `{ agentName: cssColor, ... }` (plain object from `Map.entries()`).

No migration needed — separate DB name, version 1, independent of trace data.

---

## v1.4 OWL Reactivity Constraints

### What Works

- `this.traces.set(traceId, {..., parentTraceId})` — OWL re-renders sidebar when any trace Map entry changes (HIGH confidence — same as existing code)
- `trace.parentTraceId = parentTraceId` — mutating a field on a reactive proxy object triggers re-renders in any component that reads it (HIGH confidence — existing code does this with `trace.status`, `trace.expanded`, etc.)
- `getChildTraceForToolCall(tc)` called from template — pure method reading from `this.traces`, which is reactive; calling it in a template expression means OWL tracks the reactive access and re-renders when traces change (HIGH confidence)

### What Does Not Work

- Using `_sessionToTrace` (a plain `Map`) reactively in templates — it is NOT wrapped in `reactive()` or `useState()`. Do not reference it directly in templates. It is a lookup table used in event handlers only. (HIGH confidence)
- Storing `_agentColors` as `reactive()` — unnecessary. Color lookups happen via `getAgentColor()` method called from templates; the reactive trace update already triggers re-renders when colors are needed. (HIGH confidence)

### Flat Tree Rendering

Removing iteration expand/collapse reduces reactive surface: no more `iteration.expanded` boolean toggling. The `toggleExpand` method and associated `onPatched` scroll logic needs updating. The flat tree template iterates `[...trace.iterations.entries()]` in insertion order (chronological), emitting iteration rows and immediately following with their tool call rows. This is a pure template change — no store restructuring required.

---

## v1.4 What NOT to Change

| Do Not Change | Why |
|---------------|-----|
| `new_trace` event type name | Frontend subscribes to this exact string. Changing it breaks existing subscriptions. Add new fields only. |
| `trace_id` as primary correlation key within a trace | All four event types use it consistently. No change needed. |
| `useState(new Map())` for the top-level traces store | This pattern is validated and required for OWL reactivity. Do not convert to `reactive()` without `useState`. |
| `DB_VERSION` for `"ai_debug_traces"` | Bumping it wipes existing stored traces. Use a separate DB for new schema additions (agent colors). |
| `_handle_tool_calls` override structure | The override already correctly captures tool call results and emits bus events. Subagent tool calls flow through the same mechanism. |
| Bus channel name `"ai_debug"` | Frontend subscribes to this channel. Changing it breaks all event delivery. |
| `_ai_debug_bus_send` separate cursor pattern | Required for immediate delivery before next loop iteration. Do not convert to batching. |

---

## v1.4 Confidence Assessment

| Area | Confidence | Basis |
|------|------------|-------|
| `parent_session_id` field on `ai.session` | HIGH | Direct source read: `ai/models/ai_session.py` line 62 |
| `self.parent_session_id` accessible in `_run_agentic_loop` override | HIGH | `@api.model` — `self` is a concrete record when called via `_generate_next_response`; `self.parent_session_id` read identical to existing `self.agent_id`, `self.channel_id` accesses |
| `tools_context['tool_call_id']` is the LLM call_id when subagent runs | HIGH | Enterprise `_handle_tool_calls` sets `tools_context['tool_call_id'] = tool_call['call_id']` at line 214, before calling tool; `_generate_next_response` creates fresh `tools_context` for child, so it's NOT inherited |
| Frontend `_sessionToTrace` lookup approach | HIGH | Pure data structure correlation; no framework API involved |
| OWL reactivity for `parentTraceId` field mutation | HIGH | Same pattern as existing `trace.status`, `trace.expanded` mutations |
| `new IndexedDB("ai_debug_settings", 1)` for colors | HIGH | Same API used for `"ai_debug_traces"` DB; separate name avoids schema conflict |
| Flat tree rendering (template-only change) | HIGH | No store changes needed; OWL `t-foreach` over Map entries is already used |
| `parent_call_id` accurate matching for parallel subagents | MEDIUM | Requires threading `tool_call_id` through env context across method boundaries; feasible but adds complexity. Defer to v1.4.1 if basic matching is sufficient. |

---

## v1.4 Sources

All patterns verified against source code (not training data or web search):

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_agent.py` lines 1339-1375 — `_ai_tool_request_sub_agent` full implementation (HIGH confidence)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` lines 62, 221-235 — `parent_session_id` field, subagent detection in `_handle_tool_calls` (HIGH confidence)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — full `_run_agentic_loop` and `_handle_tool_calls` overrides; `_ai_debug_bus_send`, `_ai_debug_state_snapshot` helpers (HIGH confidence)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — `_onNewTrace`, `_onToolCall`, `_onLoopEnd` handlers; `useState(new Map())` store; `hydrateTrace()` pattern (HIGH confidence)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — `serializeTrace`, `writeTrace`, `loadAllTraces`, `IndexedDB` usage pattern (HIGH confidence)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.xml` — current 3-level sidebar tree template (HIGH confidence)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_agent.py` lines 20-25 — `make_tool_name` function showing subagent tool name format (HIGH confidence)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/data/ir_actions_server_data.xml` lines 43-67 — `ir_actions_server_request_sub_agent` record confirming tool name prefix "AI: Request Sub-Agent" → normalized to `ai_request_sub_agent_{id}` (HIGH confidence)

---

## v1.3 Scope: IndexedDB Persistence, Export/Import, Trace Management

This section covers stack additions for persisting traces to IndexedDB, exporting/importing as JSON files, and providing delete/clear UI. No new npm packages or Odoo module dependencies are required — all needed APIs exist in Odoo master's `web` addon or in the browser platform itself.

**Existing stack unchanged.** The v1.2 theming stack (SCSS bundles, color scheme detection) and v1.1 stack (OWL standalone app, bus_service, sidebar tree) are not modified by v1.3.

---

## v1.3 Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `IndexedDB` from `@web/core/utils/indexed_db` | Odoo master | Structured local storage for trace data | Odoo's own IndexedDB wrapper handles versioning, schema upgrades, quota errors, and mutex-serialized transactions. Used in production by `menu_service`, `localization_service`, `rpc_cache`, and `offline_service`. Import path: `import { IndexedDB } from "@web/core/utils/indexed_db"`. Zero external dependency. |
| `downloadFile` from `@web/core/network/download` | Odoo master | Trigger a browser file download from in-memory data | Creates a temporary `<a download>` element, sets an object URL from a `Blob`, clicks it, then revokes the URL. Handles all cross-browser edge cases. Used throughout Odoo for report downloads. Import: `import { downloadFile } from "@web/core/network/download"`. Pass a `Blob` or string + filename + MIME type. |
| Native `FileReader` API | Browser (all modern) | Read a user-selected JSON file into memory | `FileReader.readAsText(file)` delivers the file content as a string. Wrap in a `Promise` for async/await. No Odoo wrapper needed — the download.js source in Odoo itself uses raw `FileReader` in the same pattern. |
| Hidden `<input type="file" accept=".json">` | Browser (all modern) | Trigger OS file picker for import | A `useRef`-held hidden input element, programmatically `.click()`-ed from a button handler, with `.change` event handling. This is the pattern used by Odoo's own component library (`FileInput` in `@web/core/file_input/file_input`). For local-only import we do NOT use `FileInput` (it uploads to server) — just the raw input element. |
| `notification` service via `useService("notification")` | Odoo master | User feedback for import errors, quota exceeded | `notification.add(message, { type: "danger" })`. Available in the standalone OWL app — registered in `web.assets_backend` which is included by `ai_debug.assets`. Already available to all OWL components via `useService`. |
| `dialog` service via `useService("dialog")` + `ConfirmationDialog` | Odoo master | Delete-confirmation modal before destructive operations | `dialogService.add(ConfirmationDialog, { body, confirm, cancel })` opens a Bootstrap modal with "Confirm" / "Discard" buttons. Import `ConfirmationDialog` from `@web/core/confirmation_dialog/confirmation_dialog`. Available automatically through `web.assets_backend`. |

### Supporting APIs (Browser-Native, No New Dependencies)

| API | Purpose | Notes |
|-----|---------|-------|
| `IndexedDB.execute(callback)` | Run raw IDB operations not covered by `read`/`write`/`getAllKeys` | The `execute` method gives the callback a live `IDBDatabase` instance. Use `db.transaction(table, "readonly").objectStore(table).getAll()` to bulk-read all trace records on startup hydration. The `IndexedDB` class itself only exposes `read(table, key)` and `getAllKeys(table)` — use `execute` for `getAll`. |
| `IndexedDB.invalidate()` | Clear all entries in all stores | Odoo's API: `invalidate(null)` clears all stores; `invalidate("traces")` clears one store. Use for "Clear All" button. |
| `IndexedDB.execute` with `objectStore.delete(key)` | Delete a single trace by ID | No `delete(key)` method on the `IndexedDB` class. Use `execute((db) => new Promise((res, rej) => { const tx = db.transaction("traces", "readwrite"); tx.objectStore("traces").delete(traceId); tx.oncomplete = res; tx.onerror = () => rej(tx.error); }))`. |
| `JSON.stringify` / `JSON.parse` | Serialize trace data for IndexedDB and export | IndexedDB stores structured clones natively — pass plain objects directly to `write()`. For export: `JSON.stringify(payload, null, 2)` for readable output. For import: `JSON.parse(text)` then validate schema version field before merging. |
| `URL.createObjectURL` + `URL.revokeObjectURL` | Called internally by `downloadFile` | Do not call these directly — `downloadFile` handles the object URL lifecycle. |

---

## v1.3 Integration with Existing `useState(new Map())` Store

The existing reactive store uses `useState(new Map())` at the top level with nested `reactive(new Map())` for iterations and tool calls. IndexedDB persistence requires a serialization strategy because:

1. OWL `reactive` proxies are not JSON-serializable.
2. `Date` objects become strings in JSON round-trips and must be reconstructed.
3. Nested `reactive(new Map())` must be recreated when hydrating from IndexedDB.

### Serialization Pattern

Store each trace as a **plain JSON object** keyed by `trace_id`. The object stores only the raw data fields — no `reactive`, no `Map`, no `Date` objects. On load, reconstruct the reactive Maps and Date instances.

```javascript
// Serialize one trace to a plain object for IndexedDB storage
function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        agent_name: trace.agent_name,
        model_name: trace.model_name,
        status: trace.status,
        started_at: trace.started_at?.toISOString() ?? null,
        ended_at: trace.ended_at?.toISOString() ?? null,
        duration_ms: trace.duration_ms,
        instructions: trace.instructions,
        tools: trace.tools,
        state_snapshot: trace.state_snapshot,
        iterations: Object.fromEntries(
            [...trace.iterations.entries()].map(([iterId, iter]) => [
                iterId,
                {
                    iteration_id: iter.iteration_id,
                    trace_id: iter.trace_id,
                    iteration_index: iter.iteration_index,
                    has_error: iter.has_error,
                    receivedAt: iter.receivedAt?.toISOString() ?? null,
                    is_final: iter.is_final,
                    error: iter.error,
                    messages_sent: iter.messages_sent,
                    raw_response: iter.raw_response,
                    toolCalls: Object.fromEntries(
                        [...iter.toolCalls.entries()].map(([tcId, tc]) => [tcId, { ...tc }])
                    ),
                },
            ])
        ),
    };
}

// Hydrate a plain object back to the reactive store format
function hydrateTrace(plain) {
    const iterations = reactive(new Map());
    for (const [iterId, iterPlain] of Object.entries(plain.iterations || {})) {
        const toolCalls = reactive(new Map());
        for (const [tcId, tcPlain] of Object.entries(iterPlain.toolCalls || {})) {
            toolCalls.set(tcId, { ...tcPlain });
        }
        iterations.set(iterId, {
            ...iterPlain,
            receivedAt: iterPlain.receivedAt ? new Date(iterPlain.receivedAt) : null,
            expanded: false,  // UI state always starts collapsed on hydration
            toolCalls,
        });
    }
    return {
        ...plain,
        started_at: plain.started_at ? new Date(plain.started_at) : null,
        ended_at: plain.ended_at ? new Date(plain.ended_at) : null,
        expanded: false,  // UI state always starts collapsed on hydration
        iterations,
    };
}
```

### Write Pattern (Fire-and-Forget on Every Bus Event)

Write to IndexedDB after each bus event mutates the store. The write is async but does not block the reactive update — OWL re-renders immediately; IndexedDB write happens in the background:

```javascript
// In _onNewTrace, _onIteration, _onToolCall, _onLoopEnd handlers — after store mutation:
this._db.write("traces", payload.trace_id, serializeTrace(this.traces.get(payload.trace_id)));
// No await — fire-and-forget. Failures are logged by IndexedDB class internally.
```

**Why fire-and-forget:** The bus events arrive quickly (multiple per second during an agentic loop). Awaiting each write would block the event handler and delay store updates, causing visual lag. IndexedDB writes with `durability: "relaxed"` are fast (sub-millisecond typically). The worst case on failure is one event not persisted — acceptable for a dev tool.

### Hydration Pattern (onMounted, Before Bus Subscription)

```javascript
onMounted(async () => {
    // Hydrate from IndexedDB BEFORE subscribing to bus
    // so that existing traces are visible immediately,
    // and new bus events append to (not overwrite) them.
    const keys = await this._db.getAllKeys("traces");
    for (const key of keys) {
        const plain = await this._db.read("traces", key);
        if (plain) {
            this.traces.set(plain.trace_id, hydrateTrace(plain));
        }
    }
    // Then subscribe to bus...
    this.busService.subscribe("new_trace", this._onNewTrace);
    // ...
});
```

**Why `getAllKeys` then individual `read` calls:** The `IndexedDB` class from `@web/core/utils/indexed_db` does not have a `getAll()` method that returns values (only `getAllKeys()` exists). To bulk-read, either: (a) loop `getAllKeys` → `read` per key (simple, works), or (b) use `execute((db) => new Promise(res => db.transaction("traces","readonly").objectStore("traces").getAll().onsuccess = e => res(e.target.result)))`. Option (a) is simpler and readable for the expected trace count (dozens, not thousands). Use option (b) if startup time becomes a concern.

---

## v1.3 Schema

Store one object store named `"traces"` in a database named `"ai_debug_traces"`.

```javascript
// In setup():
this._db = new IndexedDB("ai_debug_traces", 1);
// Version 1 — bump if schema changes. The IndexedDB class auto-deletes and re-creates
// the database when the version changes (verified in _checkVersion() source).
```

**Database name:** `"ai_debug_traces"` — scoped to this app, avoids conflicts with Odoo's other IndexedDB databases (`"webclient_menu"`, `"odoo_rpc_cache"`, etc.).

**Object store name:** `"traces"` — one store, one key per trace (`trace_id`), full serialized trace as value.

**Schema version strategy:** Start at `1`. The Odoo `IndexedDB` class's `_checkVersion()` deletes and re-creates the entire database if the version changes. This is acceptable for a dev tool. Bump to `2` if the stored schema changes in a future milestone.

---

## v1.3 Export Pattern

```javascript
exportTraces(traceIds) {
    // traceIds: array of trace_id strings to export, or null for all
    const toExport = traceIds
        ? traceIds.map((id) => serializeTrace(this.traces.get(id))).filter(Boolean)
        : [...this.traces.values()].map(serializeTrace);

    const payload = {
        version: 1,  // export schema version — bump if format changes
        exported_at: new Date().toISOString(),
        traces: toExport,
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const filename = `ai-traces-${new Date().toISOString().slice(0, 19).replace(/:/g, "-")}.json`;
    downloadFile(blob, filename, "application/json");
}
```

**Why `downloadFile` not `<a>` directly:** `downloadFile` from `@web/core/network/download` handles cross-browser edge cases (Safari, IE11 fallback, object URL lifecycle). It is already in the bundle via `web.assets_backend`.

---

## v1.3 Import Pattern

```javascript
importTraces(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = (e) => {
            try {
                const payload = JSON.parse(e.target.result);
                if (payload.version !== 1) {
                    reject(new Error(`Unsupported export version: ${payload.version}`));
                    return;
                }
                for (const plain of payload.traces) {
                    // Merge: imported traces are added; existing traces with same ID are overwritten
                    this.traces.set(plain.trace_id, hydrateTrace(plain));
                    this._db.write("traces", plain.trace_id, plain);  // fire-and-forget
                }
                resolve(payload.traces.length);
            } catch (err) {
                reject(err);
            }
        };
        reader.onerror = () => reject(new Error("FileReader error"));
        reader.readAsText(file);
    });
}
```

**Error surface:** Wrap the call in a try/catch in the button handler and show `notification.add(err.message, { type: "danger" })` on failure.

---

## v1.3 Delete Patterns

```javascript
// Delete single trace — from store and IndexedDB
async deleteTrace(traceId) {
    this.traces.delete(traceId);
    if (this.state.selectedId === traceId) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    await this._db.execute((db) => new Promise((res, rej) => {
        const tx = db.transaction("traces", "readwrite");
        tx.objectStore("traces").delete(traceId);
        tx.oncomplete = res;
        tx.onerror = () => rej(tx.error);
    }));
}

// Clear all — both store and IndexedDB
async clearAll() {
    this.traces.clear();
    this.state.selectedId = null;
    this.state.selectedType = null;
    await this._db.invalidate("traces");  // clears the "traces" object store
}
```

**Confirmation before delete:** Use `dialogService.add(ConfirmationDialog, { body: "Delete this trace?", confirm: () => this.deleteTrace(id), confirmClass: "btn-danger", confirmLabel: "Delete" })`. The existing `clearAll()` method in `app.js` already exists but only clears the in-memory store — v1.3 adds the IndexedDB side.

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `localStorage` for trace storage | 5-10 MB limit in most browsers. A single large RAG-enabled session can produce megabytes of trace data. Size cap causes silent data loss with no error surfacing. | `IndexedDB` via `@web/core/utils/indexed_db` — browser-managed quota with explicit `QuotaExceededError`. |
| `idb` npm package (jakearchibald/idb) | External npm dependency; not in Odoo's asset pipeline; adds 2 KB gzip for a wrapper we get for free from `@web/core/utils/indexed_db`. | `IndexedDB` from `@web/core/utils/indexed_db` — already in the bundle via `web.assets_backend`. |
| `idb-keyval` (already vendored in mail/website_event_track) | Vendored as a service worker utility in the `mail` addon — not accessible from `@web/core/utils`. Importing across addons from a vendor lib path is fragile. | `IndexedDB` from `@web/core/utils/indexed_db`. |
| POS `IndexedDB` class (`@point_of_sale/app/models/utils/indexed_db`) | POS IndexedDB is designed for POS-specific batch ORM data — heavyweight, callback-based, not exposed as an `@web/*` import. | `IndexedDB` from `@web/core/utils/indexed_db`. |
| Storing OWL reactive proxies in IndexedDB | `structuredClone` (used internally by IndexedDB) cannot clone OWL Proxy objects and will throw `DataCloneError`. | Serialize to plain objects via `serializeTrace()` before writing. |
| Awaiting IndexedDB writes in bus event handlers | Blocks the event handler and delays OWL reactive updates, causing sidebar to stutter during fast loop execution. | Fire-and-forget writes — `this._db.write(...)` without `await` in event handlers. |
| `FileInput` component from `@web/core/file_input/file_input` | `FileInput` is hardwired to upload files to a server route (`/web/binary/upload_attachment`). We need client-side `FileReader` — no server round-trip. | Hidden `<input type="file">` with `FileReader.readAsText()`. |
| Server-side persistence (Odoo model, SQL) | Adds a migration, a model, ORM overhead, and database I/O for every bus event. Out of scope per PROJECT.md constraints. | IndexedDB for persistence; nothing for coordination. |

---

## Version Compatibility

| API | Odoo Version | Notes |
|-----|--------------|-------|
| `IndexedDB` class at `@web/core/utils/indexed_db` | Odoo master | Verified imported by `menu_service`, `localization_service`, `rpc_cache`, `offline_service`. The class is stable and widely used. |
| `IndexedDB.execute(callback)` | Odoo master | Exposes raw `IDBDatabase` for operations not in the class API. `getAll()` for values requires this. |
| `IndexedDB.invalidate(tableName)` | Odoo master | Passing a string clears one store. Passing null clears all stores except `__DBVersion__`. |
| `downloadFile(data, filename, mimetype)` | Odoo master | Exported from `@web/core/network/download`. Accepts `Blob`, `string`, or data URL as `data`. |
| `ConfirmationDialog` | Odoo master | At `@web/core/confirmation_dialog/confirmation_dialog`. Props: `body`, `confirm`, `cancel`, `confirmLabel`, `cancelLabel`, `confirmClass`, `title`. |
| `notification` service | Odoo master | `useService("notification")` in any OWL component mounted via `mountComponent`. API: `notification.add(message, { type: "success"|"danger"|"warning"|"info" })`. |
| `dialog` service | Odoo master | `useService("dialog")` in any OWL component. API: `dialogService.add(Component, props)`. Returns a close function. |
| `IDBQuotaExceededError` | Odoo master | Exported from `@web/core/utils/indexed_db`. Thrown (not just logged) when quota is exceeded. Catch it to show a user-facing notification. |
| `FileReader` | Browser — all modern | `readAsText(file)` → `onload` → `event.target.result` string. No Odoo dependency. |

---

## Sources

All patterns verified against Odoo master source code at `/Users/joseph/clones/odoo/odoo/.worktrees/master/`:

- `addons/web/static/src/core/utils/indexed_db.js` — Full `IndexedDB` class source: `read`, `write`, `getAllKeys`, `invalidate`, `execute`, `_checkVersion`, `IDBQuotaExceededError` (HIGH confidence)
- `addons/web/static/src/webclient/menus/menu_service.js` — `new IndexedDB("webclient_menu", session.registry_hash)` + `read`/`write` pattern (HIGH confidence)
- `addons/web/static/src/core/network/rpc_cache.js` — `IDBQuotaExceededError` catch pattern + `execute` usage (HIGH confidence)
- `addons/web/static/src/core/network/download.js` — `downloadFile(data, filename, mimetype)` implementation, Blob + object URL lifecycle (HIGH confidence)
- `addons/web/static/src/core/confirmation_dialog/confirmation_dialog.js` — `ConfirmationDialog` props, `AlertDialog` variant (HIGH confidence)
- `addons/web/static/src/core/file_input/file_input.js` — `FileInput` server-upload pattern (confirmed: NOT suitable for local import) (HIGH confidence)
- `addons/web/static/src/core/utils/files.js` — `useFileUploader` uploads to server route; raw `FileReader` needed instead for local import (HIGH confidence)
- `addons/web/static/src/core/utils/indexed_db.js` lines 215-244 — `_invalidate` implementation: `objectStore.clear()` for each named table (HIGH confidence)
- `addons/mail/static/lib/idb-keyval/idb-keyval.js` — idb-keyval confirmed vendored in mail addon; not usable from `@web/*` path (HIGH confidence)
- `addons/point_of_sale/static/src/app/models/utils/indexed_db.js` — POS-specific IndexedDB, batch-oriented, not appropriate for this use case (HIGH confidence)

---

## v1.2 Stack (Prior Milestone — Retained for Reference)

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.2)
**Researched:** 2026-02-22

---

### v1.2 Scope: Native Odoo Theming

This document adds a v1.2 section focused on replacing hardcoded Catppuccin Mocha colors with Odoo's Bootstrap CSS variable theming system. The v1.1 stack content (standalone OWL app, bus.bus, sidebar tree, asset bundle) follows at the bottom and is not re-researched.

---

### v1.2 Recommended Stack

#### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `web.assets_web_dark` asset bundle | Odoo master + web_enterprise | Provides fully compiled dark-mode CSS | The dark bundle re-compiles ALL SCSS with dark variable values injected before light ones via `web.dark_mode_variables`. This is Odoo's official mechanism — used by the webclient, POS, and all enterprise modules. Loading this bundle instead of `web.assets_web` gives a complete dark theme with zero extra SCSS authoring. |
| Bootstrap 5 CSS custom properties (`--body-bg`, `--border-color`, etc.) | Bootstrap 5 (no `bs-` prefix in Odoo) | Runtime color tokens that switch between light and dark without SCSS re-compilation | Odoo sets `$variable-prefix: ''` which strips the `bs-` prefix, so all Bootstrap CSS custom properties are unprefixed: `var(--body-bg)`, `var(--body-color)`, `var(--border-color)`. These are emitted at `:root` by Bootstrap and automatically carry dark values when the dark bundle is loaded. Using them in app SCSS means the app adapts for free as the bundle switches. |
| `request.env['ir.http'].color_scheme()` | web_enterprise `ir_http.py` | Server-side detection of user's color preference | Returns `'light'` or `'dark'`. Reads the `color_scheme` cookie first, then falls back to `res.users.settings.color_scheme`. The community `ir.http` base always returns `'light'`; the enterprise override (in `web_enterprise/models/ir_http.py`) adds the cookie and user preference. Called once at page render time — no JS needed. |
| `color_scheme` cookie | Browser cookie set by `web_enterprise` controller | Persists user's light/dark toggle preference across page loads | Set by `web_enterprise/controllers/home.py` on every `/web` or `/odoo` request. The cookie value is `'dark'` or `'light'`. Reading it server-side via `color_scheme()` and loading the correct bundle server-side is the same approach used by the main webclient template (`web.webclient_bootstrap` lines 314-319). |

#### Supporting Libraries (No New Dependencies)

No new npm packages, Python libraries, or Odoo modules required. All the infrastructure is already present:

| Library | Purpose | Status |
|---------|---------|--------|
| `web.dark_mode_variables` asset bundle | Injects dark SCSS variable overrides before light variables — enables full SCSS recompilation with dark palette | Defined by `web_enterprise/__manifest__.py`. Available because `ai_debug` already depends on `ai_app` which depends on `web_enterprise`. |
| `web_enterprise/static/src/scss/primary_variables.dark.scss` | Declares dark-mode overrides for all `$o-gray-*`, `$o-webclient-background-color`, `$o-view-background-color`, etc. | Included by `web.dark_mode_variables`; compiled automatically when the dark bundle is loaded. |

---

### Pattern 1: Conditional Bundle Loading in Controller + Template

This is the exact same mechanism used by `web.webclient_bootstrap`. The controller calls `color_scheme()` and passes it to the template. The template conditionally loads the light or dark bundle.

#### Controller Change (`controllers/main.py`)

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
        color_scheme = request.env['ir.http'].color_scheme()
        return request.render('ai_debug.index', {
            'session_info': session_info,
            'color_scheme': color_scheme,
        })
```

**Why `color_scheme()` not cookie read directly:** `color_scheme()` encapsulates the full priority chain — cookie → user preference → default. The cookie alone misses the user's explicit preference set in the Odoo settings panel. Using the method is the authoritative source, identical to how the main webclient does it.

**Why `debug` is not passed explicitly:** QWeb auto-injects `debug` from `request.session.debug` into the template rendering context (`ir_qweb.py` line 1297: `values.setdefault('debug', debug)`). No need to pass it manually.

#### Template Change (`views/ai_debug_index.xml`)

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
                <t t-if="color_scheme == 'dark'">
                    <t t-call-assets="ai_debug.assets_dark" t-js="false"/>
                    <t t-call-assets="ai_debug.assets" t-css="false"/>
                </t>
                <t t-else="">
                    <t t-call-assets="ai_debug.assets"/>
                </t>
            </head>
            <body/>
        </html>
    </template>
</odoo>
```

**Why split CSS and JS for dark mode:** The dark bundle replaces the CSS only — the JS is identical in both themes. The split `t-js="false"` / `t-css="false"` pattern mirrors `web.webclient_bootstrap` exactly (lines 312-319 of `webclient_templates.xml`). In dark mode: load dark CSS from `ai_debug.assets_dark`, load JS from `ai_debug.assets`. In light mode: load the single bundle normally (which includes both).

**Why not load both dark and light CSS with a media query:** Odoo does not use `prefers-color-scheme` media queries. The dark/light choice is explicit via a user cookie, not an OS preference. The server decides which bundle to load based on the cookie value.

#### Asset Bundle Changes (`__manifest__.py`)

```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        'ai_debug/static/src/app/**/*.scss',
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
    ],
    # Dark mode bundle: recompiles all SCSS with dark variable values
    'ai_debug.assets_dark': [
        ('include', 'web.dark_mode_variables'),  # injects dark vars before light
        ('include', 'ai_debug.assets'),           # recompiles full bundle with dark palette
    ],
    'web.assets_backend': [
        'ai_debug/static/src/debug_menu_button.js',
    ],
},
```

**Why `('include', 'web.dark_mode_variables')` first:** `web.dark_mode_variables` uses `('before', ...)` positioning to place dark SCSS variable files immediately before their light counterparts in the file order. When `ai_debug.assets_dark` includes this bundle first, the dark SCSS variable files are loaded before the light SCSS compiles, so `$o-gray-100` etc. carry their dark values for the entire compilation. This is identical to how `web.assets_web_dark` works in the enterprise manifest.

**Why the dark bundle includes `ai_debug.assets` not `web.assets_web_dark`:** `web.assets_web_dark` includes `web.assets_web` which includes `main.js` and `start.js` — the webclient bootstrappers that conflict with the standalone app's own `main.js`. Using `ai_debug.assets` as the base keeps the standalone app's own bootstrap intact while still getting the dark variable recompilation.

**Why `web.dark_mode_variables` is safe to include:** `web.dark_mode_variables` is defined by `web_enterprise/__manifest__.py`. The `ai_debug` module depends on `ai_app` which depends on `web_enterprise`. The bundle is always present.

---

### Pattern 2: Replacing Hardcoded Colors with CSS Custom Properties

The app.scss currently uses hardcoded Catppuccin Mocha hex values. These map to Bootstrap/Odoo CSS custom properties that automatically carry dark or light values depending on which bundle is loaded.

#### Color Mapping: Catppuccin Mocha → Odoo CSS Custom Properties

| Catppuccin Hex | Semantic Role | Replace With | Notes |
|----------------|---------------|--------------|-------|
| `#1e1e2e` | App background, sidebar bg | `var(--body-bg)` | Bootstrap `:root` — `$body-bg` → `$o-webclient-background-color`. Dark: `#1B1D26`. Light: `#F9FAFB`. |
| `#181825` | Header background, deeper panel bg | `var(--secondary-bg)` | Bootstrap `:root` — darker surface than body. Dark: derived from `$o-gray-200 = #262A36` (actually, secondary-bg is darker). Use `color-mix(in srgb, var(--body-bg), black 30%)` or a custom CSS var. |
| `#11111b` | Detail panel background (deepest) | `var(--tertiary-bg)` or custom | Bootstrap emits `--tertiary-bg`. Alternatively define `--ai-debug-deep-bg` as a CSS var anchored to `var(--body-bg)`. |
| `#313244` | Borders and dividers | `var(--border-color)` | Bootstrap `:root` — `$border-color` → `$o-gray-300`. Dark: `$o-gray-300 = #3C3E4B`. Light: `$d8dadd`. |
| `#cdd6f4` | Primary text | `var(--body-color)` | Bootstrap `:root` — `$body-color` → `$o-main-text-color` → `$o-gray-900`. Dark: `#E4E4E4`. Light: `#111827`. |
| `#a6adc8` | Secondary text, monospace content | `var(--secondary-color)` | Bootstrap 5.3 `:root` variable. Falls back to `color-mix(in srgb, var(--body-color), transparent 40%)`. |
| `#585b70` | Muted / dimmed text, placeholder | `var(--tertiary-color)` | Bootstrap 5.3 `:root` variable. Or use `.text-muted` Bootstrap class directly in templates. |
| `#6c7086` | Section headers, labels | `color-mix(in srgb, var(--body-color), transparent 50%)` | No direct Bootstrap var maps here. Define as `--ai-debug-label-color`. |
| `#89b4fa` | Accent / selected indicator / link | `var(--link-color)` | Bootstrap `:root` — `$link-color` → `$o-main-link-color` → `$o-enterprise-action-color`. Dark: `#02c7b5`. Light: `#017e84`. |
| `#a6e3a1` | Success state | `var(--success)` | Bootstrap theme color. Dark: `#1dc959`. Light: Bootstrap default. |
| `#f38ba8` | Error / danger state | `var(--danger)` | Bootstrap theme color. Dark: `#b83232`. Light: Bootstrap default. |
| `#f9e2af` | Warning state | `var(--warning)` | Bootstrap theme color. Dark: `#FBB56A`. Light: Bootstrap default. |

**Confidence:** HIGH for `--body-bg`, `--body-color`, `--border-color`, `--link-color`, `--success`, `--danger`, `--warning` — these are established Bootstrap 5 `:root` variables. MEDIUM for `--secondary-color`, `--tertiary-color`, `--secondary-bg`, `--tertiary-bg` — these exist in Bootstrap 5.3 but may not all be emitted by Odoo's Bootstrap configuration (`$enable-dark-mode: false` suppresses Bootstrap's own dark mode variables in `_root.scss`; Odoo implements its own scheme).

**Important caveat on secondary/tertiary Bootstrap vars:** Odoo sets `$enable-dark-mode: false` in `bootstrap_overridden.scss` line 60. This disables Bootstrap 5's built-in `[data-bs-theme="dark"]` block in `_root.scss`, which means `--secondary-bg`, `--tertiary-bg`, `--secondary-color`, `--tertiary-color` may not be emitted at `:root`. Verify in the compiled bundle before using. Safe fallback: define component-scoped CSS custom properties anchored to `$o-gray-*` SCSS variables directly in the module's SCSS files, which get the correct values at compile time.

#### SCSS Approach for Compile-Time Color Values

For values with no direct CSS custom property match, use SCSS variables directly in the app's SCSS. These get the correct dark/light values at compile time because `web.dark_mode_variables` is included first:

```scss
// Use SCSS variables for values that won't have a CSS custom property
// These compile to the correct light or dark hex values automatically
// because web.dark_mode_variables overrides them before this file compiles.

.ai-debug-header {
    background-color: $o-gray-200;  // Light: #e7e9ed, Dark: #262A36
    border-bottom: 1px solid $o-gray-300;  // Light: #d8dadd, Dark: #3C3E4B
}

.ai-debug-app {
    background-color: $o-gray-100;  // Light: #F9FAFB, Dark: #1B1D26
    color: $o-gray-900;  // Light: #111827, Dark: #E4E4E4
}
```

**Why SCSS variables are safe:** When `ai_debug.assets_dark` is loaded, `web.dark_mode_variables` runs `('before', primary_variables.scss, primary_variables.dark.scss)`, which makes `$o-gray-100 = #1B1D26` during the entire SCSS compilation of `ai_debug.assets`. The compiled CSS has the dark value baked in. This is the same mechanism used by every enterprise dark SCSS file.

#### Dark-Specific Override Pattern (`.dark.scss` files)

For colors that cannot be expressed as CSS custom properties or SCSS variables — such as complex rgba() calls with specific alpha values tied to the Catppuccin palette — create `.dark.scss` override files. These are only included in the dark bundle:

```scss
// ai_debug/static/src/app/app.dark.scss
// Overrides for colors that differ from the SCSS variable mappings

.ai-tree-row {
    &.selected {
        // In light mode: uses default Bootstrap active bg
        // In dark mode: use Odoo's dark action color tint
        background-color: rgba($o-enterprise-action-color, 0.15);
        border-left-color: $o-enterprise-action-color;
    }

    &.ancestor {
        background-color: rgba($o-enterprise-action-color, 0.05);
    }
}

.ai-json-key { color: $o-action; }
```

**Why `.dark.scss` files are automatically included:** `ai_debug.assets_dark` includes `ai_debug.assets` which uses `'ai_debug/static/src/app/**/*.scss'`. This glob includes `.dark.scss` files. To exclude them from the light bundle, add `('remove', 'ai_debug/static/src/app/**/*.dark.scss')` to `ai_debug.assets`, identical to how `web_enterprise/__manifest__.py` line 46 does `('remove', 'web_enterprise/static/src/**/*.dark.scss')`.

---

### Pattern 3: Color Scheme Cookie Detection

#### Server-Side (Recommended Approach)

The controller reads the color_scheme cookie via `ir.http.color_scheme()` and conditionally loads the correct asset bundle server-side. No JavaScript cookie parsing needed at mount time:

```python
color_scheme = request.env['ir.http'].color_scheme()
return request.render('ai_debug.index', {'color_scheme': color_scheme, ...})
```

The template then loads `ai_debug.assets_dark` (CSS only) or `ai_debug.assets` based on `color_scheme == 'dark'`. The app JS never needs to know which theme is active — the CSS just works.

#### Client-Side Cookie Parsing (Only If Needed)

If any JS component needs to know the current color scheme at runtime (e.g., for a JS charting library that can't use CSS variables), parse the cookie client-side:

```javascript
// Read color_scheme cookie — same logic as webclient_offline template uses
function getColorScheme() {
    const match = document.cookie.match(/(?:^|;\s*)color_scheme=([^;]+)/);
    return match ? match[1] : 'light';
}
```

**Why not use `prefers-color-scheme` media query in JS:** Odoo's color scheme is user-controlled via cookie/preference, not OS-controlled. A user might have OS in dark mode but Odoo in light mode. The cookie is authoritative.

**Why not use a service or OWL reactive state for color scheme in the standalone app:** The color scheme is fixed for the lifetime of a page load. The correct bundle is loaded at page render time. No runtime switching occurs. There is nothing to react to in OWL.

---

### What NOT to Use (v1.2)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Custom theme system (CSS-in-JS, emotion, styled-components, etc.) | Introduces a dependency outside Odoo's toolchain. Odoo's SCSS pipeline is the only supported path for theming. | Odoo SCSS variables and Bootstrap CSS custom properties. |
| Third-party CSS frameworks (Tailwind, Bulma, etc.) | Would conflict with Odoo's Bootstrap-based layout. The standalone app already inherits Bootstrap via `web.assets_backend`. | Odoo's Bootstrap 5 classes and CSS custom properties already present in the bundle. |
| `@media (prefers-color-scheme: dark)` CSS queries | Odoo does not use OS dark mode preference. The user's color_scheme cookie controls the theme. Using a media query creates a split where OS preference and Odoo preference diverge. | Server-side bundle selection based on `color_scheme` cookie. |
| Inline styles for theme-sensitive colors | Defeats the variable system entirely. Inline styles always override CSS custom property defaults and require JS to switch. | CSS custom property references in SCSS rules. |
| `web.assets_web_dark` directly in the standalone app template | `web.assets_web_dark` includes `web.assets_web` which includes `main.js` and `start.js` — the webclient bootstrappers. Loading them in the standalone app's page creates a double bootstrap conflict. | The custom `ai_debug.assets_dark` bundle that includes `web.dark_mode_variables` + `ai_debug.assets`. |
| Hardcoding Catppuccin dark values in `.dark.scss` overrides | If the user has a light-mode Odoo instance, the dark SCSS file never loads — which is correct. But if you hardcode exact Catppuccin hex values in `.dark.scss`, you lose the ability to match Odoo's actual dark palette. | `$o-gray-*` SCSS variables and Bootstrap CSS custom property references in `.dark.scss` overrides. |

---

### Version Compatibility (v1.2)

| Pattern | Odoo Version | Notes |
|---------|--------------|-------|
| `ir.http.color_scheme()` method | web_enterprise master | Base method in community always returns `'light'`. Enterprise override adds cookie and user preference. Verified in `web_enterprise/models/ir_http.py`. |
| `color_scheme` cookie format | web_enterprise master | Set by `web_enterprise/controllers/home.py` on every `/web` request. Values: `'dark'` or `'light'`. |
| `web.dark_mode_variables` bundle | web_enterprise master | Defined in `web_enterprise/__manifest__.py` lines 61-67. Required for the `ai_debug.assets_dark` approach. |
| `web.assets_web_dark` bundle | web (community) + web_enterprise | Base `web.assets_web_dark` defined in `web/__manifest__.py` line 339. Enterprise adds dark variable injection via `web.dark_mode_variables`. Only the enterprise version has meaningful dark colors. |
| Bootstrap CSS custom properties (no `bs-` prefix) | Odoo 16+ master | `$variable-prefix: ''` in `web/static/src/scss/bootstrap_overridden.scss` line 51. CSS vars are `--body-bg` not `--bs-body-bg`. |
| `$o-gray-*` SCSS variables | web_enterprise master | Defined in `web_enterprise/static/src/scss/primary_variables.scss`. Dark overrides in `primary_variables.dark.scss`. Available in any SCSS file compiled within the asset bundle. |
| `$enable-dark-mode: false` | Odoo 16+ | Set in `web/static/src/scss/bootstrap_overridden.scss` line 60. Disables Bootstrap 5's own dark mode `:root` block. Odoo rolls its own dark mode via separate compiled bundles. |

---

### Sources (v1.2)

All patterns verified against Odoo master source, not training data or web search:

- `addons/web/views/webclient_templates.xml` lines 312-319 — conditional `color_scheme == 'dark'` → `assets_web_dark` pattern (HIGH confidence)
- `addons/point_of_sale/views/pos_assets_index.xml` lines 36-41 — standalone app conditional bundle loading on `pos_color_scheme` cookie (HIGH confidence)
- `web_enterprise/models/ir_http.py` lines 22-31 — `color_scheme()` method: cookie → user preference → default (HIGH confidence)
- `web_enterprise/controllers/home.py` lines 13-14 — `color_scheme` cookie set on every `/web` request (HIGH confidence)
- `web_enterprise/__manifest__.py` lines 44-75 — `web.dark_mode_variables`, `web.assets_web_dark`, `('remove', '**/*.dark.scss')` patterns (HIGH confidence)
- `addons/web/__manifest__.py` lines 339-342 — base `web.assets_web_dark` definition: includes `web.assets_web` + `**/*.dark.scss` (HIGH confidence)
- `web_enterprise/static/src/scss/primary_variables.dark.scss` — dark-mode $o-gray-* values: gray-100=#1B1D26, gray-200=#262A36, gray-300=#3C3E4B, gray-900=#E4E4E4 (HIGH confidence)
- `addons/web/static/src/scss/bootstrap_overridden.scss` lines 51, 60 — `$variable-prefix: ''` (no bs- prefix), `$enable-dark-mode: false` (HIGH confidence)
- `addons/web/static/lib/bootstrap/scss/_root.scss` — Bootstrap 5 `:root` CSS custom property declarations (HIGH confidence)
- `web_enterprise/static/src/core/notebook/notebook.dark.scss` — component-scoped dark override using `$o-*` SCSS vars (HIGH confidence)
- `enterprise/account_reports/static/src/scss/account_return.scss` — `var(--body-bg)`, `var(--body-color)`, `var(--border-color)` usage in enterprise SCSS (HIGH confidence)

---

## v1.1 Stack (Prior Milestone — Retained for Reference)

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1)
**Researched:** 2026-02-20

---

### What v1.1 Research Covers

v1.1 changes three things from v1.0:
1. Replace the `ir.actions.client` backend panel with a **true standalone OWL app** at `/ai-debug` (own HTML page, own asset bundle, own HTTP controller — same pattern as `point_of_sale.index`)
2. Carry **full payloads** over `bus.bus` instead of summary-only (no DB means no lazy ORM reads)
3. Render a **sidebar tree** (Loop > Iteration > Tool Call) with a master/detail layout

The v1.0 stack entries (generator yield passthrough, model inheritance, backend views) are NOT re-researched here. Only additions and changes are covered.

---

### Core Technologies (v1.1)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| OWL `mountComponent` | Odoo master (OWL 2.8.1) | Bootstrap standalone OWL app into `document.body` | `mountComponent` from `@web/env` creates its own OWL env, starts all registered services (including `bus_service`), and mounts the root component. Used identically by `point_of_sale/static/src/app/main.js` and `point_of_sale/static/src/customer_display/customer_display.js`. |
| Dedicated asset bundle (`ai_debug.assets`) | Odoo master | Isolate standalone app JS/CSS from backend | The standalone page loads exactly one `<t t-call-assets="..."/>` tag pointing to a module-defined bundle. POS uses `point_of_sale.assets_prod`; ai_debug uses `ai_debug.assets`. The bundle includes `web.assets_backend` for OWL, session, bus services. |
| HTTP controller (`type='http'`, `auth='user'`) | Odoo master | Serve the `/ai-debug` HTML page | `request.render('ai_debug.index', context)` renders the QWeb template. `auth='user'` enforces login. Exact same pattern as `PosController.pos_web()` in `point_of_sale/controllers/main.py`. |
| QWeb HTML template (`<template id="ai_debug.index">`) | Odoo master | Standalone HTML page shell | Declares `<!DOCTYPE html>`, injects `odoo` global with `csrf_token` and `__session_info__`, calls `t-call-assets`. Same structure as `point_of_sale/views/pos_assets_index.xml`. |
| `bus_service` + `bus_service.subscribe()` | Odoo master | Receive full-payload events in standalone app | The bus service registers itself into the service registry and is started automatically by `mountComponent` → `startServices`. Works identically in standalone and backend contexts. |

### What NOT to Use (v1.1)

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `ir.actions.client` for the standalone app | Client actions render inside the Odoo backend layout (navbar, breadcrumbs, action manager). The requirement is a true standalone page with no Odoo chrome — like POS. | HTTP controller + QWeb template + `mountComponent` |
| `mount` (from `@odoo/owl`) instead of `mountComponent` | `mount` skips `makeEnv` and `startServices`. The `bus_service`, `rpc`, and all other services are not started. | `mountComponent` from `@web/env` |

### Sources (v1.1)

- `addons/point_of_sale/views/pos_assets_index.xml` — QWeb standalone HTML template structure
- `addons/point_of_sale/controllers/main.py` — HTTP controller `pos_web()` pattern
- `addons/point_of_sale/static/src/app/main.js` — `mountComponent` with `whenReady` bootstrap
- `addons/web/static/src/env.js` lines 226-250 — `mountComponent` implementation
- `addons/bus/static/src/services/bus_service.js` lines 174-181 — `addChannel()` starts connection
- `addons/bus/models/bus.py` lines 92-188 — pg_notify carries channel names only

---

*Stack research for: AI Debugger — subagent hierarchy visualization (v1.4)*
*Researched: 2026-02-23*
*All patterns verified against enterprise and custom source code at `/Users/joseph/clones/odoo/`*
