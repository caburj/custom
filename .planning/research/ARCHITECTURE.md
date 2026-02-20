# Architecture Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1)
**Researched:** 2026-02-20
**Confidence:** HIGH (grounded in actual source at verified paths)

## What Changed in v1.1

v1.0 used: persistent DB models + backend XML views + OWL client action panel.
v1.1 replaces that with: no DB models + standalone OWL app at `/ai-debug` + full bus payloads.

This document focuses on the v1.1 target architecture. v1.0 patterns that carry over unchanged (generator yield passthrough, separate cursor bus sends) are referenced but not re-explained in full.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                     INSTRUMENTATION LAYER (unchanged)                │
│                                                                      │
│  AiSessionDebug (_inherit = 'ai.session')                            │
│  ├── _run_agentic_loop()   — wraps super(), captures events          │
│  ├── _handle_tool_calls()  — wraps super(), captures tool events     │
│  └── _generate_next_response() — captures instructions + RAG        │
│           │                                                          │
│           │  No DB writes. Sends via separate cursor:                │
│           ▼                                                          │
├──────────────────────────────────────────────────────────────────────┤
│                  REAL-TIME NOTIFICATION LAYER                        │
│                                                                      │
│  bus.bus._sendone('ai_debug:traces', event_type, FULL_PAYLOAD)       │
│                                                                      │
│  Events (all carry full data — no lazy DB reads):                    │
│  ├── ai_debug/new_trace    — loop start, instructions, tools def     │
│  ├── ai_debug/iteration    — messages_sent, raw_response, timing     │
│  ├── ai_debug/tool_call    — args, result, state_before/after        │
│  └── ai_debug/trace_update — state, termination_reason              │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                       HTTP LAYER (new in v1.1)                       │
│                                                                      │
│  AiDebugController                                                   │
│  └── GET /ai-debug  →  renders 'ai_debug.index' template            │
│                         (auth='user', internal users only)           │
│                                                                      │
├──────────────────────────────────────────────────────────────────────┤
│                   STANDALONE OWL APP LAYER (new)                     │
│                                                                      │
│  ai_debug.index (QWeb template — full HTML page, no Odoo chrome)     │
│  └── loads asset bundle: ai_debug.assets                            │
│      └── main.js → mountComponent(AiDebugApp, document.body)        │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  AiDebugApp  (root OWL component)                           │     │
│  │  ├── TraceList  (sidebar — loops, with agent label)         │     │
│  │  │   ├── LoopItem (clickable, shows status badge)          │     │
│  │  │   │   ├── IterationItem (LLM call, duration)           │     │
│  │  │   │   │   └── ToolCallItem (tool name, success badge)  │     │
│  │  │   │   └── ...                                          │     │
│  │  │   └── ...                                              │     │
│  │  └── DetailPanel  (right pane — context for selection)     │     │
│  │      ├── LoopDetail  (system prompt, tools definition)     │     │
│  │      ├── IterationDetail  (messages sent, raw response)    │     │
│  │      └── ToolCallDetail  (args, result, state diff)        │     │
│  └─────────────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| `AiSessionDebug` | Generator yield passthrough; emits full bus payloads | `TransientModel`, `_inherit = 'ai.session'`, unchanged from v1.0 except payload content |
| `ir.websocket` (inherit) | Restricts `ai_debug:*` channels to `group_system` users | `AbstractModel`, `_build_bus_channel_list` override — carried over from v1.0 |
| `AiDebugController` | Serves the standalone app HTML page at `/ai-debug` | `http.Controller`, `auth='user'`, renders `ai_debug.index` QWeb template |
| `ai_debug.index` (template) | Full HTML page: CSRF token, `__session_info__`, asset bundle | QWeb template declared in views XML; bootstraps OWL app |
| `ai_debug.assets` (bundle) | JS + CSS for the standalone app | Declared in `__manifest__.py`; includes OWL, web core services, bus service |
| `main.js` | Boots the OWL app | `mountComponent(AiDebugApp, document.body)` from `@web/env` |
| `AiDebugApp` | Root component; owns bus subscription and all trace state | OWL `Component`; `useState` for traces map; `useService('bus_service')` |
| `TraceList` | Sidebar tree: loop > iteration > tool call | Receives traces from parent; emits selection events upward |
| `DetailPanel` | Right pane; renders context for selected item | Receives `selection` prop (type + data); switches between sub-components |
| `JsonTree` | Collapsible JSON tree renderer | Pure presentational; carries over from v1.0 |
| `StateDiff` | Before/after state comparison | Pure presentational; carries over from v1.0 |

---

## Recommended Project Structure (v1.1)

```
ai_debug/
├── __manifest__.py                   # updated: no models data, new assets bundle, new controller
├── __init__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                       # NEW: AiDebugController — serves /ai-debug
├── models/
│   ├── __init__.py
│   ├── ai_session.py                 # unchanged: generator instrumentation
│   └── ir_websocket.py               # unchanged: channel access control
├── views/
│   └── templates.xml                 # NEW: ai_debug.index QWeb template
├── static/src/
│   ├── app/
│   │   ├── main.js                   # NEW: app boot — mountComponent(AiDebugApp)
│   │   ├── ai_debug_app.js           # NEW: root component — state, bus, selection
│   │   ├── ai_debug_app.xml          # NEW: root template
│   │   ├── ai_debug_app.scss         # NEW: full-page layout styles
│   │   ├── sidebar/
│   │   │   ├── trace_list.js         # NEW: sidebar tree component
│   │   │   ├── trace_list.xml
│   │   │   ├── loop_item.js          # NEW: one loop row
│   │   │   ├── loop_item.xml
│   │   │   ├── iteration_item.js     # NEW: one iteration row (nested)
│   │   │   ├── iteration_item.xml
│   │   │   ├── tool_call_item.js     # NEW: one tool call row (nested)
│   │   │   └── tool_call_item.xml
│   │   └── detail/
│   │       ├── detail_panel.js       # NEW: right pane switcher
│   │       ├── detail_panel.xml
│   │       ├── loop_detail.js        # NEW: system prompt + tools def
│   │       ├── loop_detail.xml
│   │       ├── iteration_detail.js   # NEW: messages sent + raw response
│   │       ├── iteration_detail.xml
│   │       ├── tool_call_detail.js   # NEW: args + result + state diff
│   │       └── tool_call_detail.xml
│   └── components/
│       ├── json_tree/               # carried over from v1.0
│       │   ├── json_tree.js
│       │   └── json_tree.xml
│       └── state_diff/              # carried over from v1.0
│           ├── state_diff.js
│           └── state_diff.xml
└── security/
    └── ir.model.access.csv          # REMOVED in v1.1 (no DB models)
```

**Files to delete from v1.0:**
- `models/ai_debug_trace.py`
- `models/ai_debug_iteration.py`
- `models/ai_debug_tool_call.py`
- `security/ir.model.access.csv`
- `views/ai_debug_trace_views.xml`
- `views/ai_debug_iteration_views.xml`
- `views/ai_debug_tool_call_views.xml`
- `views/debug_panel_action.xml`
- `views/menus.xml`

---

## Architectural Patterns

### Pattern 1: Standalone OWL App — Controller + Template + Asset Bundle

This is the POS Self Order pattern, which is simpler than full POS and has no session management complexity. The hr_attendance kiosk is even simpler (uses `web.layout`), but ai_debug should match `pos_self_order.index` since it needs `__session_info__` for the bus service.

**What:** A dedicated HTTP route renders a full HTML page (no Odoo chrome/navbar). The template inlines the CSRF token and `__session_info__` as a JS global, then loads a custom asset bundle. The bundle's `main.js` boots an OWL app via `mountComponent`.

**When to use:** Any tool that should live in its own browser tab, free of the Odoo backend navbar.

**Controller (HIGH confidence — from source):**

```python
# controllers/main.py
from odoo import http
from odoo.http import request


class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user')
    def ai_debug_index(self, **kwargs):
        if not request.env.user._is_internal():
            return request.not_found()
        session_info = request.env['ir.http'].session_info()
        return request.render('ai_debug.index', {
            'session_info': session_info,
        })
```

**Template — `views/templates.xml` (HIGH confidence — from source):**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <template id="ai_debug.index" name="AI Debug">
        &lt;!DOCTYPE html&gt;
        <html>
            <head>
                <title>AI Debug</title>
                <meta http-equiv="X-UA-Compatible" content="IE=edge"/>
                <meta http-equiv="content-type" content="text/html, charset=utf-8"/>
                <meta name="viewport" content="width=device-width, initial-scale=1"/>
                <script type="text/javascript">
                    var odoo = <t t-out="json.dumps({
                        'csrf_token': request.csrf_token(None),
                        '__session_info__': session_info,
                        'debug': request.session.debug,
                    })"/>;
                </script>
                <t t-call-assets="ai_debug.assets"/>
            </head>
            <body>
            </body>
        </html>
    </template>
</odoo>
```

**Asset bundle in `__manifest__.py` (HIGH confidence — from source):**

```python
'assets': {
    'ai_debug.assets': [
        # OWL + web infrastructure (mirrors pos_self_order.assets pattern)
        ('include', 'web._assets_helpers'),
        ('include', 'web._assets_backend_helpers'),
        'web/static/src/scss/pre_variables.scss',
        'web/static/lib/bootstrap/scss/_variables.scss',
        'web/static/lib/bootstrap/scss/_variables-dark.scss',
        'web/static/lib/bootstrap/scss/_maps.scss',
        ('include', 'web._assets_bootstrap_backend'),
        ('include', 'web._assets_core'),
        # Bus service (needed for WebSocket)
        'bus/static/src/services/bus_service.js',
        'bus/static/src/services/worker_service.js',
        'bus/static/src/bus_parameters_service.js',
        'bus/static/src/multi_tab_service.js',
        'bus/static/src/multi_tab_shared_worker_service.js',
        'bus/static/src/multi_tab_fallback_service.js',
        'bus/static/src/workers/*',
        # App files
        'ai_debug/static/src/**/*.js',
        'ai_debug/static/src/**/*.xml',
        'ai_debug/static/src/**/*.scss',
    ],
},
```

**main.js (HIGH confidence — from pos_self_order and POS source):**

```javascript
// static/src/app/main.js
import { mountComponent } from "@web/env";
import { whenReady } from "@odoo/owl";
import { AiDebugApp } from "./ai_debug_app";

whenReady(async () => {
    await mountComponent(AiDebugApp, document.body, {
        name: "AI Debug",
    });
});
```

`mountComponent` from `@web/env` calls `makeEnv()` + `startServices(env)` internally, which initializes the Odoo service registry (including `bus_service`, `orm`, `rpc`, `notification`). All services registered in `web.assets_backend` service registry are available. This is the key benefit over raw `App` mounting.

### Pattern 2: Full Bus Payloads — No Lazy ORM Reads

**What:** The v1.0 bus payloads were summaries (IDs only). The OWL panel then made ORM read calls on expand. In v1.1 there are no DB models, so all data must travel in the bus payload at event time.

**When to use:** Always, when there is no DB to fall back to.

**Trade-offs:** Payloads can be large. `messages_sent` for a multi-turn conversation can be tens of KB. The `bus_bus` table stores each payload as JSONB — this is fine. The pg_notify NOTIFY payload has a limit (default 8000 bytes) but this is for the notification *channel list*, not the message payload. The message itself is stored in `bus_bus` rows and fetched by the polling/WS client — no size constraint from pg_notify.

**What each event type must carry (inferred from v1.0 DB schema):**

```python
# ai_debug/new_trace  — fires when _run_agentic_loop starts
{
    'trace_id': str,           # UUID, client-generated, never a DB id
    'llm_model': str,
    'state': 'running',
    'instructions': str,       # system prompt (was lazy in v1.0)
    'rag_context': str,        # RAG text (was lazy in v1.0)
    'tools_definition': list,  # full tool schemas (was lazy in v1.0)
    'started_at': float,       # time.time(), for display
}

# ai_debug/iteration  — fires after each LLM yield
{
    'trace_id': str,
    'iteration_id': str,       # UUID, client-generated
    'index': int,
    'messages_sent': list,     # full message list (was lazy in v1.0)
    'raw_response': dict,      # full provider response (was lazy in v1.0)
    'final_message': dict,     # present if loop terminating
    'duration_ms': int,
}

# ai_debug/tool_call  — fires for each tool result
{
    'trace_id': str,
    'iteration_id': str,
    'tool_call_id': str,       # UUID, client-generated
    'tool_name': str,
    'call_id': str,            # LLM-assigned call_id
    'args': dict,              # full args (was lazy in v1.0)
    'result': str,
    'success': bool,
    'state_before': dict,      # full state snapshot (was lazy in v1.0)
    'state_after': dict,       # full state snapshot (was lazy in v1.0)
    'triggered_confirmation': bool,
    'confirmation_message': str,
    'duration_ms': int,
}

# ai_debug/trace_update  — fires on state change (done/error/paused)
{
    'trace_id': str,
    'state': str,              # 'done' | 'error' | 'paused'
    'termination_reason': str,
    'error_message': str,
    'iteration_count': int,
    'total_duration_ms': int,
}
```

**ID strategy:** Since there are no DB records, IDs must be client-meaningful strings. Generate a `trace_id` UUID in Python at loop start. Generate `iteration_id` and `tool_call_id` UUIDs as each event fires. The client uses these as dict keys for O(1) lookup.

**Binary stripping:** The existing `_debug_strip_binaries` helper in `ai_session.py` already handles large base64 content in `messages_sent`. Carry it forward unchanged.

### Pattern 3: OWL App State Management — Reactive Store in Root Component

**What:** The root component `AiDebugApp` owns the entire application state as a single `useState` object. Child components receive state slices as props. This avoids the complexity of a separate store service for an app this small.

**When to use:** Apps with a single data entity type (traces) and simple selection state. For comparison: POS uses a complex service-based store because it has dozens of entity types. ai_debug has one.

**Trade-offs:** All bus event handlers live in the root component. This is acceptable because there are only 4 event types. The sidebar and detail panel are purely presentational — they receive data and emit selection events upward via callbacks.

**Root component state shape:**

```javascript
// static/src/app/ai_debug_app.js
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { TraceList } from "./sidebar/trace_list";
import { DetailPanel } from "./detail/detail_panel";

export class AiDebugApp extends Component {
    static template = "ai_debug.AiDebugApp";
    static components = { TraceList, DetailPanel };
    static props = {};

    setup() {
        this.busService = useService("bus_service");

        // All application state in one reactive object.
        // traces: Map<traceId, TraceNode>
        // TraceNode: { id, llm_model, state, instructions, tools_definition,
        //              iterations: Map<iterationId, IterationNode> }
        // IterationNode: { id, index, messages_sent, raw_response, final_message,
        //                  duration_ms, toolCalls: Map<toolCallId, ToolCallNode> }
        // ToolCallNode:  { id, tool_name, args, result, state_before, state_after,
        //                  success, duration_ms }
        this.state = useState({
            traces: new Map(),
            selection: null,   // { type: 'loop'|'iteration'|'tool_call', id: str }
            connectionStatus: 'connecting',
        });

        // Bind handlers once.
        this._onNewTrace = this._onNewTrace.bind(this);
        this._onIteration = this._onIteration.bind(this);
        this._onToolCall = this._onToolCall.bind(this);
        this._onTraceUpdate = this._onTraceUpdate.bind(this);

        onMounted(() => {
            this.busService.addChannel("ai_debug:traces");
            this.busService.subscribe("ai_debug/new_trace", this._onNewTrace);
            this.busService.subscribe("ai_debug/iteration", this._onIteration);
            this.busService.subscribe("ai_debug/tool_call", this._onToolCall);
            this.busService.subscribe("ai_debug/trace_update", this._onTraceUpdate);
        });

        onWillUnmount(() => {
            this.busService.deleteChannel("ai_debug:traces");
            this.busService.unsubscribe("ai_debug/new_trace", this._onNewTrace);
            this.busService.unsubscribe("ai_debug/iteration", this._onIteration);
            this.busService.unsubscribe("ai_debug/tool_call", this._onToolCall);
            this.busService.unsubscribe("ai_debug/trace_update", this._onTraceUpdate);
        });
    }

    _onNewTrace(payload) {
        this.state.traces.set(payload.trace_id, {
            id: payload.trace_id,
            llm_model: payload.llm_model,
            state: payload.state,
            instructions: payload.instructions,
            rag_context: payload.rag_context,
            tools_definition: payload.tools_definition,
            started_at: payload.started_at,
            iterations: new Map(),
        });
        // Auto-select the new trace's loop node.
        this.state.selection = { type: 'loop', id: payload.trace_id };
    }

    _onIteration(payload) {
        const trace = this.state.traces.get(payload.trace_id);
        if (!trace) return;
        trace.iterations.set(payload.iteration_id, {
            id: payload.iteration_id,
            index: payload.index,
            messages_sent: payload.messages_sent,
            raw_response: payload.raw_response,
            final_message: payload.final_message,
            duration_ms: payload.duration_ms,
            toolCalls: new Map(),
        });
    }

    _onToolCall(payload) {
        const trace = this.state.traces.get(payload.trace_id);
        if (!trace) return;
        const iteration = trace.iterations.get(payload.iteration_id);
        if (!iteration) return;
        iteration.toolCalls.set(payload.tool_call_id, {
            id: payload.tool_call_id,
            tool_name: payload.tool_name,
            args: payload.args,
            result: payload.result,
            success: payload.success,
            state_before: payload.state_before,
            state_after: payload.state_after,
            duration_ms: payload.duration_ms,
        });
    }

    _onTraceUpdate(payload) {
        const trace = this.state.traces.get(payload.trace_id);
        if (!trace) return;
        trace.state = payload.state;
        trace.termination_reason = payload.termination_reason;
        trace.total_duration_ms = payload.total_duration_ms;
        trace.iteration_count = payload.iteration_count;
    }

    setSelection(selection) {
        this.state.selection = selection;
    }

    get selectedNode() {
        if (!this.state.selection) return null;
        const { type, id, traceId, iterationId } = this.state.selection;
        if (type === 'loop') return { type, data: this.state.traces.get(id) };
        if (type === 'iteration') {
            const trace = this.state.traces.get(traceId);
            return { type, data: trace?.iterations.get(id) };
        }
        if (type === 'tool_call') {
            const trace = this.state.traces.get(traceId);
            const iter = trace?.iterations.get(iterationId);
            return { type, data: iter?.toolCalls.get(id) };
        }
        return null;
    }
}
```

**OWL Map reactivity note:** OWL's `useState` makes objects reactive by proxy. `Map` objects inside `useState` ARE reactive — mutations (`.set`, `.delete`) trigger re-renders. This is confirmed by OWL source. Use `Map` for O(1) lookup by ID; the sidebar renders by iterating `.values()`.

### Pattern 4: Sidebar Tree — 3-Level Collapsible List

**What:** The sidebar is a pure presentational component tree. It receives the `traces` Map and a `setSelection` callback as props. Each level (loop, iteration, tool call) is its own component that renders its children.

**When to use:** Hierarchical data with 3 levels and selection state managed by a parent.

**Template structure:**

```xml
<!-- sidebar/trace_list.xml -->
<templates>
    <t t-name="ai_debug.TraceList">
        <div class="ai-debug-sidebar">
            <t t-foreach="[...props.traces.values()]" t-as="trace" t-key="trace.id">
                <LoopItem
                    trace="trace"
                    isSelected="props.selection?.id === trace.id"
                    onSelect="props.setSelection"
                />
            </t>
        </div>
    </t>

    <t t-name="ai_debug.LoopItem">
        <!-- Clickable header — selects loop node -->
        <div class="ai-debug-loop-item" t-on-click="onClickLoop">
            <span class="badge" t-att-class="statusBadgeClass">
                <t t-esc="props.trace.state"/>
            </span>
            <span t-esc="props.trace.llm_model"/>
        </div>
        <!-- Always expanded; iterations always visible under their loop -->
        <t t-foreach="[...props.trace.iterations.values()]" t-as="iter" t-key="iter.id">
            <IterationItem
                trace="props.trace"
                iteration="iter"
                isSelected="props.selection?.id === iter.id"
                onSelect="props.onSelect"
            />
        </t>
    </t>
</templates>
```

**Selection protocol:** The sidebar emits `setSelection({ type, id, traceId?, iterationId? })` upward. The root component updates `state.selection`. The `DetailPanel` receives the resolved `selectedNode` as a prop and switches between `LoopDetail`, `IterationDetail`, or `ToolCallDetail`.

---

## Data Flow

### Capture Flow (Python — write path, v1.1)

```
HTTP call triggers agentic loop
    ↓
AiSessionDebug._run_agentic_loop()
    │
    ├── Generate trace_id = uuid.uuid4()
    ├── _debug_bus_send_full('ai_debug/new_trace', {full trace payload})
    │     → separate registry.cursor() → bus.bus._sendone()
    │
    ├── for each LLM yield:
    │   ├── Generate iteration_id = uuid.uuid4()
    │   ├── _debug_bus_send_full('ai_debug/iteration', {full iteration payload})
    │   │
    │   └── for each tool result (via _handle_tool_calls):
    │       ├── Generate tool_call_id = uuid.uuid4()
    │       └── _debug_bus_send_full('ai_debug/tool_call', {full tool payload})
    │
    └── _debug_bus_send_full('ai_debug/trace_update', {state: 'done', ...})

No DB writes. All data exists only in the browser until page refresh.
```

### Live App Flow (OWL — read path, v1.1)

```
User navigates to /ai-debug
    ↓
AiDebugController.ai_debug_index()
    → renders ai_debug.index template
    → browser loads ai_debug.assets bundle
    → main.js: mountComponent(AiDebugApp, document.body)
    → makeEnv() + startServices(env) boot all registered services
    → AiDebugApp.setup() runs
    → busService.addChannel('ai_debug:traces')
    → WebSocket connects
    → ir.websocket._build_bus_channel_list() validates group_system

Agentic loop fires on another tab/user
    → bus.bus._sendone('ai_debug:traces', 'ai_debug/new_trace', {FULL_PAYLOAD})
    → PostgreSQL NOTIFY → ImDispatch → WebSocket → browser
    → busService dispatches to AiDebugApp._onNewTrace(payload)
    → AiDebugApp updates state.traces Map
    → OWL reactivity: TraceList re-renders sidebar, DetailPanel shows loop detail

Subsequent iterations/tool calls arrive the same way.
    → Map mutations trigger OWL re-renders
    → Sidebar tree grows in real time
    → Selection state preserved across updates
```

### Key Data Flows

1. **New trace auto-selection:** On `_onNewTrace`, the app immediately sets `state.selection` to the new loop node. The detail panel shows the system prompt and tools definition without any user action.

2. **Session scope:** Refreshing the browser clears `state.traces` (empty Map). There is no persistence and no way to load historical traces. This is by design.

3. **Subagent anticipation:** When a subagent loop fires, it emits its own `ai_debug/new_trace` event with a distinct `trace_id`. The sidebar shows it as a second top-level loop. The data model carries a `parent_trace_id` field (null for now) that the frontend can use later to indent subagent loops under their parent.

---

## Integration Points

### Between Python Instrumentation and Bus

| Concern | v1.0 | v1.1 |
|---------|------|------|
| Payload size | Small summaries (IDs only) | Full payloads (messages, args, state snapshots) |
| ID source | DB autoincrement | `uuid.uuid4()` — no DB |
| Bus channel | `ai_debug:traces` (global) | `ai_debug:traces` (global, unchanged) |
| DB writes | Separate cursor per event | None |

### Between OWL App and Odoo Backend Services

The standalone app gets Odoo services (bus_service, rpc, orm, notification) for free via `mountComponent` + `startServices`. No special wiring needed. The `session` object is injected via `odoo.__session_info__` in the template (same pattern as POS self-order and POS).

| Service | Used by | Notes |
|---------|---------|-------|
| `bus_service` | `AiDebugApp` | WebSocket connection, channel subscription |
| `rpc` | Not used in v1.1 | No backend data fetching |
| `orm` | Not used in v1.1 | No DB models |

### Auth and Access

- Route: `auth='user'` — Odoo session required. Not public.
- Channel access: `ir.websocket` override restricts `ai_debug:*` channels to `group_system` (carried from v1.0). Any internal user can open the page, but only system users receive bus events.
- If the target access should be relaxed to `base.group_user`, change the channel guard in `ir_websocket.py` to `has_group('base.group_user')`.

---

## Anti-Patterns

### Anti-Pattern 1: Storing Full Payload in pg_notify NOTIFY Call

**What people do:** Assume the bus payload (the full messages_sent, state_before, etc.) flows through pg_notify directly.
**Why it's wrong:** pg_notify has an 8000-byte default limit for the NOTIFY payload — but this limit applies to the *channel list* notification, not the bus message content. The actual bus event data is written to the `bus_bus` table as JSONB and fetched separately. Full payloads are safe in `bus.bus._sendone()` messages.
**Do this instead:** Send full payloads via `bus.bus._sendone()` without concern for pg_notify size limits. The bus infrastructure handles chunking of the NOTIFY channel list if needed.

### Anti-Pattern 2: Using DB Integer IDs in Bus Payloads

**What people do:** Generate IDs server-side as sequential integers (mimicking DB autoincrement) since there are no DB records.
**Why it's wrong:** Sequential integers create ordering dependencies — if two tool calls fire concurrently, the client can't distinguish them by arrival order. UUIDs are collision-free and make payloads self-describing.
**Do this instead:** `trace_id = str(uuid.uuid4())` at loop start. Same for `iteration_id` and `tool_call_id`.

### Anti-Pattern 3: Including the Odoo Backend Navbar in the Standalone App

**What people do:** Use `ir.actions.client` in the backend for "standalone" feel.
**Why it's wrong:** The backend navbar, debug toolbar, and chat widget are always rendered. CSS hacks (like v1.0's `o_ai_debug_standalone` class) to hide them are fragile — every Odoo update can break them.
**Do this instead:** Serve a full HTML page from a dedicated controller. The page has no `<t t-call="web.layout"/>` — it is its own document root.

### Anti-Pattern 4: Fetching Data On Selection (ORM Read on Click)

**What people do:** Store only IDs in state and fetch full data when the user clicks a node.
**Why it's wrong:** In v1.1 there is no DB to fetch from. All data must be in the bus payload, in memory, at selection time.
**Do this instead:** Store complete data in the state Map at event receipt time. Selection is purely a pointer into already-held state — zero network requests on click.

### Anti-Pattern 5: One Asset Bundle Per Page That Includes All of `web.assets_backend`

**What people do:** Set `'assets': {'web.assets_backend': ['ai_debug/static/src/**/*']}` for the standalone app files.
**Why it's wrong:** `web.assets_backend` loads only in the Odoo backend webclient. The standalone app at `/ai-debug` renders its own HTML page with its own `<t t-call-assets="ai_debug.assets"/>`. Files added to `web.assets_backend` are invisible there.
**Do this instead:** Declare a dedicated bundle `ai_debug.assets` in `__manifest__.py`. Include it in the `ai_debug.index` template. Keep backend-only files (menu XML, action XML) in `web.assets_backend` if they still exist, but the app files go in `ai_debug.assets`.

---

## Build Order for v1.1

Dependencies determine this order:

1. **Controller + template** (`controllers/main.py`, `views/templates.xml`) — the URL must resolve before any frontend can load. Can be verified by hitting `/ai-debug` in a browser (should render a blank page with asset errors, not a 404).

2. **Asset bundle + `main.js` + root `AiDebugApp`** — stub component that mounts and logs "AI Debug loaded". Verifies the entire bootstrap chain (route → template → bundle → OWL env → services). Confirms `bus_service` is available.

3. **Python instrumentation update** (`ai_session.py`) — strip DB model writes, generate UUIDs, emit full payloads. Verifiable by triggering an agentic loop and watching browser console for bus events (add `console.log` in handlers temporarily).

4. **Sidebar `TraceList` and `LoopItem`** — receive bus events, render trace rows. First visible output.

5. **`IterationItem` and `ToolCallItem`** — complete the 3-level tree. Nesting requires iteration and tool_call payloads proven in step 3.

6. **`DetailPanel` with sub-components** — `LoopDetail`, `IterationDetail`, `ToolCallDetail`. Depends on sidebar selection being wired (step 4-5).

7. **`JsonTree` and `StateDiff` integration** — port from v1.0, plug into detail components. These are self-contained presentational components.

8. **Cleanup** — delete all v1.0-only files (`models/ai_debug_*.py`, `security/`, `views/ai_debug_*_views.xml`, `views/menus.xml`). Update `__manifest__.py` to remove their data declarations and the old `web.assets_backend` assets entry.

---

## Sources

- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/controllers/main.py` — `pos_web` controller, `request.render('point_of_sale.index', context)`, `session_info` injection (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — `point_of_sale.index` template structure, `odoo` JS global with `__session_info__`, `t-call-assets` (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/__manifest__.py` — `point_of_sale.assets_prod`, `base_app` bundle structure including bus service files (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/static/src/app/main.js` — `mountComponent(Chrome, document.body)` boot pattern (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/views/pos_self_order.index.xml` — simpler template: inlines `__session_info__`, single `t-call-assets` (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/static/src/app/root.js` — `mountComponent(Index, document.body)` — cleanest boot example (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/hr_attendance/views/hr_attendance_kiosk_templates.xml` — `web.layout` alternative, inline script calling `createPublicKioskAttendance` (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/hr_attendance/static/src/public_kiosk/public_kiosk_app.js` — `makeEnv()` + `startServices()` + `new App(...)` explicit boot (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/env.js` — `mountComponent`, `makeEnv`, `startServices` implementations (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `NOTIFY_PAYLOAD_MAX_LENGTH` applies to channel list, not bus message content; `_sendone` stores payload in JSONB `bus_bus` table (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/custom/ai_debug/models/ai_session.py` — existing v1.0 instrumentation, `_debug_strip_binaries`, `_debug_bus_send`, separate cursor pattern (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/custom/ai_debug/models/ir_websocket.py` — channel access control for `ai_debug:*` channels (HIGH confidence — direct source read)
- Source: `/Users/joseph/clones/odoo/custom/ai_debug/static/src/debug_panel/debug_panel.js` — v1.0 OWL bus subscription patterns, state shape, event handler structure (HIGH confidence — direct source read)

---
*Architecture research for: Odoo AI debugger v1.1 — standalone OWL app conversion*
*Researched: 2026-02-20*
