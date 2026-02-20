# Phase 3: Live Panel and Polish - Research

**Researched:** 2026-02-20
**Domain:** Odoo bus.bus real-time notifications, IrWebsocket override, OWL client action components
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Panel layout**
- Vertical timeline with a rail connecting iterations top-to-bottom
- Tool calls nested under their parent iteration in the timeline
- Medium density on collapsed iteration nodes: iteration number, duration, tool count, message count, and status indicator
- Clicking an iteration or tool call expands to show detail (JSON tree for messages, response, etc.)
- Active/streaming iteration shown at the bottom with animation

**Real-time behavior**
- Always auto-scroll to follow the latest event as iterations and tool calls arrive
- Live only — opening the panel mid-loop shows only events arriving after open, no historical backfill
- Always-visible connection status indicator (connected/disconnected/reconnecting badge/dot)
- Loop completion signaled by trace status change in header only — no banner or overlay

**State diff presentation**
- Side-by-side layout: before state on left, after state on right, changes highlighted
- Displayed inside the iteration expand area (a tab/section alongside messages and response)
- Unchanged keys collapsed by default (e.g., "... 5 unchanged keys") with click to expand
- Deep diff vs top-level diff: Claude's discretion based on what state data typically looks like

**JSON tree interaction**
- Default expansion: 1-2 levels deep (top-level keys expanded, nested objects collapsed)
- Syntax highlighting by type: strings green, numbers blue, booleans orange, nulls gray
- No search/filter — just expand/collapse navigation
- Copy-to-clipboard icon on hover for any node — copies that subtree as JSON

### Claude's Discretion
- Header/toolbar design (trace selector vs minimal header)
- Deep diff algorithm choice for state comparison
- Exact color palette and spacing for the timeline
- Loading/skeleton states
- Error state handling and display

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LIVE-01 | OWL debug panel accessible as a separate browser tab/page, receiving real-time updates via `bus.bus` as the agentic loop runs | IrWebsocket._build_bus_channel_list override pattern (verified in spreadsheet_edition, iot); bus_service addChannel/subscribe/deleteChannel lifecycle; ir.actions.client with tag registered in JS registry |
| LIVE-02 | State diff viewer showing what changed in `tools_context['state']` between iterations | state_before/state_after are already captured as fields.Json on ai.debug.iteration; hand-rolled recursive diff algorithm (no Odoo-bundled JSON diff library found) |
| LIVE-03 | Collapsible JSON tree renderer for messages, raw responses, and state data | Hand-rolled OWL component (no Odoo-bundled JSON tree widget found); useState for collapse state, syntax highlighting via CSS classes, copy-to-clipboard via navigator.clipboard |
</phase_requirements>

---

## Summary

Phase 3 requires two interconnected deliverables: a backend bus notification pipeline that emits events per iteration/tool-call through `bus.bus._sendone`, and a frontend OWL `ir.actions.client` component that subscribes to those events and renders them in real time.

The backend work is straightforward because the existing `ai_debug` instrumentation already uses a separate cursor (`self.env.registry.cursor()`) for every write. Adding `env['bus.bus']._sendone(channel, type, payload)` inside those same `with self.env.registry.cursor() as cr:` blocks is the correct and atomic approach — `_sendone` hooks onto `cr.precommit` and `cr.postcommit`, so the bus write and pg_notify fire exactly when the iteration/tool-call record commits. No additional cursor management is needed.

The frontend requires an OWL Component registered in `registry.category("actions")`, which subscribes to a UUID-based channel via `bus_service.addChannel` / `bus_service.subscribe` on mount, and tears it down with `bus_service.unsubscribe` / `bus_service.deleteChannel` on unmount. The IrWebsocket model must be extended to allow the client to subscribe to the per-trace UUID channel (access-checked against `base.group_system`). JSON tree rendering and state diff are hand-rolled OWL components — no suitable library exists in the Odoo bundle.

**Primary recommendation:** Add `_sendone` calls inside the existing separate-cursor write helpers in `ai_session.py`; register a UUID `bus_channel` field on `ai.debug.trace`; extend `IrWebsocket._build_bus_channel_list` to allow `ai_debug:trace:{uuid}` channels for system users; build the OWL panel as a single `ir.actions.client` component with child components for the JSON tree and state diff.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `bus.bus` (`BusBus` model) | Odoo master | Persistent notification queue; triggers pg_notify on commit | The standard Odoo WebSocket delivery mechanism |
| `ir.websocket` (`IrWebsocket` model) | Odoo master | Per-connection channel whitelist; override `_build_bus_channel_list` | The only correct extension point for custom channels |
| `bus_service` (JS) | Odoo master | Client-side WebSocket service; `addChannel`, `subscribe`, `deleteChannel`, `unsubscribe` | Shared across tabs via SharedWorker; the standard subscription API |
| OWL `Component` + `registry.category("actions")` | Odoo master | `ir.actions.client` component registration | Standard pattern — DiscussClientAction, hr_attendance kiosk, etc. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `WORKER_STATE` (from `@bus/workers/websocket_worker`) | Odoo master | Enum: `CONNECTED`, `DISCONNECTED`, `IDLE`, `CONNECTING` | Read `bus_service.workerState` or listen to `BUS:WORKER_STATE_UPDATED` event for connection badge |
| `BusMonitoringService` | Odoo master | `isConnectionLost` reactive flag | Can be used directly or as a reference for the connection badge implementation |
| `navigator.clipboard.writeText` | Browser standard | Copy-to-clipboard for JSON nodes | Always available in modern browsers; no Odoo wrapper needed |
| `JSON.stringify(obj, null, 2)` | JS standard | Fallback JSON rendering | Used in computed fields already; useful for copy output |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| UUID string channel | Model record channel (bus_listener_mixin) | String channel requires `_build_bus_channel_list` override but avoids adding a `bus.listener.mixin` inheritance to `ai.debug.trace`. UUID is "not guessable by an attacker" per `_sendone` docstring — correct pattern for custom string channels. |
| Hand-rolled JSON tree | `ace` widget (already used in phase 2) | `ace` is a text editor widget, not a tree. Phase 2 already uses `ace` for read-only pretty-print, but expanding/collapsing individual nodes requires a tree component. |
| `diff_match_patch` (bundled in Odoo) | Custom diff | `diff_match_patch` is a *text* diff library for strings. JSON state diff requires structural (deep object) comparison. Not applicable. |

---

## Architecture Patterns

### Recommended Project Structure

```
ai_debug/
├── models/
│   ├── ai_debug_trace.py         # add bus_channel UUID field
│   ├── ai_session.py             # add _sendone calls in write helpers
│   └── ir_websocket.py           # NEW: _build_bus_channel_list override
├── static/
│   └── src/
│       ├── debug_panel/
│       │   ├── debug_panel.js    # main ir.actions.client OWL component
│       │   ├── debug_panel.xml   # OWL template
│       │   ├── json_tree/
│       │   │   ├── json_tree.js  # recursive JSON tree component
│       │   │   └── json_tree.xml
│       │   └── state_diff/
│       │       ├── state_diff.js # side-by-side diff component
│       │       └── state_diff.xml
└── views/
    └── debug_panel_action.xml    # ir.actions.client record + menu button
```

### Pattern 1: Backend Bus Notification via Separate Cursor

**What:** Call `env['bus.bus']._sendone(channel, type, payload)` inside the existing `with self.env.registry.cursor() as cr:` blocks in `ai_session.py` write helpers.

**When to use:** Every time an iteration or tool call record is created — the bus notification fires atomically on cursor commit.

**Why it works:** `_sendone` registers its writes on `cr.precommit` and the pg_notify on `cr.postcommit`. When the `with` block for the separate cursor exits, precommit runs (inserts `bus_bus` row), the cursor commits, then postcommit runs (executes `pg_notify('imbus', ...)`). The notification is visible to WebSocket clients immediately.

**Example (inside `_debug_write_iteration`):**

```python
# Source: verified from bus/models/bus.py _sendone + _ensure_hooks
def _debug_write_iteration(self, trace_id, vals):
    try:
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self._debug_safe_context())
            vals = dict(vals, trace_id=trace_id)
            iteration = env['ai.debug.iteration'].create(vals)
            iteration_id = iteration.id
            # Bus notification fires when this cursor commits
            channel = f'ai_debug:trace:{self._get_trace_bus_channel(trace_id, env)}'
            env['bus.bus']._sendone(channel, 'ai_debug/iteration', {
                'iteration_id': iteration_id,
                'index': vals.get('index', 0),
                'duration_ms': vals.get('duration_ms', 0),
            })
        return iteration_id
    except Exception:
        _logger.warning('ai_debug: failed to write iteration', exc_info=True)
        return False
```

**The channel name:** `ai_debug:trace:{uuid}` where `uuid` is stored on `ai.debug.trace.bus_channel` (a `fields.Char` with `default=lambda self: str(uuid.uuid4())`).

To retrieve the UUID inside the write helpers, the trace must already be created. The `_debug_write_trace` helper creates the trace first and returns `trace_id`. The UUID must be fetched in a subsequent read (also via separate cursor) OR stored on `debug_ctx` when the trace is created. The simplest approach: read the `bus_channel` field inside `_debug_write_trace` and return it alongside `trace_id`, storing both in `debug_ctx`.

### Pattern 2: IrWebsocket Override for Access-Checked Channel

**What:** Override `_build_bus_channel_list` in `ir.websocket` to allow clients to subscribe to `ai_debug:trace:{uuid}` channels, but only if the user has `base.group_system`.

**When to use:** Every WebSocket subscribe event. The client sends the channel name; the server validates access and either adds it to the subscription list or drops it.

**Example:**

```python
# Source: verified from enterprise/spreadsheet_edition/models/ir_websocket.py pattern
from odoo import models

class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if self.env.user.has_group('base.group_system'):
            # Pass through ai_debug trace channels for system users only
            channels = [
                c for c in channels
                if not isinstance(c, str) or not c.startswith('ai_debug:trace:')
            ] + [
                c for c in channels
                if isinstance(c, str) and c.startswith('ai_debug:trace:')
            ]
        else:
            # Strip ai_debug channels for non-system users
            channels = [
                c for c in channels
                if not (isinstance(c, str) and c.startswith('ai_debug:trace:'))
            ]
        return super()._build_bus_channel_list(channels)
```

**Simpler alternative:** Since `_sendone` uses a UUID that is not guessable, the security risk of a non-system user subscribing is that they waste a subscription slot — no data leakage because `_sendone` is only called when the debug module writes (which itself requires system access). A minimal override just needs to not crash — the whitelist approach is cleaner.

**Recommended minimal pattern (from iot module):**

```python
class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if self.env.user.has_group('base.group_system'):
            # ai_debug trace channels are allowed for system users as-is
            pass
        else:
            channels = [
                c for c in channels
                if not (isinstance(c, str) and c.startswith('ai_debug:trace:'))
            ]
        return super()._build_bus_channel_list(channels)
```

### Pattern 3: OWL Client Action Component

**What:** A `Component` registered in `registry.category("actions")` with a matching `tag` on the `ir.actions.client` record. Subscribes to the bus on `onMounted`, unsubscribes on `onWillUnmount`.

**Key imports:**
```javascript
// Source: verified from mail/static/src/core/public_web/discuss_app/client_action.js
import { Component, onMounted, onWillUnmount, useState, useRef, onPatched } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
```

**Component structure:**

```javascript
// Source: verified from hr_attendance presence_status.js (bus pattern)
// and mail discuss_app client_action.js (actions.client pattern)
export class DebugPanel extends Component {
    static template = "ai_debug.DebugPanel";
    static components = { JsonTree, StateDiff };
    static props = ["action", "*"];

    setup() {
        this.busService = useService("bus_service");
        this.state = useState({
            iterations: [],
            connectionStatus: "connecting",
            traceStatus: "running",
        });
        this.scrollRef = useRef("scroll");

        const channel = this.props.action.context?.bus_channel;

        onMounted(() => {
            if (channel) {
                this.busService.addChannel(channel);
                this.busService.subscribe("ai_debug/iteration", this._onIteration.bind(this));
                this.busService.subscribe("ai_debug/tool_call", this._onToolCall.bind(this));
                this.busService.subscribe("ai_debug/trace_update", this._onTraceUpdate.bind(this));
            }
            this.busService.addEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onConnectionStateChange.bind(this)
            );
        });

        onPatched(() => {
            // Auto-scroll to bottom after each render (new iteration/tool-call arrived)
            const el = this.scrollRef.el;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        });

        onWillUnmount(() => {
            if (channel) {
                this.busService.unsubscribe("ai_debug/iteration", this._onIteration);
                this.busService.unsubscribe("ai_debug/tool_call", this._onToolCall);
                this.busService.unsubscribe("ai_debug/trace_update", this._onTraceUpdate);
                this.busService.deleteChannel(channel);
            }
            this.busService.removeEventListener(
                "BUS:WORKER_STATE_UPDATED",
                this._onConnectionStateChange
            );
        });
    }
    // ...
}
registry.category("actions").add("ai_debug.debug_panel", DebugPanel);
```

**How `bus_channel` reaches the component:** The `ir.actions.client` record has a `context` field. When the user clicks "Open Live Panel" from the trace form, a Python `@api.model` method constructs the action dict on the fly, injecting `bus_channel` from the trace record. This is an `ir.actions.act_window` button calling a server action or a direct JS `doAction` call.

**Simpler approach:** The panel can also be a static `ir.actions.client` with `path` set (e.g., `ai-debug/trace/{id}`), and the `DebugPanel` component reads `trace_id` from the URL (via `router.current`) and fetches the `bus_channel` UUID via a `rpc` call.

### Pattern 4: JSON Tree Component (Hand-Rolled)

**What:** A recursive OWL component that renders a JSON value (object, array, scalar) as an expandable tree.

**State model:**

```javascript
// No external library — hand-rolled with useState for collapse tracking
// Source: standard OWL pattern, no Odoo reference
export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static props = {
        value: true,         // any JSON value
        depth: { type: Number, optional: true },
        maxDepth: { type: Number, optional: true },  // default 2
    };

    setup() {
        const maxDepth = this.props.maxDepth ?? 2;
        const depth = this.props.depth ?? 0;
        this.state = useState({
            collapsed: depth >= maxDepth,  // collapsed beyond maxDepth
        });
    }

    get isObject() { return this.props.value !== null && typeof this.props.value === 'object'; }
    get isArray() { return Array.isArray(this.props.value); }
    get entries() {
        const v = this.props.value;
        if (Array.isArray(v)) return v.map((val, i) => [String(i), val]);
        return v ? Object.entries(v) : [];
    }
    get valueType() {
        const v = this.props.value;
        if (v === null) return 'null';
        if (typeof v === 'boolean') return 'boolean';
        if (typeof v === 'number') return 'number';
        return 'string';
    }
    copyToClipboard() {
        navigator.clipboard.writeText(JSON.stringify(this.props.value, null, 2));
    }
}
```

**Template sketch:**

```xml
<templates>
  <t t-name="ai_debug.JsonTree">
    <span t-if="!isObject" t-att-class="'ai-debug-json-' + valueType"
          t-esc="value === null ? 'null' : String(props.value)"/>
    <span t-else="">
      <span class="ai-debug-json-toggle" t-on-click="() => state.collapsed = !state.collapsed">
        <t t-if="state.collapsed">
          <t t-esc="isArray ? '[...]' : '{...}'" />
        </t>
      </span>
      <t t-if="!state.collapsed">
        <div class="ai-debug-json-children" t-foreach="entries" t-as="entry" t-key="entry[0]">
          <span class="ai-debug-json-key" t-esc="entry[0]"/>:
          <JsonTree value="entry[1]" depth="(props.depth ?? 0) + 1" maxDepth="props.maxDepth ?? 2"/>
        </div>
      </t>
    </span>
  </t>
</templates>
```

### Pattern 5: State Diff (Hand-Rolled, Deep Diff)

**What:** A recursive diff that computes added, removed, changed, and unchanged keys between two plain objects.

**Decision on deep vs. top-level diff:** `tools_context['state']` in Odoo AI agents is typically a flat-to-2-level-deep dict (e.g., `{'field': value, 'nested': {'key': value}}`). Deep diff (1-2 levels) covers the real changes. Recommendation: implement a recursive diff up to a configurable depth; stop recursing into arrays (treat them as atomic values — show old vs. new side-by-side).

**Diff algorithm (no library needed):**

```javascript
// Source: hand-rolled, no Odoo library available
// Standard recursive JSON object diff
function computeDiff(before, after) {
    // Returns an array of DiffEntry: { key, status: 'added'|'removed'|'changed'|'unchanged', oldVal, newVal, children }
    const result = [];
    const allKeys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
    for (const key of allKeys) {
        const inBefore = key in (before || {});
        const inAfter = key in (after || {});
        if (!inBefore) {
            result.push({ key, status: 'added', oldVal: undefined, newVal: after[key] });
        } else if (!inAfter) {
            result.push({ key, status: 'removed', oldVal: before[key], newVal: undefined });
        } else {
            const a = before[key], b = after[key];
            if (JSON.stringify(a) === JSON.stringify(b)) {
                result.push({ key, status: 'unchanged', oldVal: a, newVal: b });
            } else if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
                result.push({ key, status: 'changed', oldVal: a, newVal: b, children: computeDiff(a, b) });
            } else {
                result.push({ key, status: 'changed', oldVal: a, newVal: b });
            }
        }
    }
    return result;
}
```

**StateDiff component:** Receives `stateBefore` and `stateAfter` as props. Calls `computeDiff` in a getter. Renders: added keys in green, removed in red, changed highlighted, unchanged collapsed with "N unchanged keys" summary. Clicking the summary expands unchanged keys.

### Anti-Patterns to Avoid

- **Calling `_sendone` on the main cursor (`self.env.cr`):** The main transaction cursor for `ai.session._run_agentic_loop` is NOT committed until the agentic loop ends. Notifications sent on `self.env.cr` would only trigger pg_notify after the full loop commits, making them useless for live streaming.
- **Fetching historical records on panel open:** The locked decision is "live only." Do not add a `rpc` call on `onMounted` to backfill existing iterations. The panel only shows events arriving after the WebSocket subscription.
- **Using `bus_service.start()` without `addChannel` first:** `start()` initiates the WebSocket but without a channel the subscription is empty. Always call `addChannel` before or alongside `start()`. In practice, `addChannel` calls `start()` internally (verified in `bus_service.js`: `addChannel` calls `workerService.send("BUS:START")`).
- **Not unsubscribing in `onWillUnmount`:** Bus subscriptions are global within the service. If the component is destroyed without cleanup, callbacks fire on a destroyed component, causing errors.
- **JSON tree with deep recursion on huge payloads:** LLM messages can be large. Default collapse at depth >= 2 prevents DOM explosion. Always default to collapsed for deeply nested objects.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| WebSocket connection management | Custom WebSocket class | `bus_service` + `addChannel` | SharedWorker, reconnect logic, multi-tab dedup already built |
| Connection status tracking | Custom ping/pong | `bus_service.workerState` reactive + `BUS:WORKER_STATE_UPDATED` event | Already reactive, already handles online/offline events |
| Per-cursor commit hooks | Custom commit tracking | `self.env.cr.precommit.add` / `self.env.cr.postcommit.add` | Built-in Odoo cursor lifecycle, used by `_sendone` internally |

**Key insight:** The entire WebSocket infrastructure (SharedWorker, reconnect, multi-tab) is already provided by `bus_service`. The only integration work is calling `addChannel(uuid_string)` and `subscribe(type, callback)`. Do not build any custom WebSocket handling.

---

## Common Pitfalls

### Pitfall 1: `_sendone` on Wrong Cursor

**What goes wrong:** Notification never fires during the loop, only fires (if at all) when the main HTTP request transaction commits — long after the iteration completed.

**Why it happens:** `_sendone` uses `self.env.cr.precommit` and `self.env.cr.postcommit`. If called on the main request cursor, hooks run when the main transaction commits (end of the HTTP handler). In a generator loop, the main transaction may not commit until the generator is exhausted.

**How to avoid:** Always call `_sendone` inside a `with self.env.registry.cursor() as cr:` block, using the `env` created from that `cr`. The separate cursor commits immediately when the `with` block exits.

**Warning signs:** Panel shows no events until the loop is fully complete, then all events appear at once.

### Pitfall 2: UUID Not Available When Sending Notifications

**What goes wrong:** `_debug_write_iteration` needs to know the `bus_channel` UUID to address the notification, but `trace_id` alone is not enough — the UUID must be fetched from the `ai.debug.trace` record.

**Why it happens:** `debug_ctx` currently stores only `{'trace_id': ..., 'iteration_id': ...}`. The UUID is on the `ai.debug.trace` record.

**How to avoid:** When `_debug_write_trace` creates the trace and returns `trace_id`, also read back the `bus_channel` field and store it in `debug_ctx` as `debug_ctx['bus_channel'] = trace.bus_channel`. All subsequent `_debug_write_iteration` and `_debug_write_tool_call` calls can then read `debug_ctx['bus_channel']` without DB round-trips.

**Implementation note:** `ai.debug.trace` needs a new `bus_channel` field: `fields.Char(default=lambda self: str(uuid.uuid4()), readonly=True, copy=False, index=True)`.

**Warning signs:** `KeyError` on `debug_ctx['bus_channel']` or `_sendone` receiving `None` as channel.

### Pitfall 3: Channel Access Check in `_build_bus_channel_list`

**What goes wrong:** Non-system users can subscribe to `ai_debug:trace:` channels if the override is missing.

**Why it happens:** `_build_bus_channel_list` default implementation adds `broadcast` and user-specific channels. Custom string channels from the client are passed through unless explicitly filtered.

**How to avoid:** Override `_build_bus_channel_list` and remove `ai_debug:trace:` channels for non-system users. The UUID provides security-by-obscurity but the explicit group check is best practice (consistent with spreadsheet_edition pattern).

**Warning signs:** Security scanner flags open channel subscription.

### Pitfall 4: OWL Component Not Registered Before Action Opens

**What goes wrong:** Clicking "Open Live Panel" shows an error: "Component not found for tag ai_debug.debug_panel."

**Why it happens:** The JS file containing `registry.category("actions").add(...)` was not included in `web.assets_backend`.

**How to avoid:** Add `'ai_debug/static/src/**/*.js'` and `'ai_debug/static/src/**/*.xml'` to `web.assets_backend` in `__manifest__.py`.

**Warning signs:** Console error about missing action tag; blank panel view.

### Pitfall 5: Auto-Scroll Firing Too Aggressively

**What goes wrong:** User manually scrolls up to inspect an earlier iteration; the panel immediately snaps back to the bottom.

**Why it happens:** `onPatched` calls `scrollTop = scrollHeight` unconditionally.

**How to avoid:** Track a `userScrolledUp` flag. Set it to `true` when the user scrolls up (scroll event listener). Reset to `false` when they scroll back to the bottom. Only auto-scroll when `userScrolledUp === false`.

**Warning signs:** Scroll position jumps on every new event regardless of user position.

### Pitfall 6: Large Payload in Bus Notification

**What goes wrong:** Full `messages_sent` JSON in the notification payload triggers the `NOTIFY_PAYLOAD_MAX_LENGTH` split logic or overloads the WebSocket message.

**Why it happens:** `_sendone` payload goes through `json_dump`; `pg_notify` has an 8000-byte payload limit (configurable). LLM message arrays can be very large.

**How to avoid:** Send only summary data in the bus notification (iteration_id, index, duration_ms, tool_count, status). The client fetches full detail (messages, raw_response, state_before/after) via `rpc` when the user expands an iteration. This pattern also enables showing detail for iterations that were recorded before the panel opened.

---

## Code Examples

Verified patterns from official sources:

### Backend: `_sendone` in Separate Cursor

```python
# Source: bus/models/bus.py (_sendone, _ensure_hooks), ai_debug/models/ai_session.py
def _debug_write_iteration(self, trace_id, vals):
    try:
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, self._debug_safe_context())
            vals = dict(vals, trace_id=trace_id)
            iteration = env['ai.debug.iteration'].create(vals)
            iteration_id = iteration.id
            # Bus notification: _sendone registers on cr.precommit/postcommit
            # Fires atomically when 'with' block exits and cr commits
            bus_channel = self.env.context.get('_debug_ctx', {}).get('bus_channel')
            if bus_channel:
                env['bus.bus']._sendone(
                    f'ai_debug:trace:{bus_channel}',
                    'ai_debug/iteration',
                    {
                        'iteration_id': iteration_id,
                        'index': vals.get('index', 0),
                        'duration_ms': vals.get('duration_ms', 0),
                    }
                )
        return iteration_id
    except Exception:
        _logger.warning('ai_debug: failed to write iteration', exc_info=True)
        return False
```

### Backend: `ai.debug.trace` UUID Field

```python
# Source: mail/models/discuss/mail_guest.py (uuid4 default pattern)
import uuid
from odoo import fields, models

class AiDebugTrace(models.Model):
    _name = 'ai.debug.trace'
    # ...existing fields...
    bus_channel = fields.Char(
        string='Bus Channel',
        default=lambda self: str(uuid.uuid4()),
        readonly=True,
        copy=False,
        index=True,
    )
```

### Backend: `IrWebsocket` Override

```python
# Source: enterprise/spreadsheet_edition/models/ir_websocket.py pattern
from odoo import models

class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = list(channels)
        if not self.env.user.has_group('base.group_system'):
            channels = [
                c for c in channels
                if not (isinstance(c, str) and c.startswith('ai_debug:trace:'))
            ]
        return super()._build_bus_channel_list(channels)
```

### Frontend: OWL Client Action with Bus Subscription

```javascript
// Source: mail/static/src/core/public_web/discuss_app/client_action.js (action pattern)
//         hr_attendance/static/src/components/hr_presence_status/ (bus lifecycle pattern)
import { Component, onMounted, onPatched, onWillUnmount, useState, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class DebugPanel extends Component {
    static template = "ai_debug.DebugPanel";
    static props = ["action", "*"];

    setup() {
        this.busService = useService("bus_service");
        this.state = useState({ iterations: [], traceStatus: "running" });
        this.scrollRef = useRef("timeline");

        // bus_channel is injected into action context when opening the panel
        this.channel = this.props.action.context?.bus_channel;

        this._onIteration = this._onIteration.bind(this);
        this._onToolCall = this._onToolCall.bind(this);
        this._onTraceUpdate = this._onTraceUpdate.bind(this);

        onMounted(() => {
            if (this.channel) {
                this.busService.addChannel(this.channel);
                this.busService.subscribe("ai_debug/iteration", this._onIteration);
                this.busService.subscribe("ai_debug/tool_call", this._onToolCall);
                this.busService.subscribe("ai_debug/trace_update", this._onTraceUpdate);
            }
        });

        onPatched(() => {
            if (!this.userScrolledUp && this.scrollRef.el) {
                this.scrollRef.el.scrollTop = this.scrollRef.el.scrollHeight;
            }
        });

        onWillUnmount(() => {
            if (this.channel) {
                this.busService.unsubscribe("ai_debug/iteration", this._onIteration);
                this.busService.unsubscribe("ai_debug/tool_call", this._onToolCall);
                this.busService.unsubscribe("ai_debug/trace_update", this._onTraceUpdate);
                this.busService.deleteChannel(this.channel);
            }
        });
    }
}
registry.category("actions").add("ai_debug.debug_panel", DebugPanel);
```

### Frontend: Opening the Panel from the Trace Form

Two approaches are valid:

**Option A — Python server action (recommended):** Add a button in `ai_debug_trace_views.xml` that calls a Python method returning an `ir.actions.client` dict:

```python
def action_open_live_panel(self):
    self.ensure_one()
    return {
        'type': 'ir.actions.client',
        'tag': 'ai_debug.debug_panel',
        'name': f'Live Panel — Trace #{self.id}',
        'target': 'new',  # or a dedicated URL with path
        'context': {
            'trace_id': self.id,
            'bus_channel': self.bus_channel,
        },
    }
```

**Option B — Static `ir.actions.client` with trace_id in URL:** Declare a static action with `path='ai-debug'`; the JS component reads `trace_id` from the URL query string and RPC-fetches `bus_channel`. This enables bookmarkable URLs.

The `target: 'new'` approach opens in a dialog/new window context inside the current tab, not a separate browser tab. For a true separate browser tab, use `ir.actions.act_url` pointing at `/odoo/ai-debug?trace_id=N`, or `browser.open('/odoo/ai-debug?trace_id=N', '_blank')` from a JS button.

### Frontend: Connection Status Badge

```javascript
// Source: bus/static/src/services/bus_monitoring_service.js (WORKER_STATE pattern)
// bus_service.workerState is reactive (set via BUS:WORKER_STATE_UPDATED)
get connectionStatus() {
    const s = this.busService.workerState;
    if (s === "CONNECTED") return "connected";
    if (s === "CONNECTING") return "reconnecting";
    if (s === "DISCONNECTED") return "disconnected";
    return "connecting";
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Longpolling (`/longpolling/poll`) | WebSocket via SharedWorker | Odoo 16/17 | Must use `bus_service` JS service, not direct HTTP polling |
| `bus.bus._sendone` called directly after ORM write | `_sendone` uses `cr.precommit`/`cr.postcommit` hooks | Odoo 17 | Must call `_sendone` before cursor commit; hooks handle timing automatically |
| `ir.websocket._subscribe` override (iot pattern) | `ir.websocket._build_bus_channel_list` override | Odoo 17/master | `_build_bus_channel_list` is the recommended extension point; `_subscribe` override is lower-level and not recommended |

**Deprecated/outdated:**
- Longpolling: `/longpolling/poll` endpoint still exists but SharedWorker WebSocket is now primary. Do not use polling.
- Direct `bus.bus.create()` calls: `_sendone` is the correct API; direct `create()` bypasses the pg_notify hook.

---

## Open Questions

1. **"Open in new tab" mechanism**
   - What we know: `ir.actions.act_url` with `target: '_blank'` opens a URL in a new browser tab. `ir.actions.client` opens within the Odoo webclient. The `target: 'new'` for `ir.actions.client` opens a dialog, not a browser tab.
   - What's unclear: The requirement says "separate browser tab." This requires either `ir.actions.act_url` pointing to a routed URL (e.g., `/odoo/ai-debug`), or `window.open(url, '_blank')` from a JS button. The static `path` field on `ir.actions.client` enables `/odoo/ai-debug` URL but the action still runs inside the Odoo shell — navigating to it in a new tab works.
   - Recommendation: Use `ir.actions.client` with a `path` field (e.g., `path='ai-debug'`). The "Open Live Panel" button on the trace form uses `browser.open('/odoo/ai-debug?trace_id=N', '_blank')` to open a new tab at that URL. The component reads `trace_id` from the URL and RPC-fetches `bus_channel`. This is the cleanest separation.

2. **Notification payload granularity**
   - What we know: The locked decision says live panel shows iteration/tool call nodes as they arrive. The bus notification payload should be minimal (summary only) to stay under pg_notify limits.
   - What's unclear: Whether the component fetches full detail (messages, raw_response, state_before/after) eagerly on arrival or lazily on expand.
   - Recommendation: Lazy fetch on expand (RPC call when user clicks to expand an iteration). This avoids N+1 eager loads for long loops and keeps bus payloads small.

3. **`bus_channel` field exposure in the backend view**
   - What we know: The `bus_channel` UUID needs to be accessible from the trace form button.
   - What's unclear: Whether to expose it in the form view or keep it invisible.
   - Recommendation: Keep it as an `invisible` field in the trace form view (or don't render it at all — the button's `action_open_live_panel` method reads it server-side). No UI exposure needed.

---

## Sources

### Primary (HIGH confidence)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `BusBus._sendone`, `_ensure_hooks`, precommit/postcommit hook behavior, NOTIFY_PAYLOAD_MAX_LENGTH
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/ir_websocket.py` — `IrWebsocket._build_bus_channel_list`, `_prepare_subscribe_data` base implementation
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/services/bus_service.js` — `addChannel`, `deleteChannel`, `subscribe`, `unsubscribe`, `workerState` reactive state
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/workers/websocket_worker.js` — `WORKER_STATE` enum values (CONNECTED, DISCONNECTED, IDLE, CONNECTING)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/static/src/services/bus_monitoring_service.js` — workerState event handling pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/spreadsheet_edition/models/ir_websocket.py` — access-checked `_build_bus_channel_list` override pattern
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-imp-ai-composable-prompts-jcb/iot/models/ir_websocket.py` — `_subscribe` override with channel injection (reference only)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/mail/static/src/core/public_web/discuss_app/client_action.js` — `ir.actions.client` OWL component + `registry.category("actions").add(tag, Component)` pattern
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/hr_attendance/static/src/components/hr_presence_status/hr_attendance_presence_status.js` — `addChannel`/`subscribe`/`unsubscribe`/`deleteChannel` lifecycle in OWL component with `onMounted`/`onWillUnmount`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/mail/models/discuss/mail_guest.py` — `uuid.uuid4()` lambda default field pattern
- `/Users/joseph/clones/odoo/custom/ai_debug/models/ai_session.py` — existing separate cursor write helpers (`_debug_write_trace`, `_debug_write_iteration`, `_debug_write_tool_call`)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/tests/test_notify.py` — precommit/postcommit timing verification

### Secondary (MEDIUM confidence)
- OWL `onPatched` for post-render auto-scroll — verified by pattern in `mail/static/src/utils/common/hooks.js` and `call_participant_video.js`; scroll direction logic is standard DOM behavior

### Tertiary (LOW confidence)
- None — all critical claims verified against source code

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs verified directly from Odoo master source
- Architecture: HIGH — all patterns from production Odoo modules (mail, hr_attendance, spreadsheet_edition, iot)
- Pitfalls: HIGH — pitfalls derived from reading actual implementation code, not guessing
- JSON tree / state diff: MEDIUM — hand-rolled approach is the only viable option (no library exists in bundle); the algorithm is straightforward but untested against actual state shapes

**Research date:** 2026-02-20
**Valid until:** 2026-03-22 (Odoo master moves fast; verify bus API if > 30 days)
