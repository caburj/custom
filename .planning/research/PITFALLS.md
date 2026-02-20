# Pitfalls Research

**Domain:** Odoo standalone OWL app + bus.bus streaming — migration from DB-backed to ephemeral architecture
**Researched:** 2026-02-20
**Confidence:** HIGH (based on direct source inspection at referenced paths)

This document is scoped to the v1.1 migration: removing DB models, adding a standalone OWL app at `/ai-debug`, and streaming full payloads over bus.bus. The v1.0 generator-wrapping pitfalls are preserved because they remain relevant, but the emphasis shifts to migration-specific failure modes.

---

## Critical Pitfalls

### Pitfall 1: Standalone App Asset Bundle Uses Wrong Bundle — Services Unavailable

**What goes wrong:**

The standalone app at `/ai-debug` renders a custom HTML template that calls `t-call-assets` with a bundle name. If that bundle is `web.assets_backend`, it loads the full Odoo backend (menus, actions, webclient chrome). If it's a custom bundle that omits required service registrations, the OWL app fails to start because `bus_service`, `orm`, or `notification` dependencies are missing. The error is a cryptic `Error: Cannot find service 'bus_service'` thrown during `startServices(env)`.

**Why it happens:**

Copying the POS pattern without understanding that `point_of_sale._assets_pos` explicitly includes `bus/static/src/services/bus_service.js`, `worker_service.js`, `bus_parameters_service.js`, and related workers. The standalone app can't just load `web.assets_backend` and strip things out — the backend bundle assumes menus are loaded (`odoo.loadMenusPromise`), which fails without the `/web/webclient/load_menus` call.

**How to avoid:**

Use one of two approaches. Simple: Load `web.assets_backend` in the template but short-circuit menu loading in the template script block before the bundle loads:

```javascript
// In the QWeb template, before t-call-assets
odoo.loadMenusPromise = Promise.resolve({});
```

Advanced: Create a dedicated `ai_debug.assets_app` bundle that explicitly includes only what is needed, following the `point_of_sale.base_app` pattern (includes `web._assets_core`, `bus/static/src/services/bus_service.js`, workers, ORM service). Do not use `web.assets_backend` in a standalone app — it triggers menu loading and expects the full webclient bootstrap context.

The POS does this correctly in `/addons/point_of_sale/views/pos_assets_index.xml` line 32: `odoo.loadMenusPromise = Promise.resolve();`

**Warning signs:**

- `Cannot find service 'menu'` or `Cannot read properties of undefined (reading 'id')` in the browser console when the standalone app loads
- The top Odoo navbar and debug bar appear in the standalone page (wrong bundle)
- The app loads but `useService('bus_service')` throws because bus_service depends on `worker_service` which was not started

**Phase to address:** Phase 1 (Standalone App Scaffold)

---

### Pitfall 2: HTTP Controller Missing `session_info` in Template Context — Bus Auth Fails

**What goes wrong:**

The Odoo bus WebSocket authenticates via the user's session. When the standalone page loads, the JS needs `__session_info__` embedded in the HTML (containing `db`, `uid`, `csrf_token`) to initialize the bus connection. If the HTTP controller renders the template without passing `session_info`, the bus worker starts with an anonymous session, the WebSocket handshake fails, and `bus_service` never reaches `CONNECTED` state.

**Why it happens:**

Developers write a minimal controller like:
```python
@http.route('/ai-debug', type='http', auth='user')
def ai_debug(self):
    return request.render('ai_debug.index', {})
```

Without `session_info`, the `odoo.__session_info__` JS global is either undefined or contains stale data from a previous page load.

**How to avoid:**

Follow the POS pattern exactly:

```python
@http.route('/ai-debug', type='http', auth='user')
def ai_debug(self):
    session_info = request.env['ir.http'].session_info()
    return request.render('ai_debug.index', {
        'session_info': session_info,
    })
```

In the QWeb template:
```xml
<script type="text/javascript">
    var odoo = <t t-out="json.dumps({'csrf_token': request.csrf_token(None), '__session_info__': session_info})"/>;
    odoo.loadMenusPromise = Promise.resolve({});
</script>
```

`Cache-Control: no-store` on the response is also required — the session info changes between logins.

**Warning signs:**

- `BUS:WORKER_STATE_UPDATED` event fires with state `DISCONNECTED` immediately after `CONNECTING`
- WebSocket closes with code 4001 (`SESSION_EXPIRED`) in the browser devtools Network tab
- `session.uid` is undefined in the browser console when `import { session } from '@web/session'` is used

**Phase to address:** Phase 1 (Standalone App Scaffold)

---

### Pitfall 3: Removing DB Models Without a Migration Script — Orphaned Tables and `ir.model` Records

**What goes wrong:**

Deleting `ai_debug_trace.py`, `ai_debug_iteration.py`, and `ai_debug_tool_call.py` from the module and bumping the version causes Odoo module upgrade to remove the `ir.model`, `ir.model.fields`, and `ir.model.access` data records (via `ir_model_data._module_data_uninstall`). However, the underlying PostgreSQL tables (`ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call`) are **not automatically dropped**. This leaves orphaned tables in the database that accumulate data forever, silently consuming disk space. Worse, if the module is ever reinstalled with a different schema for the same model name, Odoo tries to `ALTER TABLE` the existing orphaned table and may fail on column conflicts.

**Why it happens:**

Developers assume Odoo's ORM manages table lifecycle symmetrically — it creates tables on `_auto_init` but does not drop them on uninstall. This is intentional (data safety), but requires explicit cleanup when dropping a model from a module.

**How to avoid:**

Write a `pre-migrate` script in `migrations/<version>/pre-migrate.py`:

```python
from odoo import api, SUPERUSER_ID

def migrate(cr, version):
    # Drop orphaned debug tables — data is intentionally discarded (ephemeral by design)
    cr.execute("DROP TABLE IF EXISTS ai_debug_tool_call CASCADE")
    cr.execute("DROP TABLE IF EXISTS ai_debug_iteration CASCADE")
    cr.execute("DROP TABLE IF EXISTS ai_debug_trace CASCADE")
```

Run `DROP TABLE IF EXISTS ... CASCADE` to also clean up any foreign key constraints. The `CASCADE` is safe here because these tables only reference each other.

Additionally, remove the `security/ir.model.access.csv` file and its reference in `__manifest__.py['data']` — leave it in place until after the migration script runs if the upgrade order matters.

**Warning signs:**

- `pg_class` shows `ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call` tables after the module upgrade
- The module upgrade completes without error, but `\dt ai_debug*` in psql still lists the old tables
- A later reinstall attempt fails with `column "X" of relation "ai_debug_trace" already exists`

**Phase to address:** Phase 1 (DB Model Removal Migration)

---

### Pitfall 4: Full LLM Payload Sent Over bus.bus — Message Is Too Large for Reliable Delivery

**What goes wrong:**

A full agentic loop iteration payload (system prompt + conversation history + raw LLM response) can be 50–500 KB. The `bus_bus.message` field is `fields.Char` (PostgreSQL VARCHAR with no length constraint), so the message is stored without error. However, delivering it via WebSocket to the browser causes two problems:

1. The browser's WebSocket receives a single large frame and passes it to the SharedWorker. The worker calls `postMessage()` to the main thread with the full payload. The structured clone of a 200 KB object blocks the main thread for 20–100 ms — visible as jank on every iteration during an active session.

2. The Odoo WebSocket server (Python) sends notifications by fetching from `bus_bus` and calling `websocket._send_frame()`. There is no per-message size check before sending outbound frames — the 1 MB `MESSAGE_MAX_SIZE` limit applies only to **inbound** frames (client to server). Outbound large messages do succeed, but they may trigger browser-side WebSocket close code 1009 if the browser enforces its own receive limit.

Note: The 8 KB `NOTIFY_PAYLOAD_MAX_LENGTH` is for the PostgreSQL pg_notify channel list (the list of channel names to wake up), **not** for the message content stored in `bus_bus`. This is a common misreading of the source.

**Why it happens:**

The v1.0 pattern sends only a tiny summary in the bus notification and lazily fetches full data via ORM. The v1.1 mandate of "full payloads over bus.bus" is taken literally, but the intention is "no lazy ORM reads for the UI" — not "stuff the entire LLM conversation into the WebSocket frame." Developers assume "no size limit" from reading the source and skip the performance analysis.

**How to avoid:**

Cap individual bus payloads at a practical limit of ~32 KB. For iteration payloads that exceed this:

1. Split into multiple bus events: one `ai_debug/iteration_meta` (index, duration, tool_count — tiny) followed by one `ai_debug/iteration_detail` (messages_sent, raw_response — potentially large, sent separately only when detail panel is open).
2. Or: send `ai_debug/iteration_meta` via bus and provide a JSON RPC endpoint (`/ai-debug/iteration/<id>`) that returns the full payload on demand when the user clicks into the detail panel.

The second approach is preferred for the sidebar layout: the sidebar tree only needs the meta (iteration number, duration, tool count), and the detail panel fetches on selection.

**Warning signs:**

- Noticeable browser jank (dropped frames) during active agentic loop sessions with RAG context enabled
- WebSocket close code 1009 in browser devtools during sessions with long conversation history
- `bus_bus` table row size exceeds 8 KB (check with `pg_column_size(message)`) for iteration events

**Phase to address:** Phase 2 (Bus Payload Design) — must be decided before writing the instrumentation send logic

---

### Pitfall 5: `_sendone` Inside a Separate Cursor — Notification Lost If Outer Transaction Is Already Committed

**What goes wrong:**

The v1.0 instrumentation uses `with self.env.registry.cursor() as cr:` to write trace data in a cursor separate from the main agentic loop transaction. The v1.1 approach removes the DB models but still sends bus notifications. If the bus `_sendone` call is made on the main cursor (`self.env.cr`) during the generator's execution, the notification sits in `precommit.data` and only fires when the main cursor commits — which may be long after the iteration completes (the main transaction may not commit until the entire HTTP request finishes). The debug panel sees a burst of events at the end of the loop, not a real-time stream.

**Why it happens:**

`_sendone` hooks into `precommit` and `postcommit` on the cursor it is called on. Calling it on the main cursor means notifications batch-fire at the end of the HTTP response, not at each iteration. This worked in v1.0 because separate cursors commit immediately on `__exit__`, triggering pg_notify promptly.

**How to avoid:**

Continue using a separate short-lived cursor for each bus notification, even after the DB models are removed:

```python
def _debug_send_event(self, event_type, payload):
    try:
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            env['bus.bus']._sendone('ai_debug:traces', event_type, payload)
            # cursor commits here, triggering pg_notify immediately
    except Exception:
        _logger.warning('ai_debug: failed to send bus event', exc_info=True)
```

Each separate cursor commits independently, so pg_notify fires at each iteration boundary, giving the frontend true real-time updates.

**Warning signs:**

- Debug panel receives all iteration events simultaneously at the end of the agentic loop, not one by one during execution
- All bus events share the same `id` sequence in `bus_bus` (they were all inserted in the same precommit batch)
- Timing information shows all events with the same `create_date` in `bus_bus`

**Phase to address:** Phase 2 (Bus Notification Architecture)

---

### Pitfall 6: OWL Standalone App Mounted on `document.body` With Odoo Backend Also Present

**What goes wrong:**

If the standalone app template is rendered by navigating to `/ai-debug` from within the Odoo backend (e.g., via a redirect from the menus), the backend's OWL app may already be mounted on `document.body`. Mounting a second OWL app on the same target node causes undefined behavior: the existing backend app's event listeners fire on DOM events in the debug app, global service singletons conflict, and `__WOWL_DEBUG__` is overwritten. The result ranges from "the debug panel doesn't render" to "the backend app crashes silently."

**Why it happens:**

Developers test the standalone URL by navigating from the backend during development. The `ir.actions.act_url` with `target: 'new'` opens a new window/tab, but the `target: 'self'` redirect from a menu item would navigate the current window, potentially causing this conflict.

**How to avoid:**

- Always open `/ai-debug` in a new tab. The HTTP controller must respond with a full standalone HTML page (its own `<!DOCTYPE html>`), not an OWL action injected into the existing backend. The template must be a complete HTML document, not a partial.
- The menu item that opens the debug app should use `type: 'ir.actions.act_url'` with `target: 'new'` (opens new tab), not `target: 'self'`.
- In the standalone template, do not include `web.webclient_bootstrap` — use a minimal custom template that boots a fresh OWL environment.

**Warning signs:**

- The debug panel renders inside the Odoo webclient's `<div class="o_web_client">` instead of a blank page
- OWL console errors referencing `Component already mounted` or service conflicts immediately on load
- The Odoo navbar appears at the top of the "standalone" app

**Phase to address:** Phase 1 (Standalone App Scaffold)

---

### Pitfall 7: Sidebar Tree Loses Selection State on Every Bus Event

**What goes wrong:**

The sidebar tree holds Loop > Iteration > Tool Call as a hierarchy. Each bus event (new iteration, new tool call) updates the state array. If the sidebar component re-renders by replacing the entire array (e.g., `this.state.loops = newLoops`), OWL diffs the new vdom against the old. Without stable `t-key` on each tree node, OWL unmounts and remounts all child nodes on every bus event, resetting any expanded/selected state to the component defaults. The user's selected iteration collapses every time a new tool call arrives.

**Why it happens:**

OWL's virtual DOM diffing requires `t-key` on repeated nodes to identify stable elements. The default diffing by position is fine for static lists but wrong for append-only lists where new items arrive at the end while the user is interacting with earlier items.

**How to avoid:**

Use stable unique keys on all tree nodes:

```xml
<t t-foreach="state.loops" t-as="loop" t-key="loop.id">
    <t t-foreach="loop.iterations" t-as="iter" t-key="iter.id">
        <t t-foreach="iter.toolCalls" t-as="tc" t-key="tc.id">
```

Use `reactive()` objects for mutation instead of array replacement — `state.loops.push(newLoop)` is safer than `state.loops = [...state.loops, newLoop]`. The existing v1.0 code correctly uses `this.state.iterations.push(...)` instead of assignment, which is the right pattern.

For nested subagent loops, ensure the loop ID is globally unique across parent and child loops — a flat integer counter is sufficient, but must be monotonically increasing across all loops in the session.

**Warning signs:**

- Clicking on an iteration in the sidebar causes it to expand, then it collapses immediately when the next bus event arrives
- The detail panel goes blank (selection is cleared) during active tool execution
- Browser console shows OWL warnings about duplicate keys if two loops share the same root ID

**Phase to address:** Phase 3 (Sidebar Tree Component)

---

### Pitfall 8: Subagent Loop Events Arrive Out of Order — Frontend State Corrupted

**What goes wrong:**

When the `ai` module eventually supports subagents, the parent loop spawns a child loop that runs to completion before the parent continues. Bus events from both loops arrive on the same `ai_debug:traces` channel. If the frontend identifies events only by `loop_id` without a parent/child relationship, a child loop event with an unknown `loop_id` is either silently dropped or creates a new top-level loop in the sidebar — both are wrong.

Even without subagent support in the upstream module, the data design must anticipate this. An event arrives with `{loop_id: 42, parent_loop_id: 41, iteration_index: 0}`. If the frontend only tracks a flat list of loops, it has no slot for `loop_id: 42` under `loop_id: 41`.

**Why it happens:**

Designing the data model and state shape for "what exists today" (flat loops) rather than "what the architecture anticipates." The PROJECT.md explicitly states subagent-ready data design is required even though the feature is deferred.

**How to avoid:**

Model the state as a tree from the start:

```javascript
// Each loop node can have child_loops
this.state = useState({
    loops: [],  // top-level only
    loopsById: {},  // flat index for O(1) lookup
});

// When a loop_start event arrives:
function addLoop(payload) {
    const loop = { id: payload.loop_id, parentId: payload.parent_loop_id, iterations: [], childLoops: [] };
    this.state.loopsById[loop.id] = loop;
    if (loop.parentId && this.state.loopsById[loop.parentId]) {
        this.state.loopsById[loop.parentId].childLoops.push(loop);
    } else {
        this.state.loops.push(loop);  // top-level
    }
}
```

The sidebar tree component renders recursively from `state.loops`, naturally handling nested loops.

On the Python side, the bus event for `ai_debug/loop_start` must include `parent_loop_id` (null for top-level loops). This field must be in the schema from the first version, even if it is always null in v1.1.

**Warning signs:**

- Flat `state.loops = [{loop_id, iterations: [...]}, ...]` without a `parent_loop_id` field
- The bus event schema does not include `parent_loop_id` in the payload dict
- Sidebar tree uses a simple `<ul><li>` with no recursive component structure

**Phase to address:** Phase 2 (Bus Event Schema) and Phase 3 (Sidebar Tree)

---

### Pitfall 9: `_build_bus_channel_list` Override Access Check Missing After DB Models Removed

**What goes wrong:**

In v1.0, the `ir.websocket` override checks `self.env.user.has_group('base.group_system')` and strips `ai_debug:` channels for non-system users. In v1.1, after removing the DB models, the channel names change (no more per-trace UUID channels — the schema may change). If the override is not updated to match the new channel naming scheme, either:

(a) The security check uses the old channel prefix pattern and passes all events through for non-system users because the new channels use a different prefix, or

(b) The check is too broad and strips channels from users who should have access (e.g., any internal user).

**Why it happens:**

The `ir_websocket.py` override is written once and forgotten. During the migration from DB-backed (per-trace UUID channels like `ai_debug:trace:{uuid}`) to pure streaming (e.g., `ai_debug:session:{session_key}`), the channel prefix changes. The security filter does a prefix match. If the new prefix doesn't match, the filter silently passes all events.

**How to avoid:**

After changing the channel naming scheme, immediately update the `_build_bus_channel_list` override to match. Use a single canonical prefix (e.g., `ai_debug:`) that covers all debug channels regardless of schema changes within that namespace. The current override already does this correctly with `ch.startswith('ai_debug:')` — preserve this pattern and do not narrow it to specific sub-prefixes.

Decision: The access control should be `base.group_user` (any internal user) rather than `base.group_system` (only admin), since the project requires "any internal user (`base.group_user`)". The current override incorrectly restricts to system users only.

**Warning signs:**

- Non-admin internal users can't see the debug panel because the bus channel is stripped before delivery
- A changed channel prefix (e.g., `ai_debug_session:` instead of `ai_debug:session:`) bypasses the security filter entirely
- `ir.websocket` override is not updated alongside a channel naming change

**Phase to address:** Phase 1 (Migration) — must be updated atomically with channel naming changes

---

### Pitfall 10: Generator Still Writing to Removed DB Models — RuntimeError on `env['ai.debug.trace']`

**What goes wrong:**

After removing the model files, if the instrumentation code in `ai_session.py` still calls `env['ai.debug.trace'].create(vals)`, Odoo raises `KeyError: 'ai.debug.trace'` (model not in registry) at runtime. The agentic loop then raises, and the exception propagates to the user as a 500 error. Worse: if the exception happens inside the generator, the `yield` never completes, and any caller doing `yield from` also fails silently.

**Why it happens:**

The migration removes the model Python files and bumps the module version, but the `ai_session.py` instrumentation code is not updated simultaneously. If the developer upgrades the module without doing a full Odoo restart, the old Python modules may still be in the import cache, masking the problem during development. It surfaces when the container restarts or in CI.

**How to avoid:**

Make the model removal and the instrumentation update a single atomic commit. The `_debug_write_trace`, `_debug_write_iteration`, and `_debug_write_tool_call` methods in `ai_session.py` must be rewritten to call the new bus-only path **before** removing the model classes. Sequence:

1. Add the new `_debug_send_event()` method (bus-only)
2. Update all callers to use `_debug_send_event()`
3. Remove DB write helper methods
4. Remove model classes
5. Bump version

**Warning signs:**

- `KeyError: 'ai.debug.trace'` in server logs after upgrade
- The agentic loop raises a 500 during the first run after the module upgrade
- `env.registry.models` does not contain `ai.debug.trace` but the code references it

**Phase to address:** Phase 1 (Migration) — the removal and the rewrite are the same task

---

### Pitfall 11: Bus Events Accumulate in `bus_bus` Table Without GC — Disk Fills

**What goes wrong:**

In v1.0, the debug data lived in `ai_debug_trace` with a configurable retention `@api.autovacuum` cron. In v1.1, all data is ephemeral — it lives only in the browser until page refresh. However, the bus messages sent to broadcast that data are still persisted in the `bus_bus` table. The default GC for `bus_bus` is 24 hours (`DEFAULT_GC_RETENTION_SECONDS = 86400`). During an active development session with many agentic loop runs (each with 10 iterations and 5 tool calls), this generates ~150 bus records per loop run. Over a day of development with 50 runs, that's 7,500 rows — small, but if each row contains a 32 KB payload (the "full payloads" design), that's 240 MB in `bus_bus` in one day.

**Why it happens:**

Developers move trace storage out of custom tables (they notice the DB disk usage) but forget that `bus_bus` also stores all messages. The GC exists and runs automatically, but a 24-hour retention with large payloads is still a lot of disk.

**How to avoid:**

Keep bus payloads small (see Pitfall 4). The `bus_bus` GC (`bus.gc_retention_seconds` ir.config_parameter) is already configurable — document this for deployers. For development, keep payloads at a few KB each; disk usage is then negligible. Do not try to manage `bus_bus` GC from within the module — the existing autovacuum handles it.

**Warning signs:**

- `SELECT pg_size_pretty(pg_total_relation_size('bus_bus'))` returns more than 100 MB after a day of development
- `SELECT count(*), avg(length(message)) FROM bus_bus WHERE channel LIKE '%ai_debug%'` shows large average message sizes
- Disk alert on the development machine after a week of AI debugging sessions

**Phase to address:** Phase 2 (Bus Payload Design) — keeping payloads small prevents this entirely

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Send full LLM payload in bus message | Simplest code path | Jank on each iteration; large `bus_bus` rows; possible browser WebSocket close 1009 | Never — split meta/detail |
| Use `web.assets_backend` for standalone app without short-circuiting menu load | No new bundle to maintain | `loadMenusPromise` fails or causes unnecessary `/web/webclient/load_menus` RPC; navbar chrome leaks into standalone | Only if `loadMenusPromise = Promise.resolve({})` is added to the template |
| Skip migration script for dropped models | Faster PR | Orphaned tables with no FK references accumulate silently; future reinstall may conflict on schema | Never — always write the DROP TABLE migration |
| Keep `ir.model.access.csv` entries for removed models | Avoids merge conflicts | Odoo upgrade warns about unknown models; CSV entries are silently ignored but add confusion | Never — remove atomically with the model |
| Use flat loops array instead of tree structure | Simpler state | Must rewrite when subagent events arrive; sidebar tree can't be extended without breaking existing event handling | Acceptable only if subagent support is explicitly deferred to v2 AND the event schema already includes `parent_loop_id: null` |
| Reuse the v1.0 `_build_bus_channel_list` override unchanged | No code change needed | Access group may still be `group_system` when spec says `group_user`; channel prefix pattern may not match new names | Never — update atomically with channel renaming |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Standalone app template | Rendering a partial template fragment | Render a full `<!DOCTYPE html>` document with its own `<head>` and JS boot block |
| `bus.bus._sendone` timing | Calling on main cursor and expecting real-time delivery | Use a separate short-lived cursor; commit immediately to trigger pg_notify at each iteration |
| OWL `mountComponent` | Calling without `loadMenusPromise` set | Set `odoo.loadMenusPromise = Promise.resolve({})` before the asset bundle loads |
| `ir.websocket._build_bus_channel_list` | Updating the prefix string without updating the override | Change the prefix and the filter in the same commit |
| DB model removal | Removing `.py` files and assuming tables are cleaned up | Write a `pre-migrate.py` with explicit `DROP TABLE IF EXISTS ... CASCADE` |
| Migration version bump | Bumping version in `__manifest__.py` without creating the migrations directory | Create `migrations/<new_version>/pre-migrate.py`; Odoo only runs migration scripts if the version string changes AND the file exists |
| `fields.Json` in bus payload | Serializing datetime objects with `json.dumps` directly | Use `json.dumps(payload, default=json_default)` from `odoo.tools` |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Large bus payload in SharedWorker `postMessage` | Main thread jank (jank monitor shows >50ms frames) during active session | Cap bus payloads at ~32 KB; send meta + fetch-on-demand for detail | First session with RAG context (typically >50 KB) |
| Separate cursor per bus send | N separate DB connections per loop iteration (one per iteration + one per tool call) | Batch multiple bus sends into a single cursor; or use the main cursor for non-real-time events | Under heavy concurrent use (>5 users debugging simultaneously) |
| Recursive OWL component for deep subagent trees | Stack overflow rendering deeply nested loops | Set a max render depth (3–4 levels); use virtual scrolling for large trees | When subagents are introduced with >3 nesting levels |
| `useState` with large array of objects | OWL reactive tracking overhead on every push | Keep state objects flat; use `loopsById` index map for O(1) lookup; avoid deeply nested reactive objects | After >100 iterations in a single session |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Debug channel accessible to any authenticated user | Any internal user can subscribe to another's debug session | `_build_bus_channel_list` override must verify user identity before adding channel; `base.group_user` is the minimum, not the absence of a check |
| Full LLM prompt (including system instructions with PII) in bus payload | LLM prompts often contain customer record data; sending full payload to all internal users exposes it | Restrict bus delivery to the session owner; or send only summaries publicly and full detail only to the session owner's channel |
| `auth='user'` on the debug route not enforcing internal user check | External portal users accessing the debug app | Add `request.env.user._is_internal()` check, mirroring the POS pattern (`is_internal_user = request.env.user._is_internal()`) |
| CSRF token not included in standalone page template | JSON RPC calls from the standalone app fail with CSRF errors | Include `csrf_token: request.csrf_token(None)` in the `odoo` JS global in the template, as POS does |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Sidebar collapses to top-level loops only on reconnect | All expanded detail panels reset when WebSocket reconnects | Store selected/expanded state in `sessionStorage`, restore on reconnect |
| Detail panel shows JSON blob with no structure | Large unformatted JSON is unreadable | The existing `JsonTree` component from v1.0 handles this — carry it forward unchanged |
| No visual distinction between running and completed loops in the sidebar | Developer can't tell at a glance which loop is active | Use a distinct visual indicator (spinner, color) for `state === 'running'` loops; gray out completed ones |
| "Waiting for session" state has no timeout indicator | Developer opens panel, nothing happens, wonders if it's broken | Show elapsed time in "waiting" state: "Listening for next session... (0:23 elapsed)" |

---

## "Looks Done But Isn't" Checklist

- [ ] **Standalone app auth gate:** Navigate to `/ai-debug` while logged out — verify redirect to `/web/login` with correct redirect param, not a 500 or blank page.
- [ ] **Session info embedded:** Open the page source of `/ai-debug` — verify `odoo.__session_info__` contains `uid`, `db`, and `csrf_token` in the inline script block.
- [ ] **DB tables removed:** After running `odoo -u ai_debug`, check `\dt ai_debug*` in psql — the tables must not exist.
- [ ] **Bus event timing:** Start an agentic loop and watch the debug panel in real time — iteration cards must appear one by one during execution, not all at once after the loop finishes.
- [ ] **Sidebar selection survives bus events:** Click on iteration #1, then trigger a new tool call. Verify iteration #1 detail panel remains selected and does not collapse.
- [ ] **Non-admin internal user access:** Log in as a non-admin internal user, navigate to `/ai-debug`, start an AI session — verify events arrive (not blocked by the channel security filter).
- [ ] **Payload size check:** After a RAG-enabled session, run `SELECT max(length(message)) FROM bus_bus WHERE channel LIKE '%ai_debug%'` — result must be under 65536 bytes.
- [ ] **parent_loop_id in schema:** Inspect a `ai_debug/loop_start` bus event payload — verify `parent_loop_id` key is present (even if null) before subagent support is added.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong asset bundle (no services) | LOW | Add `loadMenusPromise` short-circuit to template; correct bundle reference in manifest |
| Missing session info in template | LOW | Add `session_info` to controller context and `odoo.__session_info__` to template |
| Orphaned DB tables after model removal | LOW | Write and run `DROP TABLE IF EXISTS ... CASCADE` migration; re-upgrade module |
| Large bus payloads causing jank | MEDIUM | Refactor bus events to meta-only; add JSON RPC detail endpoint; frontend change to fetch on demand |
| Bus events batching (main cursor) | MEDIUM | Refactor send helpers to use separate cursors; requires testing each iteration yields a separate pg_notify |
| Generator still writes to removed models | HIGH | Emergency hotfix: add `try/except KeyError` guard in capture methods while the proper rewrite is prepared; deploy proper fix (rewrite + model removal) as the follow-up |
| Sidebar loses state on every bus event | LOW | Add `t-key` on all tree nodes; switch from array replacement to `push()` mutation |
| Access check wrong group (`group_system` not `group_user`) | LOW | Update `_build_bus_channel_list` override; test with non-admin user |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Standalone app wrong asset bundle / no services | Phase 1: Scaffold | Navigate to `/ai-debug`; `useService('bus_service')` does not throw |
| Missing `session_info` in template | Phase 1: Scaffold | Check page source for `odoo.__session_info__` containing uid |
| Orphaned DB tables after model removal | Phase 1: DB Migration | `\dt ai_debug*` shows no tables after upgrade |
| Generator still references removed models | Phase 1: DB Migration | Run an agentic loop immediately after upgrade; no KeyError in logs |
| Access check wrong group | Phase 1: Migration | Non-admin internal user can see debug panel events |
| Large bus payloads | Phase 2: Bus Design | `max(length(message))` < 65536 after RAG session |
| Bus events batch-fire at end instead of real-time | Phase 2: Bus Design | Events arrive one-by-one during execution in the panel |
| Bus payload accumulation in `bus_bus` | Phase 2: Bus Design | Payload size kept small; disk usage negligible after 1 day |
| `parent_loop_id` missing from event schema | Phase 2: Bus Design | Event payloads contain `parent_loop_id` key |
| Sidebar loses selection on bus events | Phase 3: Sidebar Tree | Click iteration; trigger new tool call; selection stable |
| Subagent events arrive with unknown parent | Phase 3: Sidebar Tree | LoopsById index handles unknown parent gracefully |
| OWL app mounted on wrong element / conflicts with backend | Phase 1: Scaffold | Navigate from backend to `/ai-debug` in new tab; no OWL conflicts in console |

---

## Sources

- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `_sendone` precommit/postcommit mechanism, `NOTIFY_PAYLOAD_MAX_LENGTH` (applies to pg_notify channel list, not message content), `MESSAGE_MAX_SIZE = 2**20` is inbound WebSocket frame limit only
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/websocket.py` — `MESSAGE_MAX_SIZE = 2 ** 20`, outbound frame handling in `_send_frame()`, rate limiting config
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/views/pos_assets_index.xml` — `loadMenusPromise = Promise.resolve()` pattern, `__session_info__` embedding, CSRF token inclusion
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/controllers/main.py` — `session_info()` call, `is_internal_user` check, `Cache-Control: no-store`
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/__manifest__.py` — `point_of_sale.base_app` bundle including bus services explicitly
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/point_of_sale/static/src/app/main.js` — `mountComponent` pattern for standalone OWL app boot
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/env.js` — `mountComponent`, `startServices`, `makeEnv` implementation
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/controllers/home.py` — `web_client` route, `auth="none"` with manual UID check, `session_info` rendering
- Direct source inspection: `/Users/joseph/clones/odoo/odoo/.worktrees/master/odoo/addons/base/models/ir_module.py` — `module_uninstall` does NOT drop tables, only removes `ir_model_data` entries
- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/models/ai_session.py` — current v1.0 instrumentation, separate cursor pattern for bus sends
- Direct source inspection: `/Users/joseph/clones/odoo/custom/ai_debug/models/ir_websocket.py` — existing `_build_bus_channel_list` override with `group_system` check (should be `group_user` for v1.1)
- Direct source inspection: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/spreadsheet_edition/models/ir_websocket.py` — reference implementation of `_build_bus_channel_list` with access check pattern

---
*Pitfalls research for: Odoo AI Debugger v1.1 — standalone OWL app + bus.bus streaming migration*
*Researched: 2026-02-20*
