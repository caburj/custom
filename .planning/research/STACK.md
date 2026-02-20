# Stack Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer (v1.1)
**Researched:** 2026-02-20
**Confidence:** HIGH (all patterns verified against Odoo master source at `/Users/joseph/clones/odoo/`)

---

## What This Research Covers

v1.1 changes three things from v1.0:
1. Replace the `ir.actions.client` backend panel with a **true standalone OWL app** at `/ai-debug` (own HTML page, own asset bundle, own HTTP controller — same pattern as `point_of_sale.index`)
2. Carry **full payloads** over `bus.bus` instead of summary-only (no DB means no lazy ORM reads)
3. Render a **sidebar tree** (Loop > Iteration > Tool Call) with a master/detail layout

The v1.0 stack entries (generator yield passthrough, model inheritance, backend views) are NOT re-researched here. Only additions and changes are covered.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| OWL `mountComponent` | Odoo master (OWL 2.8.1) | Bootstrap standalone OWL app into `document.body` | `mountComponent` from `@web/env` creates its own OWL env, starts all registered services (including `bus_service`), and mounts the root component. Used identically by `point_of_sale/static/src/app/main.js` and `point_of_sale/static/src/customer_display/customer_display.js`. |
| Dedicated asset bundle (`ai_debug.assets_app`) | Odoo master | Isolate standalone app JS/CSS from backend | The standalone page loads exactly one `<t t-call-assets="..."/>` tag pointing to a module-defined bundle. POS uses `point_of_sale.assets_prod`; ai_debug needs `ai_debug.assets_app`. The bundle includes `web._assets_core` (OWL, session, bus services) via `point_of_sale.base_app` include pattern. |
| HTTP controller (`type='http'`, `auth='user'`) | Odoo master | Serve the `/ai-debug` HTML page | `request.render('ai_debug.index', context)` renders the QWeb template. `auth='user'` enforces login. Exact same pattern as `PosController.pos_web()` in `point_of_sale/controllers/main.py` line 52. |
| QWeb HTML template (`<template id="ai_debug.index">`) | Odoo master | Standalone HTML page shell | Declares `<!DOCTYPE html>`, injects `odoo` global with `csrf_token` and `__session_info__`, calls `t-call-assets`. Same structure as `point_of_sale/views/pos_assets_index.xml` and `pos_self_order/views/pos_self_order.index.xml`. |
| `bus_service` + `bus_service.subscribe()` | Odoo master | Receive full-payload events in standalone app | The bus service registers itself into the service registry and is started automatically by `mountComponent` → `startServices`. Works identically in standalone and backend contexts. |

### Supporting Libraries (All Pre-bundled in Odoo)

| Library | Purpose | Why / When |
|---------|---------|------------|
| `@web/core/utils/hooks` → `useService` | Access `bus_service`, `rpc` in OWL components | Standard hook for service injection. Works in standalone apps because `mountComponent` runs `startServices`. |
| `@odoo/owl` → `Component, useState, useRef, onMounted, onWillUnmount` | OWL component primitives | Reactive state, lifecycle hooks, DOM refs for the sidebar and detail panel. |
| `@web/session` → `session` | Read `csrf_token`, `db`, session data | Auto-populated from the `odoo.__session_info__` global injected by the HTML template. |
| `point_of_sale.base_app` (asset bundle include) | Pull in OWL, bootstrap, bus services, `@web/_assets_core` | Verified reuse pattern — `pos_self_order.assets` does `("include", "point_of_sale.base_app")`. Gives access to all `@web/*` import paths without pulling in the whole webclient. |

---

## Pattern 1: Standalone App Template + Controller

The exact pattern from `point_of_sale` and `pos_self_order`, adapted for ai_debug.

### QWeb HTML Template (`views/ai_debug_index.xml`)

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
<template id="ai_debug.index" name="AI Debug Tracer">&lt;!DOCTYPE html&gt;
<html>
    <head>
        <title>AI Debug Tracer</title>
        <meta http-equiv="content-type" content="text/html, charset=utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <script type="text/javascript">
            var odoo = <t t-out="json.dumps({
                'csrf_token': request.csrf_token(None),
                '__session_info__': session_info,
                'debug': debug,
            })"/>;
        </script>
        <t t-call-assets="ai_debug.assets_app"/>
    </head>
    <body></body>
</html>
</template>
</odoo>
```

**Why this works:**
- The `odoo` global is populated before any JS executes. `@web/session` reads from `odoo.__session_info__` to populate `session.db`, `session.csrf_token`, etc.
- `odoo.csrf_token` is required for any `rpc` calls from the standalone app.
- `<body></body>` is empty — OWL mounts into it via `mountComponent(RootComponent, document.body)`.
- `debug` is passed from `request.session.debug` so `?debug=1` URLs work.

**What NOT to put here:** Do not add `odoo.loadMenusPromise = Promise.resolve()` unless you explicitly include `web.assets_backend` in your bundle. POS does this to suppress menu loading; our bundle won't include the menu service at all.

### HTTP Controller (`controllers/main.py`)

```python
from odoo import http
from odoo.http import request

class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', sitemap=False)
    def ai_debug_index(self, **kwargs):
        if not request.env.user._is_internal():
            return request.not_found()
        session_info = request.env['ir.http'].session_info()
        debug = request.session.debug
        context = {
            'session_info': session_info,
            'debug': debug,
        }
        response = request.render('ai_debug.index', context)
        response.headers['Cache-Control'] = 'no-store'
        return response
```

**Why `auth='user'` not `auth='public'`:** Any internal user should be able to view traces (PROJECT.md: "any internal user"). `auth='user'` enforces login redirect automatically.

**Why `Cache-Control: no-store`:** Same reason as POS — the page bootstraps itself from the `odoo` global which contains user session data that should not be cached across logins.

**Why NOT `website=True`:** Adding `website=True` pulls in website module dependencies and wraps the response in a website layout. This is for a developer tool served on the Odoo backend domain — not a public website page.

### OWL App Entry Point (`static/src/app/main.js`)

```javascript
import { whenReady } from "@odoo/owl";
import { mountComponent } from "@web/env";
import { AiDebugApp } from "./ai_debug_app";

whenReady(async () => {
    await mountComponent(AiDebugApp, document.body);
});
```

**Why `whenReady` wraps `mountComponent`:** `whenReady` fires when the DOM is ready. `mountComponent` must not run before the DOM exists. This is the exact pattern from `customer_display.js` line 48: `whenReady(() => mountComponent(CustomerDisplay, document.body))`.

**Why `mountComponent` not `mount`:** `mountComponent` (from `@web/env`) calls `makeEnv()` and `startServices(env)` before mounting. This boots `bus_service`, `rpc`, `session`, and all other registered services. Plain `mount` (from `@odoo/owl`) skips this — the component would have no access to `env.services`. POS uses `mountComponent` in `main.js` line 31.

### Root OWL Component (`static/src/app/ai_debug_app.js`)

```javascript
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { Sidebar } from "./components/sidebar/sidebar";
import { DetailPanel } from "./components/detail_panel/detail_panel";

export class AiDebugApp extends Component {
    static template = "ai_debug.AiDebugApp";
    static components = { Sidebar, DetailPanel };
    static props = [];

    setup() {
        this.bus = useService("bus_service");
        // Bus service is already started by mountComponent → startServices.
        // Add the channel here; no need to call bus_service.start() separately.
        onMounted(() => {
            this.bus.addChannel("ai_debug:traces");
            this.bus.subscribe("ai_debug/loop_start", this._onLoopStart.bind(this));
            this.bus.subscribe("ai_debug/iteration", this._onIteration.bind(this));
            this.bus.subscribe("ai_debug/tool_call", this._onToolCall.bind(this));
            this.bus.subscribe("ai_debug/loop_end", this._onLoopEnd.bind(this));
        });
        onWillUnmount(() => {
            this.bus.deleteChannel("ai_debug:traces");
            // unsubscribe each type ...
        });
    }
}
```

**Why `addChannel` not `start`:** In the backend the `bus_service` auto-starts when the webclient loads. In a standalone app started via `mountComponent`, `startServices` runs all registered service `start()` functions, which includes `bus_service`. The bus_service starts its WebSocket worker when `addChannel` or `start` is called. `addChannel` is the idiomatic call — it both registers the channel and starts the connection. Verified in `bus_service.js` lines 174-181: `addChannel` calls `ensureWorkerStarted()` and then `workerService.send("BUS:START")`.

### Asset Bundle (`__manifest__.py`)

```python
'assets': {
    # v1.1 standalone app bundle
    'ai_debug.assets_app': [
        # Pull in OWL, session, bus services, @web/_assets_core
        ('include', 'point_of_sale.base_app'),
        # App files — order matters: components before app, app before main
        'ai_debug/static/src/app/**/*.scss',
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
        # main.js must be last — it calls mountComponent
        ('remove', 'ai_debug/static/src/app/main.js'),
        'ai_debug/static/src/app/main.js',
    ],
    # v1.0 backend panel — remove when v1.1 is shipped
    'web.assets_backend': [
        'ai_debug/static/src/debug_panel/**/*.js',
        'ai_debug/static/src/debug_panel/**/*.xml',
        'ai_debug/static/src/debug_panel/**/*.scss',
    ],
},
```

**Why `point_of_sale.base_app` include:** This bundle (defined in `point_of_sale/__manifest__.py` lines 124-145) includes `web._assets_helpers`, `web._assets_backend_helpers`, Bootstrap SCSS, `web._assets_core` (OWL + all `@web/*` modules), and crucially the bus service files (`bus/static/src/services/bus_service.js` etc.). Without this include, `@web/env`, `@web/session`, `@web/core/utils/hooks` would not be resolvable.

**Why NOT `web.assets_backend`:** The standalone app page does NOT load `web.assets_backend`. Adding the app files to `web.assets_backend` would load them in the Odoo webclient too, causing double-registration and conflicts. The standalone bundle must be separate.

**Why `main.js` last via remove/re-add:** The app files glob includes `main.js`, but `main.js` must execute after all components and services are registered. The remove+re-add pattern is the standard Odoo approach. Verified in `point_of_sale/__manifest__.py` lines 198-199 and 225-228.

---

## Pattern 2: Full Bus Payloads (No DB)

v1.1 drops the database. All trace data travels over `bus.bus` in the payload of each event. This changes the Python send code and the JS receive code.

### Payload Size Constraints

The `bus.bus` notification system has two size limits that work differently:

**DB row size (message column):** The `bus_bus.message` column is `Char` (text) — no inherent size limit in PostgreSQL. Messages up to several MB are technically possible.

**pg_notify payload limit:** PostgreSQL's `pg_notify` has an 8000-byte limit per payload. However, `bus.bus._sendone` does NOT put the message in the `pg_notify` payload. It puts only the **channel names** in `pg_notify` (via `get_notify_payloads` in `bus.py` lines 92-109). The actual message stays in the `bus_bus` table. The websocket worker fetches messages by ID after receiving the pg_notify trigger. Verified: `bus.py` lines 163-188 — `postcommit` fires pg_notify with channel names only; message content is fetched by `fetch_bus_notifications` from the table.

**Practical limit:** The message can be arbitrarily large as far as the bus infrastructure is concerned. The real constraint is WebSocket frame reassembly (typically 16MB before OOM) and frontend memory for accumulating events. For an AI debugger, full message payloads (system prompt, conversation history, LLM response) can easily be 50-200KB per iteration. This is fine.

**Binary stripping still required:** Images and audio in content parts (`type != 'text'`) must still be stripped before sending. A full unstripped multimodal conversation could be megabytes. The existing `_debug_strip_binaries()` method from v1.0 is reused for this.

### Python: Full Payload Pattern

```python
def _debug_bus_send_loop_start(self, env, loop_id, payload):
    """Send full loop-start payload over bus.

    Payload carries everything the frontend needs for this loop node:
    - system prompt (instructions)
    - tools definition (JSON schema of all tools)
    - RAG context
    All large payloads must have binaries stripped first.
    """
    env['bus.bus']._sendone('ai_debug:traces', 'ai_debug/loop_start', {
        'loop_id': loop_id,
        'agent_name': payload.get('agent_name'),
        'instructions': payload.get('instructions'),        # full text OK
        'tools_definition': payload.get('tools_definition'), # JSON list OK
        'rag_context': payload.get('rag_context'),
        'timestamp': payload.get('timestamp'),
    })

def _debug_bus_send_iteration(self, env, loop_id, iter_id, payload):
    """Send full iteration payload — messages_sent and raw_response are large."""
    messages_stripped = self._debug_strip_binaries(payload.get('messages_sent', []))
    env['bus.bus']._sendone('ai_debug:traces', 'ai_debug/iteration', {
        'loop_id': loop_id,
        'iter_id': iter_id,
        'index': payload.get('index'),
        'messages_sent': messages_stripped,  # full conversation history
        'raw_response': payload.get('raw_response'),  # LLM response object
        'duration_ms': payload.get('duration_ms'),
    })
```

**Why send on commit:** `_sendone` queues the message via `precommit` and fires `pg_notify` via `postcommit`. The message is only delivered to the frontend after the transaction commits. For a no-DB design, the instrumentation cursor commits immediately after the yield — the message arrives at the frontend within milliseconds of the agentic loop yielding.

**Why global channel `ai_debug:traces`:** All events go to the same channel. The frontend subscribes once to this channel. Using per-loop channels would require the frontend to subscribe before the first event, creating a race condition. The global channel pattern eliminates that race. Validated by existing v1.0 architecture decision in PROJECT.md.

### JS: Receive Full Payload

```javascript
// In AiDebugApp or a dedicated store service
_onIteration(payload) {
    // payload.messages_sent is the full conversation array
    // payload.raw_response is the full LLM response object
    // Store directly in reactive state — no ORM read needed
    const loopNode = this.state.loops.find(l => l.id === payload.loop_id);
    if (!loopNode) return;
    loopNode.iterations.push({
        id: payload.iter_id,
        index: payload.index,
        messages_sent: payload.messages_sent,  // already available
        raw_response: payload.raw_response,     // already available
        duration_ms: payload.duration_ms,
        toolCalls: [],
    });
}
```

**Critical difference from v1.0:** In v1.0, `_onIteration` received only summary fields (id, index, duration_ms) and the user had to click "expand" to trigger an ORM read for `messages_sent` and `raw_response`. In v1.1 the full data arrives in the bus event. No lazy loading, no ORM, no expand toggle needed for already-received data.

---

## Pattern 3: Sidebar Tree Component

The sidebar shows a 3-level tree: Loop > Iteration > Tool Call. This is a selection-driven master/detail layout. OWL reactive state is the right tool.

### State Shape

```javascript
// In the root component or a shared store service
this.state = useState({
    loops: [
        // { id, agent_name, instructions, tools_definition, status, iterations: [...] }
    ],
    selected: { type: null, loopId: null, iterId: null, toolId: null },
});
```

**Why flat selection object not nested IDs in each node:** A single `selected` object makes it trivial to determine what the detail panel should show. Any component can read `this.state.selected` and render accordingly without prop drilling.

### Sidebar Component Pattern

```javascript
// static/src/app/components/sidebar/sidebar.js
import { Component } from "@odoo/owl";

export class Sidebar extends Component {
    static template = "ai_debug.Sidebar";
    static props = {
        loops: Array,
        selected: Object,
        onSelect: Function,
    };

    selectLoop(loopId) {
        this.props.onSelect({ type: 'loop', loopId });
    }

    selectIteration(loopId, iterId) {
        this.props.onSelect({ type: 'iteration', loopId, iterId });
    }

    selectToolCall(loopId, iterId, toolId) {
        this.props.onSelect({ type: 'tool_call', loopId, iterId, toolId });
    }
}
```

```xml
<!-- sidebar.xml -->
<t t-name="ai_debug.Sidebar">
    <div class="ai-debug-sidebar">
        <t t-foreach="props.loops" t-as="loop" t-key="loop.id">
            <div class="sidebar-loop"
                 t-att-class="{ selected: props.selected.loopId === loop.id and props.selected.type === 'loop' }"
                 t-on-click="() => this.selectLoop(loop.id)">
                <span t-out="loop.agent_name || 'Loop'"/>
                <span class="badge" t-out="loop.status"/>
            </div>
            <t t-foreach="loop.iterations" t-as="iter" t-key="iter.id">
                <div class="sidebar-iteration"
                     t-att-class="{ selected: props.selected.iterId === iter.id }"
                     t-on-click="() => this.selectIteration(loop.id, iter.id)">
                    Iteration <t t-out="iter.index + 1"/>
                </div>
                <t t-foreach="iter.toolCalls" t-as="tc" t-key="tc.id">
                    <div class="sidebar-tool-call"
                         t-att-class="{ selected: props.selected.toolId === tc.id, failed: !tc.success }"
                         t-on-click="() => this.selectToolCall(loop.id, iter.id, tc.id)">
                        <t t-out="tc.name"/>
                    </div>
                </t>
            </t>
        </t>
    </div>
</t>
```

**Why callback prop `onSelect` not EventBus:** OWL 2.x encourages parent-down props and callbacks-up for component communication. The root component owns `state.selected`; the sidebar calls `onSelect` to mutate it. The detail panel reads `state.selected` reactively. No EventBus plumbing needed.

**Why `t-foreach` with `t-key`:** OWL requires `t-key` for efficient list diffing. Using the item ID (not index) prevents stale DOM when loops/iterations are added mid-stream.

### Detail Panel Pattern

```javascript
// static/src/app/components/detail_panel/detail_panel.js
import { Component } from "@odoo/owl";
import { JsonTree } from "../json_tree/json_tree";

export class DetailPanel extends Component {
    static template = "ai_debug.DetailPanel";
    static components = { JsonTree };
    static props = {
        loops: Array,
        selected: Object,
    };

    get selectedNode() {
        const { type, loopId, iterId, toolId } = this.props.selected;
        const loop = this.props.loops.find(l => l.id === loopId);
        if (!loop) return null;
        if (type === 'loop') return { type, data: loop };
        const iter = loop.iterations.find(i => i.id === iterId);
        if (!iter) return null;
        if (type === 'iteration') return { type, data: iter };
        const tc = iter.toolCalls.find(t => t.id === toolId);
        return tc ? { type, data: tc } : null;
    }
}
```

```xml
<t t-name="ai_debug.DetailPanel">
    <div class="ai-debug-detail">
        <t t-if="!this.selectedNode">
            <p class="text-muted">Select an item from the sidebar.</p>
        </t>
        <t t-elif="this.selectedNode.type === 'loop'">
            <h3>Loop: <t t-out="this.selectedNode.data.agent_name"/></h3>
            <JsonTree data="this.selectedNode.data.instructions" label="'System Prompt'"/>
            <JsonTree data="this.selectedNode.data.tools_definition" label="'Tools'"/>
        </t>
        <t t-elif="this.selectedNode.type === 'iteration'">
            <h3>Iteration <t t-out="this.selectedNode.data.index + 1"/></h3>
            <JsonTree data="this.selectedNode.data.messages_sent" label="'Messages Sent'"/>
            <JsonTree data="this.selectedNode.data.raw_response" label="'LLM Response'"/>
        </t>
        <t t-elif="this.selectedNode.type === 'tool_call'">
            <h3>Tool: <t t-out="this.selectedNode.data.name"/></h3>
            <JsonTree data="this.selectedNode.data.args" label="'Arguments'"/>
            <JsonTree data="this.selectedNode.data.result" label="'Result'"/>
            <JsonTree data="this.selectedNode.data.state_before" label="'State Before'"/>
            <JsonTree data="this.selectedNode.data.state_after" label="'State After'"/>
        </t>
    </div>
</t>
```

**Why computed `selectedNode` getter not a `useState` derived value:** OWL reactivity tracks property access in templates. `this.selectedNode` is a getter on the component class — OWL will re-evaluate it whenever `props.selected` or `props.loops` changes, because the template accesses `this.selectedNode` and that getter reads the reactive props. No extra `useState` needed.

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `ir.actions.client` for the standalone app | Client actions render inside the Odoo backend layout (navbar, breadcrumbs, action manager). The requirement is a true standalone page with no Odoo chrome — like POS, not like a backend panel. | HTTP controller + QWeb template + `mountComponent` |
| `web.assets_backend` for standalone app JS | Backend assets load inside the webclient. Adding the standalone app there causes double-registration of services and component tags, and makes the app load on every backend page. | Dedicated `ai_debug.assets_app` bundle |
| `mount` (from `@odoo/owl`) instead of `mountComponent` | `mount` skips `makeEnv` and `startServices`. The `bus_service`, `rpc`, and all other services are not started. The component tree has no `env.services`. | `mountComponent` from `@web/env` |
| Calling `bus_service.start()` manually in a standalone app | `mountComponent` → `startServices` registers the bus service. `addChannel()` triggers connection start automatically. Double-calling `start()` is harmless but unnecessary. | `bus_service.addChannel(channelName)` in `onMounted` |
| `@web/core/registry` import in `main.js` before `mountComponent` | Services are registered into the registry during module load (which happens before `whenReady`). This is fine. But if you call `registry.category("services").add(...)` inside `whenReady` after `startServices` has run, the service starts only after a registry UPDATE event — behavior is consistent but non-obvious. | Register services at module load time (top-level of the JS file), before `whenReady`. |
| Splitting the app across `web.assets_backend` and `ai_debug.assets_app` | If any component or service is defined in `web.assets_backend`, it won't be in the standalone page's bundle. Standalone app must be fully self-contained in its own bundle. | All standalone app files go in `ai_debug.assets_app` exclusively. |
| Using `session_info` from `ir.http` for the standalone app without `env['ir.http'].session_info()` | `session_info()` is an instance method that requires the model to be initialised with the request environment. Call it as `request.env['ir.http'].session_info()` in the controller, not `ir_http.session_info()`. | `session_info = request.env['ir.http'].session_info()` |
| EventBus for sidebar ↔ detail panel communication | Adds indirection when simple prop + callback suffices for a two-panel layout. OWL 2 is designed for props-down/callbacks-up. | Parent component owns `selected` state; passes `onSelect` callback to Sidebar and reads `selected` in DetailPanel. |

---

## Alternatives Considered

| Recommended | Alternative | When Alternative Makes Sense |
|-------------|-------------|-------------------------------|
| Standalone app + own asset bundle (POS pattern) | `ir.actions.client` + backend assets | When you want Odoo chrome (navbar, breadcrumbs, action manager). For a fullscreen developer tool with no Odoo UI chrome, standalone is correct. |
| `point_of_sale.base_app` include for core dependencies | `web.assets_backend` include | Never use `web.assets_backend` in a standalone bundle — it brings in the full Odoo webclient (action manager, menus, views). `point_of_sale.base_app` is a pre-assembled minimal core. |
| Single global channel `ai_debug:traces` for all events | Per-loop channels | Per-loop channels would require subscribing before the loop starts — a race. Global channel eliminates it. Would use per-loop channels only if privacy between concurrent users mattered. |
| Callbacks-up for sidebar selection | OWL EventBus or `env.bus` | EventBus would be appropriate if the sidebar and detail panel had no common ancestor (e.g., portals in different DOM trees). In a two-pane layout they always share a root — use props. |
| Full payload in bus event | Summary in bus event + ORM read on demand | ORM reads on demand (v1.0 approach) require DB models. v1.1 has no DB. Full payload in the bus event is the only option for a DB-free design. |

---

## File Layout for v1.1

```
ai_debug/
├── __manifest__.py              # updated: add ai_debug.assets_app bundle, remove old backend assets
├── controllers/
│   ├── __init__.py
│   └── main.py                  # NEW: HTTP controller for /ai-debug
├── models/
│   ├── ai_session.py            # updated: emit full payloads, no DB writes
│   └── ir_websocket.py          # kept: ai_debug: channel authorization
├── views/
│   └── ai_debug_index.xml       # NEW: QWeb HTML template (ai_debug.index)
└── static/
    └── src/
        └── app/
            ├── main.js          # NEW: whenReady → mountComponent(AiDebugApp, document.body)
            ├── ai_debug_app.js  # NEW: root Component, owns state, subscribes bus
            ├── ai_debug_app.xml # NEW: two-pane layout template
            └── components/
                ├── sidebar/
                │   ├── sidebar.js
                │   └── sidebar.xml
                ├── detail_panel/
                │   ├── detail_panel.js
                │   └── detail_panel.xml
                └── json_tree/   # CARRIED OVER from v1.0 (already built)
                    ├── json_tree.js
                    └── json_tree.xml
```

---

## Version Compatibility

| Pattern | Odoo Version | Notes |
|---------|--------------|-------|
| `mountComponent` from `@web/env` | Odoo 16+ (master) | Verified in `web/static/src/env.js` line 226. Stable API. |
| `whenReady` from `@odoo/owl` | OWL 2.x (Odoo 16+) | Fires when DOM is ready. Safe to wrap `mountComponent`. |
| `point_of_sale.base_app` bundle include | Odoo 17+ | Introduced when POS was refactored to standalone. On master this is the correct include path. |
| `bus_service.addChannel(name)` auto-starts connection | Odoo 16+ | Verified `bus_service.js` lines 174-181. |
| `bus_service.subscribe(type, callback)` | Odoo 16+ | Current API, replaces old `addEventListener` pattern. |
| `request.render(template, context)` for HTTP routes | All Odoo versions | Standard HTTP response pattern. |

---

## Sources

All patterns verified against Odoo master source, not training data:

- `addons/point_of_sale/views/pos_assets_index.xml` — QWeb standalone HTML template structure (HIGH confidence)
- `addons/point_of_sale/controllers/main.py` lines 52-123 — HTTP controller `pos_web()` pattern (HIGH confidence)
- `addons/point_of_sale/static/src/app/main.js` — `mountComponent` with `whenReady` bootstrap (HIGH confidence)
- `addons/point_of_sale/static/src/customer_display/customer_display.js` line 48 — minimal `whenReady(() => mountComponent(...))` pattern (HIGH confidence)
- `addons/point_of_sale/__manifest__.py` lines 124-228 — `point_of_sale.base_app`, `point_of_sale.assets_prod`, remove+re-add `main.js` last (HIGH confidence)
- `addons/pos_self_order/views/pos_self_order.index.xml` — simpler QWeb template without POS-specific session fields (HIGH confidence)
- `addons/pos_self_order/controllers/self_entry.py` — minimal controller using `request.render()` (HIGH confidence)
- `addons/pos_self_order/__manifest__.py` lines 57-61 — `("include", "point_of_sale.base_app")` in custom bundle (HIGH confidence)
- `addons/pos_self_order/static/src/app/root.js` — `whenReady(async () => { await mountComponent(...) })` pattern (HIGH confidence)
- `addons/web/static/src/env.js` lines 226-250 — `mountComponent` implementation: `makeEnv()` → `startServices()` → `App.mount()` (HIGH confidence)
- `addons/bus/static/src/services/bus_service.js` lines 174-181 — `addChannel()` calls `ensureWorkerStarted()` and `BUS:START` (HIGH confidence)
- `addons/bus/models/bus.py` lines 92-188 — pg_notify carries channel names only, not message content; messages fetched by ID from table (HIGH confidence)

---

*Stack research for: AI Debugger v1.1 — standalone OWL app at /ai-debug*
*Researched: 2026-02-20*
*All patterns verified against Odoo master source code*
