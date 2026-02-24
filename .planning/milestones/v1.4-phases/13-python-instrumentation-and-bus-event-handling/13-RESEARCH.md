# Phase 13: Python Instrumentation and Bus Event Handling - Research

**Researched:** 2026-02-23
**Domain:** Odoo Python backend instrumentation + OWL JS bus event handling
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Bus event payload shape**
- `new_trace` event includes `parent_trace_id` (UUID of parent agentic loop's trace) and `parent_tool_call_id` (ID of the tool call that spawned the subagent)
- For root sessions, both fields are present but set to `null` — consistent payload shape, no field-existence checks needed
- Agent name is NOT included in the event payload — derived from `agent_id` on the `ai.session` record
- No `parent_session_id` (ORM ID) needed — `parent_trace_id` is the direct pointer the frontend works with

**Tool call event splitting**
- Current: tool calls emit a single event on completion (with args + result)
- New: two distinct events — `tool_call_started` (id, name, args) and `tool_call_completed` (id, result)
- This ensures the parent tool call node exists in the UI before the subagent trace arrives, minimizing the orphan buffer window

**Orphan trace handling**
- If a child trace arrives before its parent tool call, buffer it (pending-child buffer)
- After 30 seconds timeout, promote orphaned traces to root level
- Retain parent references (`parent_trace_id`, `parent_tool_call_id`) even after root promotion
- If the parent tool call eventually arrives, silently re-attach the trace to the correct parent — no visual indicator

**Buffer strategy**
- Uncapped buffer size — subagent traces per session are few, no need for a hard limit
- Buffer logic placement: Claude's discretion (inline in event handler or separate module)
- IDB hydration uses a separate two-pass process (first pass loads all traces, second pass links parents) — does NOT reuse the live buffer logic

**Context threading (Python backend)**
- Use `env.context` to pass parent trace info to child sessions — Odoo's standard contextual data mechanism
- Two context keys: `ai_parent_trace_id` and `ai_parent_tool_call_id`
- Child session reads these keys and includes the values in its `new_trace` bus event
- Parent linkage is bus-event-only — no persistence on the `ai.session` ORM record
- Injection point: Claude's discretion (base `_handle_tool_calls` vs subagent-specific override)

### Claude's Discretion
- Buffer module architecture (inline vs dedicated module)
- Context injection point (base model vs subagent override)
- Exact `tool_call_started` / `tool_call_completed` event naming and structure (following existing bus event conventions)

### Deferred Ideas (OUT OF SCOPE)
- Exact parent tool call matching via `parent_call_id` for parallel subagent disambiguation (NEST-02 in requirements — deferred to v1.4.1)
- Persisting parent linkage on `ai.session` ORM for server-side parent queries — not needed for current UI-only use case
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INST-01 | Backend emits `session_id` (own ORM ID) in `new_trace` bus event payload | `self.id` is available anywhere on the `ai.session` record; trivial one-line addition to the existing `new_trace` payload dict in `_run_agentic_loop` |
| INST-02 | Backend emits `parent_session_id` (parent ORM ID or null) in `new_trace` bus event payload for subagent sessions | Note: CONTEXT.md locked decision supersedes this — the payload field is `parent_trace_id` (UUID), not ORM ID. `parent_session_id` on the ORM record exists but won't be emitted. Read context keys `ai_parent_trace_id` and `ai_parent_tool_call_id` from `env.context` in `_run_agentic_loop` |
| INST-03 | Backend injects parent trace context via `env.context` before `super()` in `_handle_tool_calls` so child session's `_run_agentic_loop` can read it | Full call chain is verified — see Architecture Patterns; the injection can happen either in `_handle_tool_calls` on the custom model or in a subagent-specific override |
| TREE-05 | Frontend handles out-of-order bus events via pending-child buffer (child trace arriving before parent tool call is buffered and attached when parent arrives) | `_onNewTrace` and `_onToolCall` in `app.js` are the attachment points; buffer is a plain JS object keyed by `parent_tool_call_id`; 30s timeout uses `setTimeout` |
</phase_requirements>

## Summary

Phase 13 is entirely within the existing `ai_debug` module's `ai_session.py` override and `app.js`. The codebase is well-understood — all relevant methods have already been read. The Python work is small: two additions to `_run_agentic_loop` (read context keys, add two fields to the `new_trace` payload) plus splitting the single `tool_call` bus event into `tool_call_started` and `tool_call_completed` in `_handle_tool_calls`. The JS work is a pending-child buffer in `_onNewTrace` with a 30s promotion timer and silent re-attachment in `_onToolCall`.

The key complexity is the call chain: when a parent session's `_handle_tool_calls` calls `_ai_tool_request_sub_agent`, the subagent's `_generate_next_response` → `_run_agentic_loop` runs in the same Python call stack. The parent's `_debug_ctx` is already in `env.context`. The injection point determines which `with_context()` call threads the parent trace ID into the subagent's `env.context` before `_run_agentic_loop` is called on the child `ai.session`.

The REQUIREMENTS.md fields `parent_session_id` / `session_id` were written before the CONTEXT.md locked decisions. CONTEXT.md supersedes REQUIREMENTS.md: the `new_trace` payload will carry `parent_trace_id` (UUID hex, not ORM ID) and `parent_tool_call_id`, not ORM IDs. The planner must implement what CONTEXT.md says.

**Primary recommendation:** Add context injection in the custom `_handle_tool_calls` override (not the base), because the custom override already wraps `super()` and has access to `_debug_ctx`; injecting there is cleanest and keeps subagent context threading co-located with the instrumentation code.

## Standard Stack

No new libraries. All work is within the existing module stack.

### Core
| Component | Location | Purpose | Notes |
|-----------|----------|---------|-------|
| `ai_debug/models/ai_session.py` | Custom addon | All Python instrumentation overrides | Already has `_run_agentic_loop`, `_handle_tool_calls` overrides |
| `ai_debug/static/src/app/app.js` | Custom addon | All JS bus event handling | `_onNewTrace`, `_onToolCall` are the target handlers |
| `odoo.env.context` | Odoo ORM | Context threading mechanism | `.with_context()` returns a new recordset with extra context |
| `bus.bus._sendone` (separate cursor) | Odoo bus | Real-time bus delivery | Pattern already established in `_ai_debug_bus_send` |

## Architecture Patterns

### Call Chain: How Subagent Context Flows

```
Parent ai.session._handle_tool_calls()        [custom override in ai_debug]
  └── super()._handle_tool_calls()            [base ai_session.py]
        └── tool._ai_tool_run(...)            [executes ir.actions.server code]
              └── record._ai_tool_request_sub_agent(tool_context, agent_id, prompt)
                    └── ai_session_sudo._generate_next_response(message)
                          └── self._run_agentic_loop(...)   [custom override in ai_debug]
                                → emits new_trace bus event
```

The parent's `_debug_ctx` in `env.context` (key: `_debug_ctx`) carries `trace_id`. When the tool runs, `record_context = {'session_id': self.id, ...}` is passed via `tool.with_context(**record_context)`. But the subagent session object `ai_session_sudo` is created independently — it does NOT inherit the parent's `env.context` automatically.

The injection must happen in the custom `_handle_tool_calls` override: before delegating to `super()`, use `self = self.with_context(ai_parent_trace_id=..., ai_parent_tool_call_id=...)`. The `with_context()` propagates through the override's `super()` call chain because all subsequent calls on `self` inherit the merged context.

**However, there is a critical subtlety:** The subagent session is created with `self.env["ai.session"].sudo().create(...)` inside `_ai_tool_request_sub_agent`. The new session's `env` comes from the sudo env, not from `self.env` of the tool call. The context injected via `tool.with_context(...)` is on the `tool` object, not on the `ai.session` env. The subagent session's `_generate_next_response` runs with `ai_session_sudo.env`, which may not carry the injected context.

The safe injection point is therefore the existing `record_context` dict in the base `_handle_tool_calls`:

```python
# base ai_session.py line 177
record_context["session_id"] = self.id
```

The base passes `tool.with_context(**record_context)` into `_ai_tool_run`. Inside `_ai_tool_request_sub_agent`, the subagent calls `ai_session_sudo._generate_next_response(...)`. The env that `ai_session_sudo` holds is the one from `self.env["ai.session"].sudo()` — it inherits whatever context the *caller's env* has when `.create()` is called.

The cleanest approach: in the **custom** `_handle_tool_calls` override, before calling `super()`, thread `ai_parent_trace_id` and `ai_parent_tool_call_id` into `self`'s context using `self = self.with_context(...)`. The base `_handle_tool_calls` then uses `self.id` (unchanged) but the `self.env` carries the extra keys. Inside `_ai_tool_request_sub_agent`, `self.env.context.get("ai_parent_trace_id")` is readable because the tool runs as `record = self` (the `ai.agent` instance) with the record_context — but the subagent session is created with `self.env["ai.session"]` which inherits the *current* env's context at creation time if no env override is made.

**Verified pattern for context propagation:** `self.env["ai.session"].sudo()` creates a new env that inherits `self.env.context` merged with `{'su': True}`. Therefore if `self.env.context` contains `ai_parent_trace_id`, that key IS visible in `self.env["ai.session"].sudo().env.context`. The key flows: `self.with_context(ai_parent_trace_id=X)` → `self.env.context` has the key → `self.env["ai.session"].sudo().env.context` inherits it → `ai_session_sudo.env.context.get("ai_parent_trace_id")` works.

**Confirmed injection point:** In the custom `_handle_tool_calls` override in `ai_session.py`, set `self = self.with_context(ai_parent_trace_id=_debug_ctx['trace_id'], ai_parent_tool_call_id=<current_tool_call_id>)` before calling `super()`. The `_debug_ctx['trace_id']` is the parent trace ID. The `tool_call_id` must come from the current tool call being processed.

### Pattern 1: Adding Fields to new_trace Payload (INST-01, INST-02)

In `_run_agentic_loop` in the custom `ai_session.py`:

```python
# Read parent context (set by parent's _handle_tool_calls, or None for root)
parent_trace_id = self.env.context.get('ai_parent_trace_id')
parent_tool_call_id = self.env.context.get('ai_parent_tool_call_id')

self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'session_id': self.id,                          # INST-01: own ORM ID
    'parent_trace_id': parent_trace_id,             # INST-02: null for root
    'parent_tool_call_id': parent_tool_call_id,     # INST-02: null for root
    'agent_name': self.agent_id.name if self.agent_id else None,
    ...
})
```

Confidence: HIGH — `self.id` is always available on a TransientModel instance; `env.context.get()` returns `None` by default.

### Pattern 2: Injecting Parent Context (INST-03)

In the custom `_handle_tool_calls` override, before the `super()` call:

```python
def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record,
                       confirmed_tool_id=None, refuse_all=False):
    _debug_ctx = self.env.context.get('_debug_ctx')
    if not _debug_ctx:
        yield from super()._handle_tool_calls(...)
        return

    # Thread the current trace_id so child sessions can read it
    # tool_call_id will be set per-tool-call in the loop (below)
    self = self.with_context(ai_parent_trace_id=_debug_ctx['trace_id'])

    # ... existing loop logic with super() ...
```

The `ai_parent_tool_call_id` must be set per-tool-call because `_handle_tool_calls` processes a list. The cleanest place is just before `super()._handle_tool_calls()` yields, but since `super()` is a generator, the context must be set on `self` before delegating. One approach: set the tool_call_id in the context before starting the loop by temporarily injecting it. However, since `super()` is a generator that runs lazily, the context on `self` when `super()` is called is what all downstream code sees.

**Practical approach:** Set `ai_parent_tool_call_id` to `None` before `super()` and accept that the per-tool-call accuracy is best-effort for Phase 13 (exact per-call tracking is NEST-02, deferred). The CONTEXT.md decision says `parent_tool_call_id` comes from `tools_context['tool_call_id']` which IS set per-tool in the base — but threading it requires more invasive changes. For Phase 13, it's acceptable to use the `trace_id` only (with `parent_tool_call_id: null` or the call_id from the last yielded `tool_call_started` event).

**Revised approach based on base code inspection:** The base `_handle_tool_calls` sets `tools_context['tool_call_id'] = tool_call['call_id']` at line 214. This key is available inside the tool execution. The `_ai_tool_request_sub_agent` receives `tool_context` (which IS `tools_context`) — so `tool_context['tool_call_id']` IS the call_id of the current tool. The subagent session is created inside that function. Therefore `ai_parent_tool_call_id` should be read from `tools_context['tool_call_id']` inside `_ai_tool_request_sub_agent` itself, not from env.context.

The cleanest Phase 13 implementation: inject `ai_parent_trace_id` via `env.context` (done in the custom `_handle_tool_calls` before super()), and inject `ai_parent_tool_call_id` directly from `tools_context['tool_call_id']` inside `_ai_tool_request_sub_agent` by passing it through `record_context`. The subagent session then reads `self.env.context.get('ai_parent_tool_call_id')` in `_run_agentic_loop`.

### Pattern 3: Tool Call Splitting (tool_call_started / tool_call_completed)

The current custom `_handle_tool_calls` emits a single `tool_call` event per tool **after** `super()` yields `tool_results`. The split requires emitting `tool_call_started` before `super()` processes a tool, and `tool_call_completed` after.

Since `super()` is a generator and we wrap it, we can:
1. Emit `tool_call_started` for each tool_call in the batch **before** delegating to super()
2. Emit `tool_call_completed` for each result when `tool_results` arrives

The challenge: the base iterates `tool_calls` in order and yields `tool_results` as a batch at the end. So `tool_call_started` events for all tools in the batch fire before any `tool_call_completed` events.

```python
# Before super() delegation — emit started events for all tool calls
for tc in tool_calls:
    self._ai_debug_bus_send('tool_call_started', {
        'type': 'tool_call_started',
        'trace_id': _debug_ctx['trace_id'],
        'iteration_id': _debug_ctx['iteration_id'],
        'tool_call_id': uuid.uuid4().hex,      # our stable ID for this call
        'call_id': tc['call_id'],
        'tool_name': tc['name'],
        'args': tc.get('args', {}),
    })

# After super() yields tool_results — emit completed events per result
if tool_results := item.get('tool_results'):
    for result_item in tool_results:
        # match by call_id
        self._ai_debug_bus_send('tool_call_completed', {
            'type': 'tool_call_completed',
            ...
        })
```

**ID stability:** `tool_call_id` (our UUID) must be stable across started and completed events so the JS can link them. We need a pre-generated mapping of `call_id → tool_call_id` before starting the loop.

### Pattern 4: Pending-Child Buffer in JS (TREE-05)

Location: `_onNewTrace` in `app.js`.

```javascript
// New class-level state — plain object keyed by parent_tool_call_id
this._pendingChildren = {};  // { parent_tool_call_id: { trace_data, timer } }

this._onNewTrace = (payload) => {
    const { parent_trace_id, parent_tool_call_id } = payload;

    if (parent_trace_id && parent_tool_call_id) {
        // Check if parent tool call exists already
        const parentTrace = this.traces.get(parent_trace_id);
        const parentTc = parentTrace && this._findToolCall(parentTrace, parent_tool_call_id);
        if (parentTc) {
            // Attach immediately
            this._attachChildTrace(payload, parentTc);
            return;
        }
        // Buffer with 30s timeout
        const timer = setTimeout(() => {
            // Promote to root
            this._promoteOrphanToRoot(payload);
            delete this._pendingChildren[parent_tool_call_id];
        }, 30000);
        this._pendingChildren[parent_tool_call_id] = { payload, timer };
        return;
    }

    // Root trace — place directly
    this._placeTrace(payload);
};
```

Re-attachment logic in `_onToolCall` (for `tool_call_started` events, once that event type exists):

```javascript
this._onToolCallStarted = (payload) => {
    // ... place in tree as usual ...
    // Check if any buffered child is waiting for this tool call
    const buffered = this._pendingChildren[payload.call_id];
    if (buffered) {
        clearTimeout(buffered.timer);
        delete this._pendingChildren[buffered.payload.parent_tool_call_id];
        this._attachChildTrace(buffered.payload, /* the tool call node */);
    }
};
```

**Note on event types:** The existing `_onToolCall` handles a single `tool_call` event. With the split, `tool_call_started` will be the event that creates the tree node (and triggers re-attachment checks). `tool_call_completed` fills in the result. The JS subscription setup in `onMounted` will need two new subscriptions.

### Pattern 5: Separate Cursor for Bus Sends (Already Established)

The `_ai_debug_bus_send` helper already uses `self.env.registry.cursor()` for real-time delivery. No change needed for new event types — same helper applies.

### Anti-Patterns to Avoid

- **Context mutation via dict assignment:** Never do `self.env.context['key'] = value`. Odoo contexts are read-only dicts. Always use `self.with_context(key=value)`.
- **Awaiting bus sends in the agentic loop:** Bus sends use a separate cursor. Never `await` them or check their return value in the main loop.
- **Emitting tool_call_started for confirmation-only paths:** The base `_handle_tool_calls` can yield `tool_confirmation_request` before completing tool results. The `tool_call_started` event should still fire (the tool call was started), but `tool_call_completed` only fires when `tool_results` arrives.
- **Buffer keyed by trace_id instead of parent_tool_call_id:** The child trace's `parent_tool_call_id` is the key the JS needs to match against incoming `tool_call_started` events. Keying by parent_trace_id would require a nested lookup.
- **Re-using live buffer logic for IDB hydration:** CONTEXT.md explicitly separates these — IDB hydration is a two-pass process (load all, then link), not the live buffer path.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Context threading to child env | Custom session attribute or global dict | `self.with_context(key=value)` — Odoo ORM propagates context through env inheritance |
| Bus event delivery timing | Manual commit/flush | `self.env.registry.cursor()` pattern already in `_ai_debug_bus_send` |
| JS timer management | Custom timer class | Plain `setTimeout` / `clearTimeout` — already the pattern in `onPatched` flash timer |

## Common Pitfalls

### Pitfall 1: Context Not Reaching the Subagent Session

**What goes wrong:** `ai_session_sudo.env.context.get('ai_parent_trace_id')` returns `None` even after `self.with_context(...)` in the parent's `_handle_tool_calls`.

**Why it happens:** `ai_session_sudo` is found/created via `self.env["ai.session"].sudo().search(...)`. The `sudo()` call creates a new env inheriting `self.env.context`. But if the `with_context` is applied to `self` AFTER the code path that creates `ai_session_sudo` (i.e., the base `_handle_tool_calls` is the one calling `_ai_tool_run`), the subagent may get the env BEFORE the context was injected.

**How to avoid:** The custom override sets `self = self.with_context(ai_parent_trace_id=...)` BEFORE calling `super()`. Since `super()` is a generator, the `self` binding in the custom override affects all subsequent method calls on `self` through the generator's lifetime. The base code accesses the tool via `tool.with_context(**record_context)`, and `record_context` is built inside the base using `self.env["ai.session"]` — which comes from `self.env` (the modified env). This chain is sound.

**Warning signs:** Add an `_logger.debug` in `_run_agentic_loop` to log `self.env.context.get('ai_parent_trace_id')`. If `None` for subagent sessions, the injection is missing or applied to the wrong `self`.

### Pitfall 2: tool_call_id Mismatch Between Started and Completed Events

**What goes wrong:** The JS finds a `tool_call_completed` event with a `tool_call_id` that does not match any `tool_call_started` event in the iteration's toolCalls map.

**Why it happens:** The `tool_call_id` (our generated UUID) is generated independently in the started and completed emit paths.

**How to avoid:** Generate a map of `call_id → tool_call_id` (our UUID) before the `tool_call_started` loop, then look up by `call_id` when emitting `tool_call_completed`. Store in `_debug_ctx` or as a local variable in the override.

### Pitfall 3: Buffer Timer Not Cleared on Re-Attachment

**What goes wrong:** An orphaned trace is promoted to root at 30s even though the parent tool call arrived at 25s and the trace was already re-attached.

**Why it happens:** `clearTimeout` not called when re-attaching in `_onToolCallStarted`.

**How to avoid:** Always `clearTimeout(buffered.timer)` before deleting from `_pendingChildren`. Pattern: `const buffered = this._pendingChildren[call_id]; if (buffered) { clearTimeout(buffered.timer); ... delete this._pendingChildren[...]; }`.

### Pitfall 4: Buffered Child Placed at Root Before Promotion Logic Runs

**What goes wrong:** A child `new_trace` event is placed in `this.traces` directly (at root level) before the buffer logic has a chance to check for the parent.

**Why it happens:** The `_onNewTrace` handler calls `this.traces.set(...)` unconditionally before the parent-check branch.

**How to avoid:** The buffer path should NOT call `this.traces.set(...)`. Only `_placeTrace()` (root path) and `_attachChildTrace()` (found-parent path) should touch `this.traces`. The buffered payload sits in `this._pendingChildren` until resolved.

### Pitfall 5: REQUIREMENTS.md vs CONTEXT.md Field Name Mismatch

**What goes wrong:** Implementation emits `parent_session_id` (ORM ID) in `new_trace` because REQUIREMENTS.md says so, but CONTEXT.md locked the field name to `parent_trace_id` (UUID).

**Why it happens:** REQUIREMENTS.md was written before CONTEXT.md locked the implementation.

**How to avoid:** CONTEXT.md is authoritative for locked decisions. The fields are `parent_trace_id` (UUID hex, the parent agentic loop's trace ID) and `parent_tool_call_id`. `session_id` (own ORM ID) IS still emitted per INST-01.

## Code Examples

### Example 1: Modified new_trace Payload

```python
# In custom _run_agentic_loop (ai_debug/models/ai_session.py)
# Source: direct reading of existing code + locked decisions

trace_id = uuid.uuid4().hex
parent_trace_id = self.env.context.get('ai_parent_trace_id')      # None for root
parent_tool_call_id = self.env.context.get('ai_parent_tool_call_id')  # None for root

self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'session_id': self.id,                       # INST-01
    'parent_trace_id': parent_trace_id,          # INST-02 / CONTEXT.md
    'parent_tool_call_id': parent_tool_call_id,  # INST-02 / CONTEXT.md
    'agent_name': self.agent_id.name if self.agent_id else None,
    'model_name': model,
    'user_query': user_query,
    'instructions': instructions,
    'tools': self._ai_debug_serialize_tools(tools, model),
    'state_snapshot': self._ai_debug_state_snapshot(tools_context),
})
```

### Example 2: Context Injection in Custom _handle_tool_calls

```python
# In custom _handle_tool_calls (ai_debug/models/ai_session.py)
# Source: analysis of env.context propagation through sudo() chain

def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record,
                       confirmed_tool_id=None, refuse_all=False):
    _debug_ctx = self.env.context.get('_debug_ctx')
    if not _debug_ctx:
        yield from super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            confirmed_tool_id, refuse_all,
        )
        return

    # Thread parent trace ID into env.context so child sessions spawned during
    # tool execution can read it in _run_agentic_loop.
    # ai_parent_tool_call_id is threaded via record_context (see base code line 177)
    self = self.with_context(ai_parent_trace_id=_debug_ctx['trace_id'])

    # ... rest of override ...
```

### Example 3: Pre-generating tool_call_id Map for Split Events

```python
# Before the super() generator loop
# Map our stable tool_call_id UUIDs keyed by call_id from the LLM
_tc_id_map = {tc['call_id']: uuid.uuid4().hex for tc in tool_calls}

# Emit tool_call_started for each tool in the batch
for tc in tool_calls:
    our_tc_id = _tc_id_map[tc['call_id']]
    self._ai_debug_bus_send('tool_call_started', {
        'type': 'tool_call_started',
        'trace_id': _debug_ctx['trace_id'],
        'iteration_id': _debug_ctx['iteration_id'],
        'tool_call_id': our_tc_id,
        'call_id': tc['call_id'],
        'tool_name': tc['name'],
        'args': tc.get('args', {}),
    })

# In the super() generator loop, when tool_results arrive:
for result_item in tool_results:
    call_id = result_item.get('tool_call', {}).get('call_id')
    our_tc_id = _tc_id_map.get(call_id, uuid.uuid4().hex)
    self._ai_debug_bus_send('tool_call_completed', {
        'type': 'tool_call_completed',
        'trace_id': _debug_ctx['trace_id'],
        'iteration_id': _debug_ctx['iteration_id'],
        'tool_call_id': our_tc_id,   # same as tool_call_started
        'call_id': call_id,
        'tool_name': ...,
        'result': ...,
        'success': ...,
        'error': ...,
    })
```

### Example 4: JS Pending-Child Buffer Structure

```javascript
// In AiDebugApp.setup()
this._pendingChildren = {};  // { parent_tool_call_id: { payload, timer } }

this._onNewTrace = (payload) => {
    if (payload.parent_trace_id && payload.parent_tool_call_id) {
        // Try immediate attachment
        // ... look up parent trace + tool call ...
        if (/* found */) {
            this._attachChildTrace(payload);
            return;
        }
        // Buffer
        const timer = setTimeout(() => {
            this._promoteOrphanToRoot(payload);
            delete this._pendingChildren[payload.parent_tool_call_id];
        }, 30000);
        this._pendingChildren[payload.parent_tool_call_id] = { payload, timer };
        return;
    }
    // Root trace
    this._placeTrace(payload);
};

// In _onToolCallStarted (new handler for tool_call_started event)
this._onToolCallStarted = (payload) => {
    // Place tool call in tree...
    // Check buffer
    const buffered = this._pendingChildren[payload.call_id];
    if (buffered) {
        clearTimeout(buffered.timer);
        delete this._pendingChildren[payload.parent_tool_call_id || payload.call_id];
        this._attachChildTrace(buffered.payload);
    }
};
```

## State of the Art

| Old Approach | New Approach | When Changed | Impact |
|---|---|---|---|
| Single `tool_call` event on completion | `tool_call_started` + `tool_call_completed` | Phase 13 | Enables parent node to exist in UI before child trace arrives |
| `new_trace` has no parent linkage | `new_trace` includes `parent_trace_id`, `parent_tool_call_id`, `session_id` | Phase 13 | Frontend can build the subagent hierarchy |
| No JS buffering of out-of-order events | `_pendingChildren` buffer with 30s promotion timer | Phase 13 | No silent data loss when bus events arrive out of order |

## Open Questions

1. **Where exactly does `ai_parent_tool_call_id` get threaded to the subagent session?**
   - What we know: `tools_context['tool_call_id']` is set by base `_handle_tool_calls` (line 214) to the LLM's `call_id` for the current tool. The subagent session is created inside `_ai_tool_request_sub_agent` which receives `tool_context` (= `tools_context`).
   - What's unclear: The cleanest injection point — via `record_context` (already passed to `tool.with_context(**record_context)._ai_tool_run(...)`) or by having `_ai_tool_request_sub_agent` pass it to the session via `with_context`.
   - Recommendation: In the custom `_handle_tool_calls` override, after the `tool_call_started` event is emitted for each tool, add `ai_parent_tool_call_id` to `tools_context` temporarily so `_ai_tool_request_sub_agent` can read it and thread it into the subagent session's context. This avoids modifying the base class.

2. **Does the existing `_onToolCall` handler need to be split or renamed?**
   - What we know: Current handler processes the `tool_call` event type which will be replaced by `tool_call_started` + `tool_call_completed`.
   - What's unclear: Should the existing `tool_call` event type be kept for backward compat with existing IDB records?
   - Recommendation: Keep emitting `tool_call` for the completed case (rename semantically), but also emit `tool_call_started` as a new event. The JS can subscribe to both. This prevents breaking existing IDB hydration for records already stored with the old schema. Alternatively, since the CONTEXT.md says "two distinct events", simply replace — but verify there are no stored IDB records that rely on `tool_call` event type in the hydration path.

3. **`_onNewTrace` currently calls `this.traces.set(...)` unconditionally — refactoring scope**
   - What we know: The buffer path must NOT call `traces.set()` directly.
   - What's unclear: Whether to extract `_placeTrace()` helper or inline the check.
   - Recommendation: Inline the check in `_onNewTrace` (add an early-return buffer path at the top); no need for a dedicated helper given the small scope of this phase.

## Sources

### Primary (HIGH confidence)
- Direct code reading: `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — full custom override, all existing event patterns
- Direct code reading: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` — base `_handle_tool_calls`, `_run_agentic_loop`, `_ai_tool_request_sub_agent`
- Direct code reading: `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — all existing bus event handlers
- Direct code reading: `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — serializeTrace/hydrateTrace patterns
- Direct code reading: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_agent.py` — `_ai_tool_request_sub_agent`, subagent session creation

### Secondary (MEDIUM confidence)
- Odoo ORM context propagation behavior (`with_context()` / `sudo()` inheritance) — verified by examining how `env.context` is used throughout the existing codebase (multiple call sites confirm the pattern)

## Metadata

**Confidence breakdown:**
- Python instrumentation changes: HIGH — full source code available, patterns already established in existing overrides
- Context threading: HIGH — pattern verified through call chain analysis; one open question on exact injection point for `ai_parent_tool_call_id`
- JS buffer logic: HIGH — straightforward JS, clear precedent in flash timer pattern
- Tool call splitting: HIGH — generator wrapping pattern already proven in existing custom override

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable codebase, no external dependencies)
