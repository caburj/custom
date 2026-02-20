# Architecture Research

**Domain:** Odoo instrumentation module — AI agentic loop debugger
**Researched:** 2026-02-20
**Confidence:** HIGH (grounded in actual source code at verified paths)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INSTRUMENTATION LAYER                            │
│                                                                      │
│  ai.session (TransientModel) — inherited, not modified               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  AiSessionDebug (_inherit = 'ai.session')                    │   │
│  │  ├── _run_agentic_loop()  → wraps super() generator          │   │
│  │  └── _handle_tool_calls() → wraps super() generator          │   │
│  └──────────────────────────────────────────────────────────────┘   │
│           │ writes to                  │ sends via separate cursor   │
│           ▼                            ▼                             │
├───────────────────────────┬────────────────────────────────────────-─┤
│      PERSISTENCE LAYER    │       REAL-TIME NOTIFICATION LAYER       │
│                           │                                          │
│  ai.debug.trace           │  bus.bus._sendone()                      │
│  ai.debug.iteration       │  via registry.cursor() in postcommit     │
│  ai.debug.tool.call       │  channel: 'ai_debugger_{trace_id}'       │
│                           │                                          │
├───────────────────────────┴──────────────────────────────────────────┤
│                      FRONTEND LAYER                                  │
│                                                                      │
│  ┌──────────────────────────────┐  ┌───────────────────────────┐    │
│  │  Live Debug Panel (OWL)      │  │  Backend History Views     │    │
│  │  ir.actions.client           │  │  (List + Form XML views)   │    │
│  │  busService.addChannel()     │  │  ai.debug.trace model      │    │
│  │  busService.subscribe()      │  │  Odoo backend standard     │    │
│  └──────────────────────────────┘  └───────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `AiSessionDebug` | Wraps generator methods to capture every loop event | `TransientModel`, `_inherit = 'ai.session'`, generator `yield from` passthrough |
| `ai.debug.trace` | One record per agentic loop run; root of trace hierarchy | Persistent `Model`, FK to `ai.agent`, stores loop-level metadata |
| `ai.debug.iteration` | One record per LLM API call within a loop; stores messages sent + raw response | Persistent `Model`, `Many2one → ai.debug.trace` |
| `ai.debug.tool.call` | One record per tool execution; stores args, result, timing | Persistent `Model`, `Many2one → ai.debug.iteration` |
| `ir.websocket` (inherit) | Adds `ai_debugger_{trace_id}` to bus channel list when debug panel is open | `AbstractModel`, `_inherit = 'ir.websocket'`, override `_build_bus_channel_list` |
| Bus notification sender | Sends incremental events from within the generator loop | Separate `registry.cursor()` inside a `@postcommit` hook to avoid batching |
| Live Debug Panel | OWL component; subscribes to bus channel, renders trace in real time | `ir.actions.client` registered component, `busService.addChannel()` + `busService.subscribe()` |
| Backend History Views | Standard Odoo list/form views for post-mortem inspection | XML view definitions, menu entries under Settings or dedicated AI menu |

## Recommended Project Structure

```
ai_debugger/
├── __manifest__.py              # depends: ['ai', 'bus'], assets wiring
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── ai_debug_trace.py        # ai.debug.trace — persistent Model
│   ├── ai_debug_iteration.py    # ai.debug.iteration — persistent Model
│   ├── ai_debug_tool_call.py    # ai.debug.tool.call — persistent Model
│   ├── ai_session.py            # _inherit = 'ai.session', wraps generators
│   └── ir_websocket.py          # _inherit = 'ir.websocket', adds debug channel
├── security/
│   └── ir.model.access.csv      # CRUD access for debug models (admin only)
├── data/
│   └── ir_cron_data.xml         # auto-vacuum cron for old traces
├── controllers/
│   └── __init__.py              # empty (no custom HTTP routes needed initially)
├── static/src/
│   ├── components/
│   │   ├── DebugPanel/
│   │   │   ├── DebugPanel.js    # root OWL component, manages bus subscription
│   │   │   ├── DebugPanel.xml
│   │   │   └── DebugPanel.scss
│   │   ├── TraceView/
│   │   │   ├── TraceView.js     # displays one trace (iterations list)
│   │   │   └── TraceView.xml
│   │   ├── IterationCard/
│   │   │   ├── IterationCard.js # one LLM call — messages, tool calls, timing
│   │   │   └── IterationCard.xml
│   │   ├── ToolCallCard/
│   │   │   ├── ToolCallCard.js  # one tool execution — args, result, success
│   │   │   └── ToolCallCard.xml
│   │   └── JsonViewer/
│   │       ├── JsonViewer.js    # collapsible JSON tree renderer
│   │       └── JsonViewer.xml
│   └── debug_panel_action.js    # registers ir.actions.client tag
└── views/
    ├── ai_debug_trace_views.xml # list + form view for ai.debug.trace
    ├── ai_debug_menus.xml       # menu item under Settings > Technical or AI menu
    └── templates.xml            # QWeb asset bundle registration
```

### Structure Rationale

- **`models/ai_session.py` separate from debug models:** Keeps the instrumentation override clearly distinct from the data schema. Two concerns, two files.
- **`ir_websocket.py` in models/:** Channel authorization belongs server-side with the other model code. This follows the pattern used by `im_livechat`, `hr_attendance`, and `mail` modules.
- **No `controllers/` initially:** The live panel is an `ir.actions.client` — it doesn't need a custom route. A controller can be added later if a dedicated URL is wanted.
- **`static/src/components/` split by component:** Each visual component gets its own folder so JS, XML, and SCSS stay co-located. Matches `mail` and `ai` module conventions.

## Architectural Patterns

### Pattern 1: Generator Yield Passthrough for Instrumentation

**What:** Override a generator method, intercept yielded items, then re-yield unchanged.
**When to use:** Any time you need to observe without modifying behavior. This is THE pattern for this module.
**Trade-offs:** Zero behavioral risk. The only overhead is the instrumentation code that runs between yields (model writes). If instrumentation code raises, it will break the loop — use `try/except` to log and continue.

**Example:**
```python
class AiSessionDebug(models.TransientModel):
    _inherit = 'ai.session'

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, temperature,
                          tools, tools_context, record=None, schema=None,
                          web_grounding=False):
        if not self._debug_is_enabled():
            yield from super()._run_agentic_loop(
                model, instructions, messages, temperature,
                tools, tools_context, record, schema, web_grounding
            )
            return

        trace = self._debug_open_trace(model, instructions, messages, tools)
        iteration_idx = 0
        try:
            for item in super()._run_agentic_loop(
                model, instructions, messages, temperature,
                tools, tools_context, record, schema, web_grounding
            ):
                self._debug_record_loop_event(trace, item, iteration_idx)
                if 'tool_calls' in item:
                    iteration_idx += 1
                yield item
        except Exception:
            self._debug_mark_trace_error(trace)
            raise
        finally:
            self._debug_close_trace(trace)
```

### Pattern 2: Separate Cursor for Real-Time Bus Sends

**What:** The generator runs in a long-lived transaction (the `with registry.cursor() as cr:` block in `thoughts_generator`). Bus notifications are sent via PostgreSQL NOTIFY on `postcommit`, which fires when the cursor context manager exits — i.e., after ALL loop iterations complete. For real-time updates, bus sends need their own short-lived cursor.

**When to use:** Any bus notification that must arrive at the frontend before the outer transaction commits.

**Trade-offs:** Slightly more complex. The separate cursor opens, writes, and commits independently. Failure in the bus send should never propagate to the main transaction.

**Example:**
```python
def _debug_send_bus_event(self, trace_id, notification_type, payload):
    """Send a bus notification using a separate cursor so it fires immediately."""
    dbname = self.env.cr.dbname
    uid = self.env.uid

    @self.env.cr.postcommit.add
    def send_bus():
        # This fires at the end of the current savepoint, not the outer transaction.
        # Using a fresh cursor ensures NOTIFY goes out immediately.
        from odoo.modules.registry import Registry
        registry = Registry(dbname)
        with registry.cursor() as cr:
            env = api.Environment(cr, uid, {})
            env['bus.bus']._sendone(
                f'ai_debugger_{trace_id}',
                notification_type,
                payload,
            )
```

Note: The `postcommit` hook pattern from `google_calendar` (see `google_sync.py`) is the precedent. However, for mid-loop granularity, the notification will fire at the end of each generator item's processing, not mid-item. This gives iteration-level granularity, which is sufficient.

**Alternative: Write debug records with `env.cr.flush()` and let bus batch at session end.** This is simpler and acceptable for the history view. Use the separate cursor only for the live panel.

### Pattern 3: `ir.websocket` Inheritance for Channel Authorization

**What:** Override `_build_bus_channel_list` to add the debugger's channel when the frontend requests it. The client sends the channel name as a string; the server validates and resolves it to a real channel record or string.

**When to use:** Any time a module needs its own named channels beyond the default user/partner/group channels.

**Trade-offs:** Straightforward. The `im_livechat`, `hr_attendance`, and `mail` modules all use this exact pattern. No surprises.

**Example:**
```python
class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        new_channels = list(channels)
        for channel in list(new_channels):
            if isinstance(channel, str) and channel.startswith('ai_debugger_'):
                # Validate the trace_id belongs to the current user before subscribing
                trace_id_str = channel[len('ai_debugger_'):]
                if trace_id_str.isdigit():
                    # Channel is a plain string — no record needed
                    # Keep as-is; _sendone will send to (dbname, channel_str)
                    pass
                else:
                    new_channels.remove(channel)
        return super()._build_bus_channel_list(new_channels)
```

### Pattern 4: OWL Client Action for Standalone Debug Panel

**What:** Register a component as an `ir.actions.client` tag. Open it via `actionService.doAction({ type: 'ir.actions.client', tag: 'ai_debugger.debug_panel' })`. The component manages its own bus subscription lifecycle via `onMounted` / `onWillUnmount`.

**When to use:** Any standalone page not tied to a specific record. The `mail.action_discuss` action is the canonical example.

**Trade-offs:** Clean separation. The panel is a real Odoo action — bookmarkable, openable from menus, targetable as `target: 'new'` for a separate window.

**Example:**
```javascript
import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";

class DebugPanel extends Component {
    static template = "ai_debugger.DebugPanel";
    static props = { traceId: { type: Number, optional: true } };

    setup() {
        this.busService = useService("bus_service");
        this.state = useState({ iterations: [], status: "idle" });

        onMounted(() => {
            const channel = `ai_debugger_${this.props.traceId}`;
            this.busService.addChannel(channel);
            this.busService.subscribe("ai_debug_iteration", this._onIteration.bind(this));
            this.busService.subscribe("ai_debug_tool_call", this._onToolCall.bind(this));
        });

        onWillUnmount(() => {
            // removeChannel is the symmetric call
            // busService.removeChannel(channel); — check actual API name
            this.busService.unsubscribe("ai_debug_iteration", this._onIteration.bind(this));
            this.busService.unsubscribe("ai_debug_tool_call", this._onToolCall.bind(this));
        });
    }

    _onIteration({ payload }) {
        this.state.iterations.push(payload);
    }
}

registry.category("actions").add("ai_debugger.debug_panel", DebugPanel);
```

## Data Flow

### Capture Flow (Write Path)

```
HTTP POST /ai/generate_response
    ↓
thoughts_generator() — opens registry.cursor() [long transaction]
    ↓
ai_session_sudo._add_user_message()
    ↓
_generate_next_response()
    ↓
AiSessionDebug._run_agentic_loop()   ← instrumentation starts here
    │
    ├── _debug_open_trace()          → CREATE ai.debug.trace (buffered in ORM)
    │
    ├── for each LLM call:
    │   ├── super()._run_agentic_loop() yields {'tool_calls': ..., 'metadata': response}
    │   ├── _debug_record_iteration()  → CREATE ai.debug.iteration (buffered)
    │   ├── _debug_send_bus_event()    → postcommit hook schedules separate cursor send
    │   │
    │   └── for each tool result:
    │       ├── super() yields {'tool_results': ...}
    │       └── _debug_record_tool_call() → CREATE ai.debug.tool.call (buffered)
    │
    └── _debug_close_trace()         → WRITE ai.debug.trace.state = 'done'

thoughts_generator cursor exits → all ORM writes commit → NOTIFY fires (bus sends)
```

### Live Panel Flow (Read Path)

```
User opens debug panel (ir.actions.client action)
    ↓
DebugPanel.onMounted()
    ├── busService.addChannel('ai_debugger_{traceId}')
    │     → WebSocket sends 'subscribe' event with channel name
    │     → ir.websocket._build_bus_channel_list() validates channel
    │
    └── busService.subscribe('ai_debug_iteration', handler)
        busService.subscribe('ai_debug_tool_call', handler)

NOTIFY 'imbus' arrives (from bus.bus postcommit)
    → ImDispatch.loop() relays to subscribed websockets
    → WebSocket delivers notification to browser
    → busService notificationBus.trigger(type, payload)
    → handler updates component state
    → OWL reactivity re-renders
```

### History View Flow

```
User navigates to AI Debugger menu
    → Odoo backend loads ai.debug.trace list view (XML definition)
    → ORM query: SELECT * FROM ai_debug_trace ORDER BY create_date DESC
    → Click trace → form view with One2many → iterations → tool_calls
```

### Key Data Flows

1. **Trace creation to persistence:** ORM buffered writes commit at generator cursor exit. Not visible until the full agentic response completes. Acceptable for the history view, not for live.

2. **Live bus notifications:** Postcommit hooks using a separate cursor send NOTIFY before the main transaction's postcommit fires. This achieves mid-loop granularity at the cost of a second DB connection per notification.

3. **State diff:** Captured by snapshotting `tools_context['state']` before and after each LLM call in `_run_agentic_loop`. The diff is computed Python-side before storing.

## Scaling Considerations

This is a single-developer local tool. Scaling is not a concern. Notes for completeness:

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 developer | Current design is correct. No changes. |
| Small team (2-10) | Add `ai_debugger.retention_days` config param. Add index on `trace_id` FK columns. |
| Production (never recommended) | Disable via `ai_debugger.enabled = False`. The module adds DB writes and a separate cursor per loop event. |

### First Bottleneck

If the module is accidentally left enabled in production: the extra DB writes per iteration add latency to every agentic loop call. Detection: `ai.debug.trace` table grows unbounded. Fix: the `ir.cron` auto-vacuum deletes records older than `retention_days`.

## Anti-Patterns

### Anti-Pattern 1: Modifying Yielded Items

**What people do:** Alter the dict returned by `super()._run_agentic_loop()` before yielding.
**Why it's wrong:** The caller (`_generate_next_response`) and the HTTP controller both read from yielded items. Modifying `'metadata'`, `'tool_calls'`, or `'final_message'` breaks the loop's state management or the streaming response.
**Do this instead:** Read from yielded items, write to debug models, then `yield item` unchanged.

### Anti-Pattern 2: Calling `bus.bus._sendone` Inside the Main Transaction

**What people do:** Call `self.env['bus.bus']._sendone(...)` directly inside the generator override methods.
**Why it's wrong:** `_sendone` queues the NOTIFY in `postcommit.data`, which fires when the outer `registry.cursor()` context manager in `thoughts_generator` exits — i.e., after all iterations complete. The "real-time" panel would only update once, at the end.
**Do this instead:** Use a separate `registry.cursor()` in a postcommit hook (see Pattern 2 above), or accept that notifications are batched per iteration and sent after each yield.

### Anti-Pattern 3: Inheriting `ai.session` as a Persistent Model

**What people do:** Change `_name = 'ai.session'` to `_name = 'ai.debug.session'` or try to make the session persist.
**Why it's wrong:** `ai.session` is a `TransientModel`. Its records are cleaned up by Odoo's `_gc_transient_models` cron. Debug data stored on the transient model will disappear.
**Do this instead:** Use `_inherit = 'ai.session'` (TransientModel inheritance) for the instrumentation override. Store all debug data in separate persistent `Model` classes (`ai.debug.trace`, etc.).

### Anti-Pattern 4: Using a Named String Bus Channel Without Server-Side Validation

**What people do:** Send to `'ai_debugger_general'` or any unvalidated channel string, and allow any client to subscribe.
**Why it's wrong:** Any user who knows the channel name can subscribe and see all debug traces.
**Do this instead:** Include the trace ID in the channel name and validate in `ir.websocket._build_bus_channel_list` that the requesting user owns that trace (e.g., `trace.create_uid == self.env.user`).

### Anti-Pattern 5: Putting Instrumentation Logic in `_add_user_message` or `_generate_next_response`

**What people do:** Override the higher-level methods to capture data because they're easier to understand.
**Why it's wrong:** These methods handle confirmation flows, session state, and message posting — they don't have direct access to the per-iteration data (raw LLM response, iteration index, tool_results list).
**Do this instead:** Override `_run_agentic_loop` and `_handle_tool_calls`. These are the methods with direct access to every data point needed.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| `ai.session` (enterprise) | Model inheritance (`_inherit`) | Zero modification to `ai` module. The debugger is a pure consumer. |
| `bus.bus` | `_sendone()` via separate cursor | See Pattern 2. The debugger is a producer; OWL panel is the consumer. |
| `ir.websocket` | Abstract model inheritance | Channel authorization must validate trace ownership. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `AiSessionDebug` → `ai.debug.trace` | Direct ORM write (`env['ai.debug.trace'].create(...)`) | Buffered in transaction; committed at cursor exit. |
| `AiSessionDebug` → `bus.bus` | `postcommit` hook with separate cursor | Achieves pre-main-commit delivery for live updates. |
| `DebugPanel` (OWL) → server | `busService.addChannel()` + `busService.subscribe()` | WebSocket; standard Odoo bus consumer pattern. |
| Backend views → `ai.debug.*` | ORM read via standard Odoo list/form view | No custom controllers needed; standard XML views suffice. |

## Build Order Implications

The component dependencies enforce this build order:

1. **Data models first** (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) — everything else depends on the schema existing. Security (ir.model.access.csv) and auto-vacuum cron ship alongside.

2. **`ai.session` instrumentation** (`_inherit = 'ai.session'`) — depends on models existing to write to. Can be verified by calling agentic loop and checking `ai.debug.trace` records via the Odoo shell.

3. **Backend XML views** — depends on models. No JS dependencies. Immediately useful for verifying captured data without any frontend work.

4. **`ir.websocket` extension + OWL panel** — depends on models (to know what data to display) and the backend views (for context on what a trace looks like). Bus send code in the instrumentation layer ships here.

5. **Polish** — JSON tree viewer, state diff component, filtering UI, configuration parameters UI.

## Sources

- Source: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py` — generator structure, yield items, `tools_context` keys (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/controllers/thread.py` — `thoughts_generator` cursor management, how generator is consumed (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `_sendone` precommit/postcommit mechanism, NOTIFY timing (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus_listener_mixin.py` — `_bus_send` and `_bus_channel` pattern (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/ir_websocket.py` — `_build_bus_channel_list` extension point (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/im_livechat/models/ir_websocket.py` — string channel validation pattern (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/services/bus_service.js` — `addChannel`, `subscribe`, `unsubscribe` OWL API (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/mail/static/src/core/web/mail_core_web_service.js` — `busService.subscribe()` pattern in practice (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/google_calendar/models/google_sync.py` — `@postcommit.add` with separate `registry.cursor()` (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/mail/views/discuss_channel_views.xml` — `ir.actions.client` XML definition pattern (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/__manifest__.py` — asset bundle registration, module dependencies (HIGH confidence — direct source read)

---
*Architecture research for: Odoo AI debugger instrumentation module*
*Researched: 2026-02-20*
