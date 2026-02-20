# Stack Research

**Domain:** Custom Odoo module — AI agentic loop debugger
**Researched:** 2026-02-20
**Confidence:** HIGH (all patterns verified against Odoo master source code)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python (Odoo ORM) | 3.10+ (Odoo master) | Persistent debug models + instrumentation | Model inheritance (`_inherit`) is the only zero-behavioral-change way to wrap generator methods. The ORM handles persistence, security, and the query layer automatically. |
| OWL (Odoo Web Library) | 2.8.1 (bundled in Odoo master) | Live debug panel OWL components | OWL 2.x is Odoo's mandatory frontend framework. You get it for free — importing `Component, useState, useEffect, onMounted, onWillUnmount` from `@odoo/owl`. |
| bus.bus (Odoo bus) | Odoo master (websocket-based) | Real-time push from backend to frontend | The standard Odoo mechanism. `env.user._bus_send(type, payload)` on the Python side; `bus_service.subscribe(type, callback)` on the JS side. No custom websocket server needed. |
| Odoo backend views (XML) | Odoo master | History list/form views for traces | Standard `ir.actions.act_window` + list/form XML views. Works out of the box on any Odoo install. No extra frontend framework needed. |
| ir.actions.client + OWL Component | Odoo master | Live debug panel as a standalone page | The canonical Odoo pattern for custom full-page UI. Register a component in `registry.category("actions")`, point an `ir.actions.client` at it. |

### Supporting Technologies (Verified Patterns)

| Technology | Purpose | Verified Source |
|------------|---------|----------------|
| `bus.listener.mixin` | Mixin that adds `_bus_send()` to any model | `addons/bus/models/bus_listener_mixin.py` |
| `ir.websocket` (`_build_bus_channel_list`) | Override to authorize custom bus channels | `addons/bus/models/ir_websocket.py`, `addons/hr_attendance/models/ir_websocket.py` |
| `ir.config_parameter` | Module configuration (enable/disable, retention) | `ai/models/ai_session.py` lines 166, 387 |
| `@api.autovacuum` | Scheduled GC for old debug records | `addons/bus/models/bus.py` line 121 |
| `useService("bus_service")` / `this.env.services.bus_service` | OWL hook to access bus in components | `addons/web/static/src/core/utils/hooks.js` line 153 |
| `registry.category("services").add(...)` | Register a background OWL service | `addons/calendar/static/src/js/services/calendar_notification_service.js` |
| `registry.category("actions").add(...)` | Register a client action component | `addons/web/static/src/webclient/actions/action_install_kiosk_pwa.js` |

---

## Bus.bus Architecture (Verified Against Source)

This is the most important pattern to understand correctly. The bus has two layers:

**Python side — sending:**
```python
# Option A (recommended): use BusListenerMixin._bus_send
# Sends to the current user's partner channel (auto-subscribed by all logged-in users)
self.env.user._bus_send("AI_DEBUG_EVENT", {"type": "tool_call", "payload": {...}})

# Option B (direct): send to arbitrary channel (requires _build_bus_channel_list override)
self.env["bus.bus"]._sendone("my_custom_channel", "MY_TYPE", {...})
```

**Why Option A is simpler:**
`res_users._bus_channel()` returns `self.partner_id` (verified in `addons/bus/models/res_users.py`). The base `_build_bus_channel_list` in `ir_websocket.py` automatically adds `self.env.user.partner_id` to every authenticated user's subscription list. So any message sent via `env.user._bus_send()` arrives at the frontend without any custom channel wiring.

**JS side — receiving:**
```javascript
// In a service (background, no component lifecycle)
export const aiDebugService = {
    dependencies: ["bus_service"],
    start(env, { bus_service }) {
        bus_service.subscribe("AI_DEBUG_EVENT", (payload) => {
            // handle incremental update
        });
        bus_service.start(); // activates websocket connection
    },
};
registry.category("services").add("ai.debug", aiDebugService);

// In a component (lifecycle-managed)
setup() {
    this.busService = useService("bus_service");
    onMounted(() => {
        this.busService.subscribe("AI_DEBUG_EVENT", this.onDebugEvent.bind(this));
        this.busService.start();
    });
    onWillUnmount(() => {
        this.busService.unsubscribe("AI_DEBUG_EVENT", this.onDebugEvent.bind(this));
    });
}
```

The `bus_service.start()` call is required. Without it the websocket does not connect. The AI module does this in `ai_natural_language_service.js` line 219.

**Important:** `_sendone` commits to `bus_bus` table via `precommit` hook, then fires `pg_notify('imbus', ...)` via `postcommit` hook. Messages are only delivered after the transaction commits. This is relevant to instrumentation — debug records and bus notifications must be in the same transaction, or the sequence must be understood.

---

## Module Structure

The standard Odoo module layout, verified against AI module source:

```
ai_debugger/
├── __manifest__.py              # module metadata, dependencies, assets
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── ai_session.py            # _inherit = 'ai.session' (instrumentation)
│   ├── ai_debug_trace.py        # models.Model (persistent)
│   ├── ai_debug_iteration.py    # models.Model (persistent)
│   ├── ai_debug_tool_call.py    # models.Model (persistent)
│   └── ir_websocket.py          # _inherit = 'ir.websocket' (only if custom channel needed)
├── security/
│   └── ir.model.access.csv      # required: one row per model per group
├── static/
│   └── src/
│       ├── services/
│       │   └── debug_service.js  # background bus subscriber, manages state
│       ├── components/
│       │   ├── DebugPanel/
│       │   │   ├── debug_panel.js
│       │   │   └── debug_panel.xml
│       │   └── ... (sub-components)
│       └── debug_client_action.js  # registers client action
└── views/
    ├── ai_debug_trace_views.xml    # list/form backend views
    ├── menus.xml                   # menu items under Settings > Technical
    └── assets.xml                  # (or inline in __manifest__.py assets dict)
```

### __manifest__.py Asset Registration Pattern

```python
{
    'name': 'AI Debugger',
    'depends': ['ai'],  # enterprise ai module
    'data': [
        'security/ir.model.access.csv',
        'views/ai_debug_trace_views.xml',
        'views/menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_debugger/static/src/**/*',
        ],
    },
    'license': 'LGPL-3',
}
```

Verified pattern: assets declared as glob in `web.assets_backend` — exactly how the AI module does it (`'ai/static/src/**/*'`).

---

## Python Instrumentation Pattern

The generator yield passthrough — the only correct way to instrument the agentic loop without behavioral change:

```python
class AiSessionDebug(models.TransientModel):
    _inherit = 'ai.session'

    def _run_agentic_loop(self, model, instructions, messages, temperature,
                          tools, tools_context, record=None, schema=None, web_grounding=False):
        # Open trace record before loop starts
        trace = self.env['ai.debug.trace'].create({...})
        try:
            for item in super()._run_agentic_loop(
                model=model, instructions=instructions, messages=messages,
                temperature=temperature, tools=tools, tools_context=tools_context,
                record=record, schema=schema, web_grounding=web_grounding
            ):
                # Record item, push bus notification
                self._debug_record_item(trace, item)
                yield item  # passthrough — zero behavioral change
        except Exception:
            trace.write({'state': 'error'})
            raise
        finally:
            trace.write({'state': 'done', ...})
```

**Why this works:** `_run_agentic_loop` is a generator. Python generators support `yield from super()...` or `for item in super()...: yield item`. Both patterns preserve the generator protocol. The caller (`_generate_next_response`) sees no difference. Verified against `ai_session.py` lines 381-416.

**Key constraint:** `ai.session` is a TransientModel. The inherited override is also TransientModel (inheriting the same `_transient = True` flag). But the debug records (`ai.debug.trace` etc.) must be persistent `models.Model` to survive session cleanup.

---

## OWL Component Pattern (Verified)

The canonical OWL component structure in Odoo master:

```javascript
// debug_panel.js
import { Component, useState, useEffect, onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class DebugPanel extends Component {
    static template = "ai_debugger.DebugPanel";
    static props = ["*"];  // client action passes action props

    setup() {
        super.setup();
        this.busService = useService("bus_service");
        this.orm = useService("orm");
        this.state = useState({
            traces: [],
        });

        onMounted(() => {
            this.busService.subscribe("AI_DEBUG_EVENT", this._onDebugEvent.bind(this));
            this.busService.start();
        });

        onWillUnmount(() => {
            this.busService.unsubscribe("AI_DEBUG_EVENT", this._onDebugEvent.bind(this));
        });
    }

    _onDebugEvent(payload) {
        // payload is already JSON.parse(JSON.stringify(payload)) — deep copy
        // mutate this.state directly (reactive)
        this.state.traces.push(payload);
    }
}

// Register as client action
registry.category("actions").add("ai_debugger.debug_panel", DebugPanel);
```

```xml
<!-- debug_panel.xml -->
<?xml version="1.0" encoding="UTF-8"?>
<templates>
    <t t-name="ai_debugger.DebugPanel">
        <div class="ai-debugger-panel">
            <t t-foreach="state.traces" t-as="trace" t-key="trace.id">
                <!-- render trace -->
            </t>
        </div>
    </t>
</templates>
```

```xml
<!-- ir.actions.client in views XML -->
<record id="action_ai_debug_panel" model="ir.actions.client">
    <field name="name">AI Debug Panel</field>
    <field name="tag">ai_debugger.debug_panel</field>
</record>
```

**Note on `bus_service.subscribe` callback:** The payload arrives as `JSON.parse(JSON.stringify(payload))` — a deep copy. Verified in `bus_service.js` line 211. Do not mutate the payload object; work with its values.

---

## Backend Views Pattern

Standard list + form views — no OWL required:

```xml
<!-- ai_debug_trace_views.xml -->
<record id="view_ai_debug_trace_list" model="ir.ui.view">
    <field name="name">ai.debug.trace.list</field>
    <field name="model">ai.debug.trace</field>
    <field name="arch" type="xml">
        <list>
            <field name="create_date"/>
            <field name="agent_id"/>
            <field name="llm_model"/>
            <field name="state"/>
            <field name="iteration_count"/>
            <field name="total_duration_ms"/>
        </list>
    </field>
</record>

<record id="action_ai_debug_trace" model="ir.actions.act_window">
    <field name="name">AI Debug Traces</field>
    <field name="res_model">ai.debug.trace</field>
    <field name="view_mode">list,form</field>
</record>
```

---

## Configuration Pattern (ir.config_parameter)

```python
# Reading a config param (Python)
enabled = self.env["ir.config_parameter"].sudo().get_param("ai_debugger.enabled", "True") == "True"
retention_days = int(self.env["ir.config_parameter"].sudo().get_param("ai_debugger.retention_days", "7"))

# Auto-vacuum old records
@api.autovacuum
def _gc_debug_records(self):
    cutoff = fields.Datetime.now() - timedelta(days=retention_days)
    self.search([('create_date', '<', cutoff)]).unlink()
```

Verified pattern from `bus.bus._gc_messages()` in `addons/bus/models/bus.py` lines 120-129.

---

## Security Model (ir.model.access.csv)

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_ai_debug_trace_system,ai.debug.trace,model_ai_debug_trace,base.group_system,1,1,1,1
access_ai_debug_iteration_system,ai.debug.iteration,model_ai_debug_iteration,base.group_system,1,1,1,1
access_ai_debug_tool_call_system,ai.debug.tool.call,model_ai_debug_tool_call,base.group_system,1,1,1,1
```

Developer tool — restrict to `base.group_system` (Technical / Settings access). Verified format from `ai/security/ir.model.access.csv`.

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| `env.user._bus_send()` (partner channel) | Custom string channel + `_build_bus_channel_list` override | User's partner channel is auto-subscribed for authenticated users. No extra server-side wiring needed. Custom string channels require overriding `ir.websocket` and validating channel access — more code, same result for a developer tool. |
| OWL Component as `ir.actions.client` | OWL Component embedded in existing Odoo view | Separate tab/page requirement from PROJECT.md. Client action pattern is the canonical way to get a full-page custom UI in Odoo. |
| Generator yield passthrough (`for item in super(): yield item`) | Monkey-patching or Python `wrapt` | `_inherit` is the only Odoo-idiomatic override mechanism. Monkey-patching breaks module isolation. `wrapt` is not available in Odoo's Python env and adds complexity. |
| `@api.autovacuum` for GC | `ir.cron` for scheduled cleanup | `@api.autovacuum` is the correct lightweight pattern for maintenance tasks. No XML data record needed. Verified in `bus.bus._gc_messages()`. |
| `models.Model` for debug records | `models.TransientModel` | `ai.session` is TransientModel and is cleaned up. Debug records must outlive the session. Must use `models.Model` (persistent). |
| Inline assets in `__manifest__.py` | Separate `views/assets.xml` | The AI module uses inline manifest assets (`'ai/static/src/**/*'`). Inline is cleaner for small modules. |
| `bus_service.subscribe()` in a background service | Polling via `orm.call()` in a component | Push is always better than poll for real-time UX. The bus service is the Odoo standard. No polling needed. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `models.TransientModel` for debug data | TransientModel records are cleaned up on session expiry and GC (`base.action_clead_session_log`). Debug traces would be lost. | `models.Model` (persistent) |
| Direct `env["bus.bus"]._sendone("string_channel", ...)` without `_build_bus_channel_list` override | String channels sent by client to subscribe are validated by `_prepare_subscribe_data`. Clients cannot subscribe to arbitrary strings — the server must whitelist them in `_build_bus_channel_list`. Without the override, the frontend can never receive notifications on a custom string channel. | `env.user._bus_send()` — uses the auto-subscribed partner channel |
| `yield from super()._run_agentic_loop(...)` without try/finally | If the loop raises, the trace record is never closed. The generator's `finally` block runs on GC, but timing is non-deterministic in CPython with generators. | `try/except/finally` wrapping the `for item in super()` loop |
| Importing `@odoo/owl` hooks outside of component `setup()` | OWL hooks must be called synchronously in `setup()`. Calling `useState`, `useEffect`, `useService` outside setup causes runtime errors. | Only call hooks inside `setup()` |
| `useService("bus_service")` without calling `bus_service.start()` | The bus_service starts lazily. If nothing calls `.start()` or `.addChannel()`, the websocket is never established and no notifications are received. | Call `bus_service.start()` in `onMounted()` or in the service's `start()` function |
| Monkey-patching AI module methods | Breaks when enterprise AI module updates. Not supported by Odoo's module system. | `_inherit = 'ai.session'` with method overrides |
| External JS build tooling (webpack, vite, esbuild) | Odoo uses its own asset bundler. External bundlers produce files that don't integrate with `web.assets_backend` and break Odoo's asset caching/versioning. | Declare files directly in `__manifest__.py assets` dict; Odoo bundles them |

---

## Version Compatibility

| Package/Pattern | Odoo Version | Notes |
|-----------------|--------------|-------|
| OWL 2.8.1 (bundled) | Odoo master | `import { Component } from "@odoo/owl"` — the module path alias is registered by Odoo's module loader. Do not `npm install @odoo/owl`. |
| `bus_service.subscribe(type, callback)` | Odoo 16+ (master) | Replaces the old `addEventListener` + `addChannel` pattern. Current API in master. |
| `env.user._bus_send(type, msg)` | Odoo 16+ (master) | `BusListenerMixin._bus_send()` added to `res.users` via `bus.listener.mixin`. |
| `@api.autovacuum` | All supported Odoo versions | Stable API. |
| `registry.category("actions").add(tag, Component)` | Odoo 16+ (master) | OWL 2 client action registration. Prior to 16 used `AbstractAction` class. |
| `useService()` from `@web/core/utils/hooks` | Odoo 16+ (master) | Current hook API. |
| `ir.websocket._build_bus_channel_list()` override | Odoo 16+ | Stable API for channel authorization. |

---

## Key Import Paths

All verified against Odoo master source:

```javascript
// OWL core
import { Component, useState, useEffect, onMounted, onWillUnmount, useRef } from "@odoo/owl";

// Odoo web core
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

// No npm installs needed — all are Odoo built-ins
```

```python
# Python model imports
from odoo import api, fields, models
from odoo.exceptions import UserError
# No external dependencies needed
```

---

## Sources

- `addons/bus/models/bus_listener_mixin.py` — `_bus_send()` / `BusListenerMixin` implementation (HIGH confidence)
- `addons/bus/models/res_users.py` — `res.users._bus_channel()` → routes to partner_id (HIGH confidence)
- `addons/bus/models/ir_websocket.py` — `_build_bus_channel_list`, `_prepare_subscribe_data` security model (HIGH confidence)
- `addons/bus/models/bus.py` — `_sendone()` commit hooks, `@api.autovacuum` GC pattern (HIGH confidence)
- `addons/bus/static/src/services/bus_service.js` — `subscribe()`, `start()`, `addChannel()` JS API (HIGH confidence)
- `addons/web/static/src/core/utils/hooks.js` — `useService()`, `useBus()` OWL hooks (HIGH confidence)
- `addons/web/static/src/webclient/actions/action_install_kiosk_pwa.js` — client action + OWL Component pattern (HIGH confidence)
- `addons/hr_attendance/models/ir_websocket.py` — custom string channel + `_build_bus_channel_list` override example (HIGH confidence)
- `addons/hr_attendance/static/src/components/hr_presence_status/hr_attendance_presence_status.js` — component-level bus subscription with lifecycle (HIGH confidence)
- `addons/calendar/static/src/js/services/calendar_notification_service.js` — service-level bus subscription pattern (HIGH confidence)
- `enterprise/ai/models/ai_session.py` — `_run_agentic_loop` generator, `_handle_tool_calls` generator, `env.user._bus_send()` usage (HIGH confidence)
- `enterprise/ai/static/src/ai_natural_language_service.js` — `bus_service.subscribe()` + `bus_service.start()` in a service (HIGH confidence)
- `enterprise/ai/static/src/web/systray_action.js` — OWL Component with `useService()`, `registry.category()` (HIGH confidence)
- `enterprise/ai/static/src/components/audio_visualizer/audio_visualizer.js` — `useState`, `useEffect`, `useRef`, `onMounted`, `onWillUnmount` usage (HIGH confidence)
- `addons/web/static/lib/owl/owl.js` line 5819 — OWL version 2.8.1 confirmed (HIGH confidence)

---

*Stack research for: AI Debugger custom Odoo module*
*Researched: 2026-02-20*
*All patterns verified against Odoo master source code at `/Users/joseph/clones/odoo/`*
