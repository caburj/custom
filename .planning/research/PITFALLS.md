# Pitfalls Research

**Domain:** Odoo custom module — AI agentic loop instrumentation
**Researched:** 2026-02-20
**Confidence:** HIGH (based on direct inspection of source code at the referenced paths)

---

## Critical Pitfalls

### Pitfall 1: Generator Wrapping That Breaks the Yield Contract

**What goes wrong:**

`_run_agentic_loop` and `_handle_tool_calls` are Python generators — they `yield` structured dicts at each step. A naive override that calls `super()` and immediately consumes the generator into a list (e.g., `results = list(super()._run_agentic_loop(...))`) destroys streaming behavior. The caller in `_add_user_message` iterates the generator to detect `tool_confirmation_request` mid-stream and return early. If the override collapses the generator, the confirmation flow breaks — the user confirmation prompt never gets posted because the generator has already fully executed.

**Why it happens:**

Developers unfamiliar with Python generator semantics call `list(super()._method(...))` to "collect results for inspection," not realizing the generator's side effects (posting messages, updating `self.pending_tool_call_id`) occur during iteration, not after.

**How to avoid:**

The override must use `yield from` to pass through items while inspecting them:

```python
def _run_agentic_loop(self, model, instructions, messages, temperature, tools, tools_context, record=None, schema=None, web_grounding=False):
    for item in super()._run_agentic_loop(model, instructions, messages, temperature, tools, tools_context, record, schema, web_grounding):
        # Capture and record before passing through
        self._capture_item(item)
        yield item  # Must yield, not collect
```

Any capture logic that can raise must be wrapped in `try/except` with the item yielded regardless — an error in the debug module must not interrupt the agentic loop.

**Warning signs:**

- Tool confirmation dialogs stop appearing
- Loop runs to completion but `pending_tool_call_id` is never set
- `_add_user_message` posts the final message before tool confirmation is requested

**Phase to address:** Phase 1 (Model Inheritance + Generator Wrapping)

---

### Pitfall 2: Bus Notifications Silently Lost on Transaction Rollback

**What goes wrong:**

`bus.bus._sendone()` does not immediately send a PostgreSQL NOTIFY. It queues the message in `self.env.cr.precommit.data` and schedules the actual NOTIFY in `self.env.cr.postcommit`. If the transaction rolls back (e.g., the debug `create()` call raises), no notification is ever sent. The frontend's `bus_service.subscribe()` handler never fires. The debug panel shows nothing, with no error visible.

**Why it happens:**

Developers test bus notifications in isolation with no error conditions and see them working. They assume `_sendone` is fire-and-forget. In production, a trace model `create()` with a validation error (e.g., a field constraint on JSON structure), a DB unique constraint violation, or an ORM-level issue silently absorbs the bus notification because the transaction never commits.

**How to avoid:**

- Wrap the persistent model `create()` in a savepoint so a failure in the debug write does not roll back the entire transaction. Use `self.env.cr.savepoint()`.
- Verify the bus notification fires by checking the `bus_bus` table directly in tests, not just the frontend.
- Never put business logic that can raise inside the `precommit` or `postcommit` hooks — keep those paths clean.

**Warning signs:**

- Bus subscribe callback fires in dev but not under error conditions
- No entries appear in the `bus_bus` table despite `_sendone` being called
- A silent rollback in the debug `create()` with no logged exception

**Phase to address:** Phase 1 (Persistent Models) and Phase 2 (Bus Integration)

---

### Pitfall 3: Fan-Out to All Browser Tabs via `_bus_send` on User Partner

**What goes wrong:**

The `ai` module itself sends bus notifications via `self.env.user._bus_send(...)` (confirmed in `ai_session.py` line 456). This sends to the user's partner channel, which all tabs belonging to that user receive simultaneously. If the debug module sends trace notifications the same way, every open Odoo tab for that user will receive them — including unrelated tabs running production workflows. This creates noise and potential performance impact from large JSON payloads being delivered everywhere.

**Why it happens:**

`_bus_send` on a model record is the simplest pattern. Using `self.env.user._bus_send("AI_DEBUG_TRACE", ...)` works identically to the ai module's `AI_SOFT_RELOAD` pattern. The developer does not realize the channel is user-scoped, not tab-scoped.

**How to avoid:**

Use a dedicated debug channel tied to the specific debug session identifier (a UUID generated per trace session), and expose that identifier to the debug panel so it subscribes to exactly that channel. Mirror the `ai_session_identifier` pattern used in `ai_natural_language_service.js` (lines 20, 51, 85, 130 — the JS checks `aiSessionIdentifier !== session.ai_session_identifier` to ignore messages meant for other tabs).

The debug panel backend should derive a channel key from the trace record ID, not the user partner, and `_build_bus_channel_list` must be overridden to add that channel when the debug panel requests it.

**Warning signs:**

- Other Odoo tabs receive debug notifications during an AI session
- Console errors or React state issues in unrelated tabs after AI runs
- Large payloads causing slowdowns in the shared WebSocket worker

**Phase to address:** Phase 2 (Bus Channel Design)

---

### Pitfall 4: Large JSON Payloads Stored in `fields.Json` Exceed PostgreSQL Row Size

**What goes wrong:**

`ai.session.event.metadata` is a `fields.Json` field. In heavy agentic loops (20 iterations, many tool calls, RAG context per call), a single event's metadata can be 50-200 KB. The Odoo ORM stores `fields.Json` as a PostgreSQL `json` column (not `jsonb`). PostgreSQL's TOAST mechanism handles rows up to 1 GB, so storage itself is not the hard limit. The real problem is that Odoo's ORM reads these fields eagerly — when the debug history view loads all iteration records, the ORM fetches every JSON payload into Python objects. With 20 iterations of 100 KB each, a single page load deserializes 2 MB of JSON in the web worker thread.

Additionally, the `bus.bus` notification pathway has a hard payload size cap enforced in `get_notify_payload_max_length()` (defaulting to 8000 bytes from `ODOO_NOTIFY_PAYLOAD_MAX_LENGTH`). Attempting to send a full LLM response payload via `_sendone` will silently truncate or split the notification.

**Why it happens:**

The developer stores the full raw payload from `response` (the LLM's complete response dict including all token data) in the trace model, then includes that same payload in the bus notification for real-time display. Both patterns fail at scale.

**How to avoid:**

- For persistent storage: store a compressed or summarized version in the trace model. Store the full payload in a separate `fields.Text` field or as an `ir.attachment` (binary) for drill-down access, not in the main list.
- For bus notifications: send only a minimal "new trace event" notification (trace ID + event type + timestamp). The debug panel fetches the full payload via a separate RPC on demand, not via bus.
- For the history view: use `lazy: true` on the JSON field, or paginate at the iteration level rather than loading all iterations.

**Warning signs:**

- Page loading hangs when viewing sessions with many iterations
- Browser `JSON.parse()` blocking the main thread during bus message receipt
- Bus notifications that reference large payloads arrive truncated or split

**Phase to address:** Phase 1 (Model Design) — must be decided before writing the first field definitions.

---

### Pitfall 5: Instrumenting a TransientModel That Gets Vacuumed Mid-Session

**What goes wrong:**

`ai.session` is a `TransientModel`. It is subject to `_transient_vacuum()`, which runs as an `@api.autovacuum` cron and deletes records older than `transient_age_limit` (default: 1 hour) or exceeding `osv_memory_count_limit`. A long-running agentic loop that pauses awaiting user confirmation can be vacuumed mid-session. When the debug module holds a reference to `self` (the `ai.session` record) after the vacuum runs, subsequent field reads (`self.event_ids`, `self.state`) raise `MissingError` silently or return empty recordsets — silently corrupting the trace.

**Why it happens:**

The instrumented method holds `self` (the `ai.session` record) across yield boundaries. Python generator semantics keep local variables alive across yields. If the session is vacuumed while the generator is suspended at a `yield`, the next iteration of the generator tries to read from a deleted record.

**How to avoid:**

- Capture all needed data from `self` before the first yield in the override. Store `session_id = self.id` rather than holding `self` across yield boundaries.
- The debug trace model must reference the session by its ID (for logging purposes), not hold a live ORM reference.
- In the debug model, store a copy of `tools_context['state']` at each yield point — don't try to re-read it from the `ai.session` later.

**Warning signs:**

- `MissingError: ai.session(N,)` in server logs during long confirmation-flow sessions
- Trace records that are missing intermediate iterations (the session was vacuumed between two captures)
- State diff shows `None` instead of the actual state

**Phase to address:** Phase 1 (Model Design)

---

### Pitfall 6: `_build_bus_channel_list` Override Missing the Security Gate

**What goes wrong:**

The debug panel needs to subscribe to a custom bus channel (e.g., `ai_debugger_trace_{trace_id}`). The `ir.websocket._build_bus_channel_list` override must add this channel to the list. If the override adds the channel without verifying that the requesting user has access to the trace record, any authenticated user can subscribe to any trace by guessing the channel name and receive debug payloads — including full LLM prompts, tool arguments, and internal state.

**Why it happens:**

The developer sees the `spreadsheet_edition` pattern (lines 28-56 in `ir_websocket.py`) and copies the structure, but omits the access check. The channel name is a string, and strings can be guessed or enumerated.

**How to avoid:**

Follow the pattern in `spreadsheet_edition/models/ir_websocket.py` exactly: parse the channel string, resolve the record ID, call `record.has_access('read')` (or equivalent), and only add the channel to the list if the check passes. Use an opaque UUID-based channel identifier rather than an integer ID to prevent enumeration even if the access check is accidentally omitted.

**Warning signs:**

- Channel string contains a sequential integer (`ai_debugger_trace_42`) rather than a UUID
- No `check_access` or `has_access` call in the `_build_bus_channel_list` override
- Trace payloads include API keys, user data, or prompt content (these are real security data)

**Phase to address:** Phase 2 (Bus Integration) — must be designed into the channel scheme before implementation.

---

### Pitfall 7: OWL Component Subscribing to Bus After the Component Is Destroyed

**What goes wrong:**

An OWL component subscribes to `bus_service.subscribe("AI_DEBUG_TRACE", callback)` in `setup()` or `onMounted`. If the component is destroyed (user navigates away, panel tab is closed), the subscription is not cleaned up. The callback fires against a destroyed component, causing OWL to throw `Component is destroyed` errors or silently update state that is no longer rendered.

**Why it happens:**

The `bus_service.subscribe()` pattern (unlike `useEffect` hooks with cleanup) does not automatically clean up. The developer wires up the subscription but forgets to call `bus_service.unsubscribe()` in `onWillUnmount`.

**How to avoid:**

Always pair `subscribe` with `unsubscribe` in `onWillUnmount`:

```javascript
setup() {
    this.handleTrace = (payload) => { /* ... */ };
    onMounted(() => {
        this.env.services.bus_service.subscribe("AI_DEBUG_TRACE", this.handleTrace);
    });
    onWillUnmount(() => {
        this.env.services.bus_service.unsubscribe("AI_DEBUG_TRACE", this.handleTrace);
    });
}
```

The callback reference must be the same object in both calls — store it as `this.handleTrace`, not as an inline arrow function (which creates a new reference and won't match for unsubscribe).

**Warning signs:**

- OWL `Component is destroyed` errors in the browser console after navigating away from the debug panel
- Memory leaks visible in DevTools — callbacks accumulate over multiple navigations
- State updates firing in a second panel tab after the first was closed

**Phase to address:** Phase 3 (OWL Debug Panel)

---

### Pitfall 8: Wrapping `_handle_tool_calls` While Missing the `tool_confirmation_request` Early Return

**What goes wrong:**

`_handle_tool_calls` uses `return` (not `yield`) to exit the generator early when a tool requests user confirmation (line 228 in `ai_session.py`). A `yield from super()._handle_tool_calls(...)` wrapper will naturally propagate this early termination. But if the override wraps the generator in a `for item in ...:` loop and adds pre/post processing, the `return` causes a `StopIteration` inside the loop — which is silent and correct in Python 3. However, if the developer adds code *after* the loop expecting to always run, it will not run when confirmation is requested.

**Why it happens:**

The developer writes:
```python
for item in self._handle_tool_calls(...):
    self._capture_tool_item(item)
    yield item
self._capture_tool_complete()  # NEVER runs when confirmation exits early
```

**How to avoid:**

Do not add "always-runs" code after the loop. Use `try/finally` if post-loop cleanup is needed:

```python
try:
    for item in super()._handle_tool_calls(...):
        self._capture_tool_item(item)
        yield item
finally:
    self._capture_tool_complete()  # Runs even on early return
```

Or, better: track completion state inside the loop by checking for the `tool_results` key in the last yielded item.

**Warning signs:**

- Trace records show tool execution started but no "complete" marker when confirmation flow triggers
- Debug panel shows an open iteration that never closes
- `_capture_tool_complete()` side effects (e.g., writing `completed_at`) are missing from confirmation-flow traces

**Phase to address:** Phase 1 (Generator Wrapping)

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store full LLM response JSON in bus notification payload | Simplest path to real-time display | Bus truncates payloads >8KB; frontend parsing blocks on large payloads | Never — always use reference + fetch pattern |
| Use `self.env.user._bus_send()` for all debug notifications | One-liner, follows ai module pattern | All tabs for that user receive every trace notification | Never — use a session-scoped channel |
| Hold `ai.session` recordset across yield boundaries | Simplest code — no need to copy IDs | Session vacuumed mid-loop causes `MissingError` | Never — always copy primitive IDs before first yield |
| Skip `onWillUnmount` bus unsubscribe in OWL component | Less boilerplate | Callbacks accumulate, memory leaks, destroyed-component errors | Never |
| `list(super()._run_agentic_loop(...))` to collect all items | Easy inspection | Destroys streaming, breaks confirmation flow | Never |
| Single `fields.Json` field for all trace data | Simple schema | Eager ORM loading fetches all JSON for every list view row | Acceptable in Phase 1 MVP; must fix before Phase 3 if sessions have >5 iterations |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| `bus.bus._sendone()` | Calling it and assuming notification is sent | Notification fires only on transaction commit — test by checking the `bus_bus` table after commit, not during |
| `bus_service.subscribe()` in OWL | Using inline `() => {}` arrow function as callback | Store callback as class property; use same reference for unsubscribe |
| `_build_bus_channel_list` override | Adding channel without access check | Always verify record access before adding channel to the list |
| `ai.session` `_inherit` override | Reading `self.event_ids` after super() returns | `event_ids` are created inside the generator during iteration, not before — they may not exist yet when `super()` is called |
| `fields.Json` in persistent model | Expecting ORM to auto-serialize nested objects | ORM serializes dicts/lists, but datetime objects require manual handling; use `json_default` from `odoo.tools` |
| `ir.websocket._serve_ir_websocket` override | Overriding for custom events | Source code comment explicitly warns this is not recommended and Odoo.sh doesn't support it — use `_build_bus_channel_list` + standard channels instead |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Fetching all iteration JSON in list view | History view takes 3-10 seconds to load | Use `lazy: true` on JSON fields or paginate at the iteration level | After ~10 iterations with RAG context (>50KB per event) |
| Sending full LLM payload via bus on every iteration | Browser freezes briefly on each tool call | Send only `{trace_id, iteration_idx, event_type}` via bus; fetch payload on demand | After first iteration with RAG context included |
| Writing debug trace records synchronously inside generator | Adds DB write latency to each agentic loop iteration visible to user | Use `with self.env.cr.savepoint():` and catch exceptions silently in the capture path | Always — user-facing latency impact from first use |
| Searching `ai_debug_trace` with no index on `session_id` or `create_date` | Slow history views even with few records | Add `_sql_constraints` or `index='btree'` on foreign key fields in the model definition | After ~100 trace records |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Using sequential integer as bus channel name (`ai_debugger_42`) | Authenticated users can enumerate trace IDs and subscribe to others' sessions | Use UUID as channel identifier; still add access check in `_build_bus_channel_list` |
| Storing full LLM prompts in debug model without access restriction | Developer traces contain confidential record data and potentially API keys embedded in prompts | Debug models must have `groups` on their views and `ir.model.access` restricted to developers/admins only |
| Using `sudo()` in the debug capture path without re-checking context | Debug module accidentally elevates the session's privilege | Only use `sudo()` for reading the trace model itself — never for reading the `ai.session` or related data |
| Logging `tools_context` dict which may contain `state` with PII | State dict can contain arbitrary data set by tools, including customer data | Sanitize or depth-limit what gets captured from `tools_context['state']` |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Debug panel opens in same window/tab | Interferes with the chat UI being debugged — two OWL trees fighting for state | Open in a separate `window.open()` tab; design from the start as an independent page |
| Real-time panel re-renders entire tree on every bus event | Flickering and scroll position resets during active sessions with many iterations | Use keyed OWL `t-key` on iteration components; update state in `reactive()` objects rather than triggering full re-renders |
| No indication that a session is being captured | Developer can't tell if the debugger is active | Show a visible indicator (badge, border) on the chat UI when the debug module is enabled and capturing |
| History view loads all iterations by default | Slow page for any session with more than 5 iterations | Default to showing only the last session; require explicit navigation to older ones |

---

## "Looks Done But Isn't" Checklist

- [ ] **Generator passthrough:** The override uses `yield from` or `yield item` — verify by testing a 3-iteration loop with tool confirmation and checking that the confirmation dialog still appears.
- [ ] **Bus notification actually fires:** After a test run, check `SELECT * FROM bus_bus ORDER BY id DESC LIMIT 5` — the debug notification should be visible and contain the correct channel.
- [ ] **Trace persists after session cleanup:** Manually trigger `_transient_vacuum()` via shell and verify the `ai_debug_trace` records still exist.
- [ ] **Bus unsubscribe in OWL:** Navigate to the debug panel, then away, then back — verify in browser DevTools that subscriptions do not accumulate.
- [ ] **Channel access check works:** As a non-admin user, attempt to manually subscribe to a known debug channel string in the browser console and verify the subscription is silently rejected.
- [ ] **Large payload does not break bus:** Run a session with RAG context enabled and verify that bus notifications arrive complete (not truncated) by checking payload size in `bus_bus`.
- [ ] **Capture errors are non-fatal:** Deliberately cause the trace `create()` to fail (e.g., pass an invalid JSON value) and verify the agentic loop completes normally without raising to the user.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Generator wrapping breaks confirmation flow | HIGH | Rewrite the override from scratch using `yield from`; all existing generator logic must be re-tested |
| Bus notifications lost silently | LOW | Add savepoint around trace create; add logging to confirm `postcommit` hook fires |
| Fan-out to all tabs | MEDIUM | Change channel naming scheme from user-scoped to trace-scoped; requires frontend and backend changes in sync |
| Large JSON in bus payload | LOW | Change payload to reference + fetch; frontend change only |
| OWL memory leak from missing unsubscribe | LOW | Add `onWillUnmount` with unsubscribe; no architectural change needed |
| TransientModel vacuumed mid-capture | MEDIUM | Refactor to copy primitive values from `self` before first yield; requires re-testing confirmation flow |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Generator wrapping breaks yield contract | Phase 1: Model Inheritance | Run 3-iteration tool loop with confirmation — dialog must still appear |
| Bus lost on rollback | Phase 1 + Phase 2 | Deliberately fail trace create; verify loop completes and bus fires on retry |
| Fan-out to all tabs via user partner channel | Phase 2: Bus Channel Design | Open 2 tabs; verify only the debug tab receives trace notifications |
| Large JSON payloads | Phase 1: Model Design | Check `bus_bus` payload size after RAG-enabled session |
| TransientModel vacuumed mid-session | Phase 1: Model Design | Run vacuum manually during a paused confirmation flow |
| Bus channel missing access check | Phase 2: Bus Channel Design | As non-admin, attempt to subscribe to another user's channel string |
| OWL missing unsubscribe | Phase 3: OWL Debug Panel | Navigate away and back 5 times; check DevTools for subscription accumulation |
| `_handle_tool_calls` early-return missed | Phase 1: Generator Wrapping | Trigger confirmation flow; verify `completed_at` marker is absent (correct) then present after confirmation |

---

## Sources

- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py` — generator structure, yield points, tool confirmation early return
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `_sendone` precommit/postcommit mechanism, `NOTIFY_PAYLOAD_MAX_LENGTH`
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/ir_websocket.py` — `_build_bus_channel_list` pattern and security requirements
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus_listener_mixin.py` — `_bus_send` routing to partner channel
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/static/src/ai_natural_language_service.js` — `ai_session_identifier` tab-scoping pattern
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/services/bus_service.js` — `subscribe`/`unsubscribe` API and callback reference requirement
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/odoo/orm/models_transient.py` — `_transient_vacuum` and TransientModel lifecycle
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/spreadsheet_edition/models/ir_websocket.py` — reference implementation of `_build_bus_channel_list` with access check

---
*Pitfalls research for: Odoo AI debugger module*
*Researched: 2026-02-20*
