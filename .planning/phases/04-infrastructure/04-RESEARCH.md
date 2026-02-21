# Phase 4: Infrastructure - Research

**Researched:** 2026-02-21
**Domain:** Odoo standalone OWL app, HTTP controller, bus_service, v1.0 cleanup
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**App shell skeleton:**
- Scaffold the sidebar + detail panel split layout from the start with placeholder content (later phases fill it in)
- Include a thin header/toolbar at the top for app title and connection status
- Stub sidebar shows empty state; stub detail panel shows "Listening for agentic loops..." with animated indicator (pulsing dot or similar)

**v1.0 cleanup scope:**
- Delete all v1.0 Python model files entirely — no refactoring to dataclasses, clean slate for Phase 5
- Delete all backend view XML, menu XML, and security CSV (ir.model.access) files
- Rewrite `__manifest__.py` from scratch — fresh manifest declaring only what v1.1 needs
- Keep `ai` module as a dependency (that's where the agentic loop lives)

**Instrumentation hooks:**
- Claude's discretion on whether to keep or delete v1.0 instrumentation hooks — assess what's reusable vs too coupled to ORM

**Access & discovery:**
- Add a button in the `debug_menu.js` component that opens `/ai-debug` in a new tab
- Debug menu is already gated behind debug mode — no extra gating needed on the button
- The `/ai-debug` route itself requires any internal user (`base.group_user`) — no debug mode check on the route

**Bus connection UX:**
- Subscribe to a single `ai_debug` bus channel — different event types (new_trace, iteration, tool_call, etc.) are distinguished by message type within the payload
- Always-visible connection status indicator in the header — green dot for connected, red for disconnected
- Auto-reconnect silently on connection drop — status dot goes red briefly, then green; no banner or user action needed
- Empty state: animated indicator (pulsing dot) + "Listening for agentic loops..." text

### Claude's Discretion
- Visual direction (dark/light theme) — pick what fits a developer debugging tool
- Loading skeleton and exact spacing/typography
- Error state handling
- Exact animated indicator design for the listening state
- How to structure the bus message type field within payloads

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | User can access the live tracer at `/ai-debug` as a standalone OWL app (no Odoo navbar/chrome) | HTTP controller with `auth="user"`, renders custom HTML template with own asset bundle; `mountComponent` from `@web/env` boots full service registry including bus_service |
| INFRA-02 | Any internal user (`base.group_user`) can access the app | Controller uses `is_user_internal()` check (same as web_client); `ir.websocket._build_bus_channel_list` override gates channel to internal users (`_is_internal()`) not just system users |
| INFRA-03 | App boots with full Odoo service registry (bus_service, session, etc.) | Custom asset bundle includes `web.assets_backend`; `mountComponent` auto-starts service registry via `makeEnv()` + `startServices()`; `session_info` is injected into `odoo.__session_info__` by the controller |
| MIGR-02 | All v1.0 backend views, menus, security CSV, and ORM model files are deleted | Five Python model files identified for deletion; three view XMLs + menus.xml; one security CSV; manifest rewritten; debug_panel_action.xml kept (repurposed) or also deleted (new controller replaces it) |
</phase_requirements>

---

## Summary

Phase 4 has two distinct workstreams: (1) deleting the v1.0 DB-backed architecture, and (2) scaffolding the v1.1 standalone OWL app at `/ai-debug`. These are independent and can be planned/executed in either order, though deletion first makes the new manifest easier to write from scratch.

The standalone app pattern is well-established in Odoo via `pos_self_order`: define a custom asset bundle in the manifest that includes `web.assets_backend` (which carries all core services including `bus_service`), write a custom entry-point JS file that calls `mountComponent` from `@web/env`, write a QWeb HTML template the controller renders, and write a Python HTTP controller at `@http.route('/ai-debug', auth='user')`. The controller injects `session_info` into `odoo.__session_info__` so the service registry (particularly `session` and `user` services) boots correctly. The `ir.websocket._build_bus_channel_list` override must be updated to gate the `ai_debug` channel to internal users (not just system users as in v1.0).

The v1.0 code to delete is well-bounded: 4 ORM model files + `ir_websocket.py` (keep, but update) + 4 view XML files + 1 security CSV. The v1.0 `ai_session.py` instrumentation hooks are tightly coupled to ORM (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call` models), so they must be deleted — there is nothing reusable for Phase 5.

**Primary recommendation:** Implement a dedicated HTTP controller at `/ai-debug` rendering a minimal QWeb template with a custom `ai_debug.assets` bundle. Do not reuse the `ir.actions.client` / web-client-router approach from v1.0 — it cannot deliver a truly navbar-free page.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@web/env` → `mountComponent` | Odoo master | Boot OWL app with full service registry | The only supported way to start a self-contained Odoo OWL app with all services |
| `bus/static/src/services/bus_service.js` | Odoo master | WebSocket long-poll bus | Included in `web.assets_backend`; the established channel subscription API |
| `odoo.http.Controller` + `@http.route` | Odoo master | Serve the standalone HTML page | Standard Python HTTP controller pattern |
| `request.render(template, qcontext)` | Odoo master | Render the QWeb HTML page | Same as `pos_self_order` and `web_client` controllers |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `web.assets_backend` | Odoo master | Full Odoo JS runtime (OWL + all services) | Included in custom bundle; provides bus_service, rpc, session, user, etc. |
| `ir.http.session_info()` | Odoo master | Full backend session info injected as `odoo.__session_info__` | Required for service registry to boot correctly |
| `web.layout` QWeb template | Odoo master | Minimal HTML skeleton with csrf_token + `odoo` global | Use as the base template via `t-call="web.layout"` |
| `from odoo.web.controllers.utils import is_user_internal, ensure_db` | Odoo master | Auth/redirect helpers | Exact same pattern used by `home.web_client` |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom HTTP controller | `ir.actions.client` + Odoo router | `ir.actions.client` serves the page inside the full Odoo web client shell — you hide the navbar via CSS but the navbar DOM is still there. True standalone requires an HTTP controller. |
| `web.assets_backend` in custom bundle | `pos_self_order` base_app pattern (stripped bundle) | The stripped bundle is appropriate when you cannot depend on the full backend (e.g., public-access apps). For an internal-user-only dev tool, the full backend bundle is simpler and correct. |
| `session_info()` | `get_frontend_session_info()` | `get_frontend_session_info()` is for public/website pages; `session_info()` includes `user_companies`, `user_context`, and all fields needed by backend services. Use `session_info()`. |

---

## Architecture Patterns

### Recommended Project Structure

After Phase 4, the module should look like:

```
ai_debug/
├── __init__.py
├── __manifest__.py                          # Rewritten from scratch
├── controllers/
│   ├── __init__.py
│   └── main.py                              # HTTP controller for /ai-debug
├── models/
│   ├── __init__.py
│   └── ir_websocket.py                      # Updated channel gating (internal users)
├── static/
│   └── src/
│       ├── app/
│       │   ├── app.js                       # Root OWL component
│       │   ├── app.xml                      # Root template
│       │   ├── app.scss                     # Base styles (dark theme)
│       │   └── main.js                      # Entry point: mountComponent(App, document.body)
│       └── debug_menu_button.js             # Debug menu item registration
└── views/
    └── ai_debug_index.xml                   # QWeb HTML page template
```

The v1.0 `debug_panel/`, `json_tree/`, and `state_diff/` components are deleted entirely (fresh start for Phase 5+).

### Pattern 1: HTTP Controller for Standalone App

**What:** A Python controller renders a QWeb template. The template injects `session_info` and loads a custom asset bundle. No Odoo navbar is rendered.

**When to use:** Any Odoo route that must be served as a full standalone page for authenticated internal users.

**Example:**
```python
# controllers/main.py
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import ensure_db, is_user_internal

class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        ensure_db()
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        session_info = request.env['ir.http'].session_info()
        return request.render('ai_debug.index', {
            'session_info': session_info,
        })
```

Note: `auth='user'` handles the login redirect automatically for unauthenticated requests. The `is_user_internal()` check catches portal users who have a session but are not internal.

### Pattern 2: Custom Asset Bundle with Own Entry Point

**What:** The manifest declares a custom bundle (e.g., `ai_debug.assets`) that includes `web.assets_backend` and adds the module's own JS/SCSS. A dedicated `main.js` calls `mountComponent`.

**Example manifest assets section:**
```python
'assets': {
    'ai_debug.assets': [
        ('include', 'web.assets_backend'),
        'ai_debug/static/src/app/**/*.scss',
        'ai_debug/static/src/app/**/*.xml',
        'ai_debug/static/src/app/**/*.js',
    ],
    'web.assets_backend': [
        'ai_debug/static/src/debug_menu_button.js',
    ],
}
```

The `web.assets_backend` entry registers the debug menu button into the debug registry. The `ai_debug.assets` bundle is only loaded on the standalone page.

### Pattern 3: QWeb Index Template

**What:** A minimal QWeb template that serves as the HTML shell for the standalone page.

**Example:**
```xml
<!-- views/ai_debug_index.xml -->
<odoo>
  <template id="ai_debug.index" name="AI Debug">
    <t t-call="web.layout">
      <t t-set="head">
        <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
        <script type="text/javascript">
          odoo.__session_info__ = <t t-out="json.dumps(session_info)"/>;
        </script>
        <t t-call-assets="ai_debug.assets" t-js="false"/>
        <t t-call-assets="ai_debug.assets" t-css="false"/>
      </t>
    </t>
  </template>
</odoo>
```

The template file must be listed in the manifest `data:` list.

### Pattern 4: OWL Entry Point

**What:** The `main.js` entry point calls `mountComponent` from `@web/env`. This auto-creates the service env, starts all registered services (including `bus_service`), and mounts the root component.

**Example:**
```javascript
// static/src/app/main.js
import { mountComponent } from "@web/env";
import { App } from "./app";
import { whenReady } from "@odoo/owl";

whenReady(async () => {
    await mountComponent(App, document.body, { name: "AI Debug" });
});
```

`mountComponent` internally calls `makeEnv()` then `startServices(env)`, which triggers the service registry to start all registered services including `bus_service`. After `startServices` resolves, bus_service is available and you can call `addChannel`.

### Pattern 5: Debug Menu Button Registration

**What:** A JS file added to `web.assets_backend` registers a new item in the debug menu via the `debug` registry.

**Example:**
```javascript
// static/src/debug_menu_button.js
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

function openAiDebug() {
    return {
        type: "item",
        description: _t("Open AI Debugger"),
        callback: () => {
            browser.open("/ai-debug", "_blank");
        },
        sequence: 700,
        section: "tools",
    };
}

registry.category("debug").category("default").add("openAiDebug", openAiDebug);
```

### Pattern 6: Updated ir.websocket Channel Gating

**What:** The `_build_bus_channel_list` override must be updated from v1.0 (system-user-only) to allow all internal users to subscribe to the `ai_debug` channel.

**Example:**
```python
# models/ir_websocket.py
from odoo import models

class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if not self.env.user._is_internal():
            channels = [
                ch for ch in channels
                if not (isinstance(ch, str) and ch == 'ai_debug')
            ]
        return super()._build_bus_channel_list(channels)
```

### Pattern 7: App Root Component with bus_service Setup

**What:** The root OWL component subscribes to the `ai_debug` bus channel in `onMounted` and manages connection status via `BUS:WORKER_STATE_UPDATED` events.

**Example:**
```javascript
// static/src/app/app.js
import { Component, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class App extends Component {
    static template = "ai_debug.App";
    static props = {};

    setup() {
        this.busService = useService("bus_service");

        onMounted(async () => {
            await this.busService.addChannel("ai_debug");
            this.busService.addEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
        });

        onWillUnmount(() => {
            this.busService.deleteChannel("ai_debug");
            this.busService.removeEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
        });
    }
}
```

### Anti-Patterns to Avoid

- **Using `ir.actions.client` for truly standalone pages:** The `path` field on `ir.actions.client` makes `/odoo/ai-debug` work inside the Odoo router, but the Odoo navbar/chrome is still fully rendered and you must hide it with CSS. This is the v1.0 approach. V1.1 requires a genuine separate HTTP controller route.
- **Using `get_frontend_session_info()` in the controller:** This returns a reduced session payload suitable for public/website pages. The full `session_info()` is needed so the service registry (particularly `session`, `user`, and company services) initializes correctly.
- **Mixing old `ai_debug:traces` channel name with new `ai_debug`:** The v1.0 code uses `ai_debug:traces` and `ai_debug:trace:{uuid}` channels. Phase 4 introduces a single `ai_debug` channel per the CONTEXT.md decisions. The `ir_websocket.py` override must be updated to gate the new channel name.
- **Registering assets in `web.assets_backend` for the standalone page:** Components and styles meant only for the standalone page should go in the custom `ai_debug.assets` bundle, not `web.assets_backend`. The debug menu button is the only thing that goes in `web.assets_backend`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Service bootstrapping | Custom service init sequence | `mountComponent` from `@web/env` | It handles dependency ordering, async init, and the SERVICES-LOADED event automatically |
| WebSocket connection management | Custom WebSocket wrapper | `bus_service.addChannel()` | bus_service handles SharedWorker, reconnection, multi-tab coordination, and message routing |
| Login redirect | Custom auth check | `auth='user'` on `@http.route` + `is_user_internal()` check | Odoo's routing layer handles session validation and login redirect; `is_user_internal` covers portal user exclusion |
| HTML page skeleton | Custom HTML | `t-call="web.layout"` | web.layout injects csrf_token, favicon, and the `odoo` global correctly |

---

## Common Pitfalls

### Pitfall 1: Asset Bundle Not Found at Render Time

**What goes wrong:** The QWeb template calls `t-call-assets="ai_debug.assets"` but the bundle doesn't exist yet at server startup — renders a blank page or 500 error.

**Why it happens:** The bundle is declared in the manifest `assets` dict, but the manifest `data` list must also include the QWeb template file.

**How to avoid:** The manifest `data:` list must include the template XML file. The bundle itself (`ai_debug.assets`) is declared only in `assets:` — never in `data:`.

**Warning signs:** `KeyError: 'ai_debug.assets'` in server logs; blank page with no JS loaded.

### Pitfall 2: session_info Missing Required Fields

**What goes wrong:** `bus_service` fails to start because `session.db` or `session.user_id` is undefined.

**Why it happens:** `get_frontend_session_info()` does not include `db` or `user_id` fields. The bus_service `ensureWorkerStarted()` reads `session.db` and `session.user_id` directly.

**How to avoid:** Use `request.env['ir.http'].session_info()` (the full backend version), not `get_frontend_session_info()`.

**Warning signs:** `Cannot read properties of undefined (reading 'db')` in browser console; bus worker never starts.

### Pitfall 3: `auth='none'` on the Route

**What goes wrong:** Unauthenticated requests reach the controller and crash on `request.env['ir.http'].session_info()` because there's no user.

**Why it happens:** `auth='none'` skips Odoo's session setup. The web_client route uses `auth='none'` but then calls `ensure_db()` and checks `request.session.uid` manually. For our simpler case, `auth='user'` is cleaner.

**How to avoid:** Use `auth='user'` — Odoo automatically redirects to `/web/login` if no session exists. Add the `is_user_internal()` check for portal users.

**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'session_info'`; 500 error for unauthenticated requests.

### Pitfall 4: Old ir_websocket.py Gating Blocks Internal Users

**What goes wrong:** Browser console shows bus_service connected but no messages arrive; `ai_debug` channel subscription is silently dropped.

**Why it happens:** The v1.0 `ir_websocket.py` gates `ai_debug:*` channels to `base.group_system` only. Internal users (who have `base.group_user` but not `base.group_system`) get their channel subscription stripped by `_build_bus_channel_list`.

**How to avoid:** Update `ir_websocket.py` to use `self.env.user._is_internal()` instead of `self.env.user.has_group('base.group_system')`, and match the new channel name `ai_debug` (not `ai_debug:*` prefix).

**Warning signs:** Bus worker shows CONNECTED; `addChannel("ai_debug")` is called; but no messages ever trigger subscribers.

### Pitfall 5: Reusing ir.actions.client Approach

**What goes wrong:** Navigating to `/ai-debug` loads the full Odoo web client with the navbar visible; CSS hides it but it's still in the DOM.

**Why it happens:** `ir.actions.client` with `path = "ai-debug"` routes through `/odoo/ai-debug` inside the Odoo SPA. The Odoo router handles the action, not an HTTP controller.

**How to avoid:** Create a standalone HTTP controller. The route must be `/ai-debug` (not `/odoo/ai-debug`). Delete `debug_panel_action.xml`.

### Pitfall 6: Including All v1.0 Assets in new Backend Bundle

**What goes wrong:** The old `debug_panel.js` (which makes ORM calls to `ai.debug.trace` etc.) is still loaded in `web.assets_backend`, causing `Error: model ai.debug.trace not found` on every backend page.

**Why it happens:** The v1.0 manifest had `'ai_debug/static/src/**/*.js'` as a glob in `web.assets_backend`. The new manifest must not include any v1.0 JS files in backend assets.

**How to avoid:** When rewriting the manifest, explicitly list only the new `debug_menu_button.js` in `web.assets_backend`. The rest goes in `ai_debug.assets`.

---

## Code Examples

### Complete HTTP Controller

```python
# ai_debug/controllers/main.py
import json
from odoo import http
from odoo.http import request
from odoo.addons.web.controllers.utils import ensure_db, is_user_internal

class AiDebugController(http.Controller):

    @http.route('/ai-debug', type='http', auth='user', readonly=True)
    def ai_debug(self, **kw):
        ensure_db()
        if not is_user_internal(request.session.uid):
            return request.redirect('/web/login', 303)
        session_info = request.env['ir.http'].session_info()
        return request.render('ai_debug.index', {
            'session_info': session_info,
        })
```

### Complete Manifest (v1.1 skeleton)

```python
# ai_debug/__manifest__.py
{
    'name': 'AI Debug',
    'version': '1.1',
    'category': 'Technical',
    'summary': 'Standalone live tracer for the AI agentic loop',
    'depends': ['ai_app', 'bus'],
    'data': [
        'views/ai_debug_index.xml',
    ],
    'assets': {
        'ai_debug.assets': [
            ('include', 'web.assets_backend'),
            'ai_debug/static/src/app/**/*.scss',
            'ai_debug/static/src/app/**/*.xml',
            'ai_debug/static/src/app/**/*.js',
        ],
        'web.assets_backend': [
            'ai_debug/static/src/debug_menu_button.js',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
}
```

### Complete QWeb Index Template

```xml
<!-- ai_debug/views/ai_debug_index.xml -->
<?xml version="1.0" encoding="utf-8"?>
<odoo>
  <template id="index" name="AI Debug">
    <t t-call="web.layout">
      <t t-set="head">
        <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no"/>
        <script type="text/javascript">
          odoo.__session_info__ = <t t-out="json.dumps(session_info)"/>;
        </script>
        <t t-call-assets="ai_debug.assets" t-js="false"/>
        <t t-call-assets="ai_debug.assets" t-css="false"/>
      </t>
    </t>
  </template>
</odoo>
```

### OWL App Entry Point

```javascript
// ai_debug/static/src/app/main.js
/** @odoo-module **/
import { mountComponent } from "@web/env";
import { AiDebugApp } from "./app";
import { whenReady } from "@odoo/owl";

whenReady(async () => {
    await mountComponent(AiDebugApp, document.body, { name: "AI Debug" });
});
```

### Stub Root Component

```javascript
// ai_debug/static/src/app/app.js
/** @odoo-module **/
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static props = {};
    static components = {};

    setup() {
        this.busService = useService("bus_service");
        this.state = useState({ connectionStatus: "connecting" });

        this._onWorkerState = ({ detail }) => {
            this.state.connectionStatus =
                detail === "CONNECTED" ? "connected" :
                detail === "CONNECTING" ? "reconnecting" : "disconnected";
        };

        onMounted(async () => {
            this.busService.addEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.removeEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
            this.busService.deleteChannel("ai_debug");
        });
    }
}
```

### Debug Menu Button

```javascript
// ai_debug/static/src/debug_menu_button.js
/** @odoo-module **/
import { _t } from "@web/core/l10n/translation";
import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";

function openAiDebugger() {
    return {
        type: "item",
        description: _t("Open AI Debugger"),
        callback: () => {
            browser.open("/ai-debug", "_blank");
        },
        sequence: 700,
        section: "tools",
    };
}

registry.category("debug").category("default").add("openAiDebugger", openAiDebugger);
```

---

## v1.0 Cleanup Inventory

### Files to Delete (complete)

| File | v1.0 Role | Delete? | Reason |
|------|-----------|---------|--------|
| `models/ai_debug_trace.py` | ORM model | YES | No DB persistence in v1.1 |
| `models/ai_debug_iteration.py` | ORM model | YES | No DB persistence in v1.1 |
| `models/ai_debug_tool_call.py` | ORM model | YES | No DB persistence in v1.1 |
| `models/ai_session.py` | Instrumentation hooks | YES | Tightly coupled to ORM models; incompatible with v1.1 bus-only design |
| `models/ir_websocket.py` | Channel gating | UPDATE | Keep but rewrite: change from system-user-only to internal-user, update channel name to `ai_debug` |
| `views/ai_debug_trace_views.xml` | Backend list/form views | YES | Replaced by standalone app |
| `views/ai_debug_iteration_views.xml` | Backend list/form views | YES | Replaced by standalone app |
| `views/ai_debug_tool_call_views.xml` | Backend list/form views | YES | Replaced by standalone app |
| `views/menus.xml` | Backend menus + actions | YES | No backend menus in v1.1 |
| `views/debug_panel_action.xml` | `ir.actions.client` for old `/odoo/ai-debug` | YES | New standalone controller replaces this |
| `security/ir.model.access.csv` | ORM model access | YES | No ORM models in v1.1 |
| `static/src/debug_panel/` (entire dir) | v1.0 OWL panel (ORM-reading) | YES | Fresh start; new app/ dir for v1.1 |

### Files to Keep/Create

| File | Action | Reason |
|------|--------|--------|
| `__init__.py` | KEEP | Module root init |
| `__manifest__.py` | REWRITE | Fresh manifest for v1.1 |
| `models/__init__.py` | UPDATE | Remove imports of deleted models |
| `models/ir_websocket.py` | UPDATE | Keep gating logic, update group and channel name |
| `controllers/__init__.py` | CREATE | New controllers package |
| `controllers/main.py` | CREATE | HTTP controller for /ai-debug |
| `views/ai_debug_index.xml` | CREATE | QWeb HTML template |
| `static/src/app/main.js` | CREATE | Entry point |
| `static/src/app/app.js` | CREATE | Root OWL component |
| `static/src/app/app.xml` | CREATE | Root template |
| `static/src/app/app.scss` | CREATE | Base styles |
| `static/src/debug_menu_button.js` | CREATE | Debug menu item |

### Instrumentation Hooks Assessment (Claude's Discretion)

The v1.0 `models/ai_session.py` contains `_run_agentic_loop`, `_handle_tool_calls`, and `_generate_next_response` overrides. These are the Phase 5 instrumentation hooks. However, every write call in these methods targets ORM models (`env['ai.debug.trace'].create(...)`, `env['ai.debug.iteration'].create(...)`, etc.) that will not exist in v1.1.

**Decision: Delete ai_session.py entirely.** The Phase 5 implementation will rewrite instrumentation from scratch using `bus.bus._sendone()` directly (no ORM writes). The helper utilities (`_debug_strip_binaries`, `_debug_safe_context`) might be reimplemented in Phase 5, but they are simple enough to recreate and keeping them in a broken state creates confusion.

---

## State of the Art

| Old Approach (v1.0) | New Approach (v1.1) | When Changed | Impact |
|---------------------|---------------------|--------------|--------|
| `ir.actions.client` + CSS navbar hiding | True standalone HTTP controller | Phase 4 (this phase) | Genuine navbar-free page; no DOM clutter |
| `ai_debug:traces` + `ai_debug:trace:{uuid}` channels | Single `ai_debug` channel | Phase 4 (this phase) | Simpler subscription; message type field distinguishes events |
| ORM models for trace/iteration/tool_call | No ORM; all data in frontend memory | Phase 4 (this phase) | Eliminates DB writes entirely; session-scoped |
| `ai.session` ORM override for instrumentation | Pure `bus.bus._sendone()` calls | Phase 5 | Faster; no separate cursor; bus payload = only source of truth |
| System-user-only channel gating | Internal-user channel gating | Phase 4 (this phase) | Matches INFRA-02: any `base.group_user` can access |

---

## Open Questions

1. **`readonly=True` on the HTTP route**
   - What we know: The web_client route uses a `_web_client_readonly` callable that returns `False`. We can use `readonly=True` on our route since the controller only reads session info.
   - What's unclear: Whether `readonly=True` causes issues with `ensure_db()` or session touching.
   - Recommendation: Use `readonly=True` (matches the intent: GET request, read-only). If session touching is needed, drop to `readonly=False`.

2. **Asset bundle inclusion order (SCSS variables)**
   - What we know: `web.assets_backend` includes all SCSS variable definitions. Including it first in `ai_debug.assets` ensures the app SCSS has access to Bootstrap variables.
   - What's unclear: Whether including `web.assets_backend` causes any service double-registration issues.
   - Recommendation: Test with a simple `console.log` in `main.js` after `mountComponent` resolves to confirm service registry starts cleanly.

3. **`json.dumps` import in the QWeb template**
   - What we know: The `webclient_bootstrap` template and `pos_self_order.index` both use `json.dumps(session_info)` directly in QWeb. This works because `json` is available in the QWeb rendering context via `ir.qweb`.
   - What's unclear: Whether `json` needs to be explicitly passed in the `qcontext` dict from the controller.
   - Recommendation: Pass `session_info` in qcontext and let Odoo's QWeb context inject `json` automatically. If it fails, add `import json` and pass `'json': json` in qcontext.

---

## Sources

### Primary (HIGH confidence)

- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/env.js` — `mountComponent`, `makeEnv`, `startServices` implementation
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/controllers/home.py` — `web_client` controller pattern, `is_user_internal`, `ensure_db`
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/models/ir_http.py` — `session_info()` vs `get_frontend_session_info()` comparison
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/services/bus_service.js` — `addChannel`, `BUS:WORKER_STATE_UPDATED`, `workerState`
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/controllers/self_entry.py` — standalone HTTP controller pattern
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/static/src/app/root.js` — `mountComponent` entry point
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/pos_self_order/__manifest__.py` — custom asset bundle pattern
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/views/webclient_templates.xml` — `web.layout` template and `webclient_bootstrap` structure
- Odoo source: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/debug/debug_menu_items.js` — debug menu item registry pattern
- Odoo source: `/Users/joseph/clones/odoo/custom/ai_debug/` — full v1.0 codebase audit (all files)

### Secondary (MEDIUM confidence)

- Inferred from `bus_service.js` line 125-135: `ensureWorkerStarted()` reads `session.db` and `session.user_id` — confirming that `get_frontend_session_info()` (which lacks `db`) is insufficient.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all verified directly from Odoo master source
- Architecture: HIGH — patterns extracted directly from working Odoo modules (pos_self_order, web, bus)
- Pitfalls: HIGH — identified by direct reading of v1.0 code and comparing to v1.1 requirements; Pitfall 4 (gating) confirmed by reading existing `ir_websocket.py`
- Cleanup inventory: HIGH — all files identified by direct `find` of the current codebase

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (Odoo master changes frequently but core patterns are stable)
