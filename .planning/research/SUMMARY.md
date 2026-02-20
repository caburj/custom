# Project Research Summary

**Project:** AI Debugger v1.1 — Standalone OWL App at /ai-debug
**Domain:** Odoo custom module — live agentic loop tracer, DB-backed to ephemeral migration
**Researched:** 2026-02-20
**Confidence:** HIGH (all patterns verified against Odoo master source code at `/Users/joseph/clones/odoo/`)

## Executive Summary

AI Debugger v1.1 is a targeted refactor of a working v1.0 developer tool. The migration replaces three things: a DB-backed backend client action panel becomes a true standalone OWL app at `/ai-debug` (own HTML page, own asset bundle, own HTTP controller — the POS self-order pattern); lazy ORM-on-click trace data loading becomes full payloads embedded in bus.bus events; and a flat timeline view becomes a 3-level sidebar tree (Loop > Iteration > Tool Call) with a master/detail right panel. The technical patterns are all well-documented in Odoo master source — the primary reference is `pos_self_order` for the standalone app scaffold and the existing v1.0 `ai_session.py` for the bus send mechanics.

The recommended approach is to treat this as a migration with four sequential work blocks: (1) infrastructure — delete DB models with a proper migration script, scaffold the standalone app so `/ai-debug` loads, fix the bus channel access group from `group_system` to `group_user`; (2) backend instrumentation — rewrite the agentic loop instrumentation to emit full payloads over bus.bus using a separate cursor per send; (3) sidebar tree component — implement the 3-level OWL component tree with reactive Map-based state in the root component; (4) detail panel — wire the type-aware detail panel using existing `JsonTree` and `StateDiff` components. The dependency chain is strict: Phase 3 cannot start until Phase 2's bus payloads are verified in the browser, and Phase 4 cannot start until Phase 3's selection state is stable.

The key risk is payload size. The PITFALLS research identifies that sending full LLM conversation history (50-500 KB) in a single bus event causes main-thread jank via SharedWorker `postMessage` and risks browser WebSocket close code 1009. The mitigation is to cap payloads at approximately 32 KB and split large iteration data into meta (always sent) and detail (sent separately or fetched on demand). A secondary risk is the DB model removal: Odoo does not drop tables on module uninstall, so orphaned tables require an explicit `pre-migrate.py` with `DROP TABLE IF EXISTS ... CASCADE`. Both risks are well-understood and have clear prevention strategies documented in PITFALLS.md.

## Key Findings

### Recommended Stack

All v1.1 stack additions follow the POS self-order pattern, verified against Odoo master source. The standalone app is served by an HTTP controller (`auth='user'`) that renders a QWeb HTML template injecting `odoo.__session_info__` and `csrf_token` as a JS global, then loads a dedicated asset bundle via `t-call-assets="ai_debug.assets_app"`. The bundle uses `('include', 'point_of_sale.base_app')` to pull in OWL, `@web/_assets_core`, Bootstrap SCSS, and all bus service files — this is the correct and minimal dependency graph for a standalone OWL app that uses `bus_service`. The app is booted via `whenReady(() => mountComponent(AiDebugApp, document.body))`. `mountComponent` from `@web/env` (not bare `mount` from `@odoo/owl`) is mandatory because it calls `makeEnv()` and `startServices(env)`, bootstrapping the full service registry including `bus_service`.

**Core technologies:**
- `mountComponent` from `@web/env`: Bootstrap standalone OWL app — starts all registered services automatically; required for `bus_service` access; mirrors `pos_self_order/static/src/app/root.js`
- `ai_debug.assets_app` (dedicated bundle): Isolates standalone app from backend; `('include', 'point_of_sale.base_app')` provides OWL + bus + web core without pulling in the full webclient
- HTTP controller (`type='http'`, `auth='user'`): Serves `/ai-debug` with session info injection and internal-user gate; mirrors `PosController.pos_web()` exactly
- QWeb HTML template (`ai_debug.index`): Full `<!DOCTYPE html>` document with `odoo` JS global and empty `<body>`; no Odoo navbar chrome
- `bus_service.addChannel()` + `subscribe()`: Receives full-payload events; auto-starts WebSocket connection; must be called in `onMounted`, not `setup()`
- `uuid.uuid4()` for all IDs: No DB autoincrement available; UUIDs are collision-free and make payloads self-describing
- Separate `registry.cursor()` per bus send: Required for real-time per-iteration delivery — main cursor defers all notifications until HTTP request end

See `.planning/research/STACK.md` for verified code examples and source references.

### Expected Features

v1.0's timeline model gave developers a flat, per-iteration view requiring explicit "expand" clicks to load data from the DB. v1.1's sidebar tree model follows the canonical live-tracer UX established by VS Code debugger, LangSmith, Langfuse, and Jaeger: a persistent left sidebar drives a right detail panel. The UX research is decisive — the tree model is the expert pattern for this domain and no external tracer surveyed used a flat timeline as its primary view.

**Must have (table stakes):**
- Sidebar tree with 3-level hierarchy (Loop > Iteration > Tool Call) — the canonical live-tracer structure; every comparable tool organizes data as a tree
- Click-to-select drives detail panel — the entire value proposition of the master/detail layout
- Status badge inline with each tree node (running/done/error/paused) — live state at a glance without opening detail
- Full bus.bus payloads — iteration events carry `messages_sent`, `raw_response`; tool call events carry `args`, `result`, `state_before`, `state_after`; all fields needed for the detail panel must arrive in the bus event
- Loops-array state model (`state.traces` Map) — replaces single-trace state; each loop has nested iterations and tool calls
- Agent name as loop label — `ai.agent.name` from the bus payload, Odoo-specific context not available in any external tracer
- Auto-select latest running node — follows live execution unless user has manually selected a node
- Multiple loops as top-level sidebar roots — correctness for sequential and concurrent agentic runs
- `parent_loop_id` in loop data model (null in v1.1) — subagent-ready without implementation cost; field must be in the schema from day one
- Ephemeral session-scoped data — refresh clears all; no DB persistence; explicit design choice

**Should have (competitive advantage):**
- Iteration timing display (`duration_ms` inline on each tree node) — immediate "which call was slow" signal without opening detail
- Keyboard navigation (W3C ARIA tree pattern, arrow keys) — matches VS Code and DevTools behavior developers already know
- Confirmation pause badge (distinct from running/done/error) — Odoo-specific two-phase confirmation pattern that no external tracer has
- Connection status indicator — carry forward from v1.0; developers watching a live trace must know WebSocket state

**Defer (v2+):**
- Database persistence of traces — session-scoped is the explicit v1.1 design
- Search/filter within sidebar — bounded tree depth makes this low-priority; Ctrl+F browser search covers the common case
- Trace export (OTLP / JSON) — deferred per PROJECT.md
- Replay / re-run with modified messages — requires session lifecycle integration; significant scope

See `.planning/research/FEATURES.md` for the full prioritization matrix, dependency graph, and competitor comparison table.

### Architecture Approach

The v1.1 architecture cleanly separates concerns into four layers: instrumentation (Python generator wrapping, unchanged from v1.0), notification (bus.bus with full payloads and separate cursors for real-time delivery), HTTP/template (new standalone page controller mirroring POS self-order), and OWL app (root component owns all state and bus subscriptions; sidebar and detail panel are purely presentational). State lives in a single `useState` object in the root component using `Map` for O(1) lookup by UUID — there is one entity type (traces) and four event handlers, so no Vuex-style store service is warranted. OWL's reactive `Map` (confirmed in OWL source) triggers re-renders on `.set()` mutations, making it the right collection type for live append-only data.

**Major components:**
1. `AiDebugController` + `ai_debug.index` template — serves the page at `/ai-debug`; injects session info and CSRF token; no Odoo navbar chrome
2. `ai_debug.assets_app` bundle — self-contained; includes all required services via `point_of_sale.base_app`; `main.js` is added last via remove/re-add pattern
3. `AiDebugApp` (root) — owns `useState({ traces: Map, selection, connectionStatus })`; subscribes to 4 bus event types in `onMounted`; handles auto-selection of new traces
4. `TraceList` (sidebar) — purely presentational; receives `traces` Map and `setSelection` callback; renders 3-level hierarchy with `t-key` on all node types
5. `DetailPanel` (right pane) — receives `selectedNode`; switches between `LoopDetail`, `IterationDetail`, `ToolCallDetail` via `t-if`/`t-elif`
6. `JsonTree` + `StateDiff` — carry over from v1.0 unchanged; slot directly into detail sub-components with no modification needed

**Data flow:** Python yield boundary -> `_debug_send_event()` with separate cursor -> `bus.bus._sendone()` commits immediately -> pg_notify -> Odoo WebSocket dispatcher -> browser SharedWorker -> `bus_service.subscribe()` callback -> `AiDebugApp` mutates `state.traces` Map -> OWL reactive re-render -> sidebar tree grows and detail panel updates.

See `.planning/research/ARCHITECTURE.md` for full component code examples, build order, and anti-patterns.

### Critical Pitfalls

1. **Wrong asset bundle / missing services** — If `ai_debug.assets_app` does not include bus service files (via `point_of_sale.base_app`), `useService('bus_service')` throws on startup with `Cannot find service 'bus_service'`. Never add standalone app files to `web.assets_backend` — that bundle is invisible to the standalone HTML page. Prevention: use `('include', 'point_of_sale.base_app')` and verify that navigating to `/ai-debug` shows the app (not a blank page with console errors) before proceeding.

2. **Missing `session_info` in controller context** — Without `odoo.__session_info__` embedded in the standalone HTML, the bus WebSocket handshake fails with session expired (WebSocket close code 4001). `session.uid` will be undefined. Prevention: call `request.env['ir.http'].session_info()` in the controller, embed in the template JS global, add `Cache-Control: no-store`.

3. **Orphaned DB tables after model deletion** — Odoo does not drop tables on module uninstall — it removes `ir.model` records only. Removing the three model files leaves `ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call` tables in PostgreSQL forever. Prevention: write `migrations/<version>/pre-migrate.py` with `DROP TABLE IF EXISTS ... CASCADE` before shipping the v1.1 upgrade.

4. **Oversized bus payloads causing jank and WebSocket close 1009** — Full LLM conversation history (50-500 KB) in a single bus event blocks the main thread via SharedWorker `postMessage` (20-100 ms per iteration) and can trigger browser WebSocket close 1009. The 8 KB `NOTIFY_PAYLOAD_MAX_LENGTH` is a common misread — it applies to the pg_notify channel list, not message content. Prevention: cap payloads at approximately 32 KB; split into meta (index, duration, tool count) and detail (messages_sent, raw_response).

5. **Bus events batching instead of streaming** — Calling `bus.bus._sendone()` on the main cursor (`self.env.cr`) means all notifications fire at HTTP request end, not at each yield boundary. Prevention: always use `with self.env.registry.cursor() as cr:` for each bus send; the cursor commits immediately and triggers pg_notify per iteration.

6. **Access group wrong (`group_system` not `group_user`)** — The existing `ir_websocket.py` override restricts `ai_debug:*` channels to `base.group_system`. The v1.1 requirement is any internal user (`base.group_user`). Must be corrected in Phase 1 atomically with any channel naming changes.

7. **Sidebar loses selection on every bus event** — Without stable `t-key` on tree nodes and in-place mutation (`.push()` not array replacement), OWL unmounts all nodes on each bus event, resetting selected/expanded state. Prevention: `t-key="loop.id"`, `t-key="iter.id"`, `t-key="tc.id"`; use `Map.set()` for O(1) mutation; never assign `state.traces = newMap`.

See `.planning/research/PITFALLS.md` for the full checklist including security mistakes, UX pitfalls, performance traps, and the "Looks Done But Isn't" verification checklist.

---

## Implications for Roadmap

Based on the strict dependency chain identified across all four research files, four phases are the right structure. The ordering is non-negotiable: Phase 2 cannot start until Phase 1's `/ai-debug` route resolves cleanly and the DB migration is verified; Phase 3 cannot start until Phase 2's bus payloads are confirmed arriving in the browser; Phase 4 cannot start until Phase 3's selection state is stable under concurrent bus events.

### Phase 1: Infrastructure — DB Migration + Standalone App Scaffold

**Rationale:** Everything downstream depends on two things: (a) the old DB models being cleanly removed without orphaned tables or broken references in `ai_session.py`, and (b) `/ai-debug` returning a working HTML page that boots an OWL app and connects `bus_service`. Both are blocking foundations with no other dependencies. They can be worked in parallel within Phase 1 but must both be complete and verified before Phase 2 begins.

**Delivers:** A navigable `/ai-debug` URL that mounts a stub `AiDebugApp`, connects to `bus_service`, logs received events to the browser console, and leaves no trace of the old DB models in the database or codebase. The `ir_websocket.py` access group is corrected to `group_user`.

**Addresses:** Ephemeral session-scoped data (table stakes), connection status indicator (carry forward).

**Avoids:** Pitfalls 1 (wrong bundle), 2 (missing session_info), 3 (orphaned DB tables), 6 (wrong access group), and the generator-references-deleted-model failure mode.

**Key tasks:**
- Write `migrations/<version>/pre-migrate.py` with `DROP TABLE IF EXISTS ... CASCADE` for all three tables
- Remove `ai_debug_trace.py`, `ai_debug_iteration.py`, `ai_debug_tool_call.py` and `security/ir.model.access.csv`
- Stub out DB write calls in `ai_session.py` (replace with `pass` temporarily; do not delete the bus send path)
- Add `controllers/main.py` with `AiDebugController.ai_debug_index()` following the POS self-order pattern
- Add `views/templates.xml` with `ai_debug.index` QWeb template (includes session_info, csrf_token, `loadMenusPromise = Promise.resolve({})`)
- Add `ai_debug.assets_app` bundle to `__manifest__.py` using `('include', 'point_of_sale.base_app')`
- Add stub `main.js`, `ai_debug_app.js`, `ai_debug_app.xml` (mounts, logs "AI Debug loaded", subscribes to bus channel)
- Update `ir_websocket.py`: change `group_system` to `group_user`; verify channel prefix still matches `ai_debug:`
- Remove old backend views, menus, and their `__manifest__.py` data references

### Phase 2: Backend Instrumentation — Full Bus Payloads

**Rationale:** The frontend cannot display meaningful data until the backend emits correctly structured, complete bus payloads. The bus event schema (UUID IDs, `parent_loop_id` field, payload size discipline) must be locked before the frontend state model is built — changing the schema after Phase 3 requires synchronized changes to both Python and JavaScript. The payload split decision (meta-only vs. capped full payload) must also be made here, before any frontend code depends on a particular shape.

**Delivers:** A running agentic loop that emits 4 well-structured bus events (`ai_debug/new_trace`, `ai_debug/iteration`, `ai_debug/tool_call`, `ai_debug/trace_update`) with verified payloads, confirmed arriving one-by-one in the browser console during loop execution. Payload size discipline enforced.

**Addresses:** Full bus.bus payloads (table stakes), agent name label, iteration timing data, confirmation pause state signal, `parent_loop_id` in schema.

**Avoids:** Pitfalls 4 (oversized payloads), 5 (batch-fire instead of streaming), 8 (subagent events arrive with unknown parent), 11 (bus_bus disk accumulation).

**Key tasks:**
- Finalize bus event schema for all 4 event types (include `parent_loop_id: null`, `agent_name`, UUID IDs, `state` field on loop)
- Decide and implement payload split strategy: recommended is `ai_debug/iteration_meta` (index, duration, tool_count — tiny) plus either a capped `messages_sent`/`raw_response` or a separate `ai_debug/iteration_detail` event
- Rewrite `ai_session.py` instrumentation: replace stubbed DB write calls with `_debug_send_event()` using a separate cursor per send
- Carry forward `_debug_strip_binaries()` for multimodal content in `messages_sent`
- Verify real-time delivery: trigger agentic loop, confirm events arrive one-by-one in browser console during execution
- Verify payload size: `SELECT max(length(message)) FROM bus_bus WHERE channel LIKE '%ai_debug%'` must return < 65536 after a RAG-enabled session

### Phase 3: Sidebar Tree Component

**Rationale:** The sidebar is the primary UX deliverable of v1.1. It depends entirely on Phase 2's proven bus payloads. The OWL reactive Map state model and the 3-level component tree are the structural core — everything in Phase 4 (detail panel) slots into the selection state established here. Selection stability (stable `t-key`, `Map.set()` not array replacement) must be confirmed under live bus events before Phase 4 is added.

**Delivers:** A working sidebar that populates in real time as bus events arrive, with Loop > Iteration > Tool Call hierarchy, inline status badges, agent name labels, timing display, and stable selection state under concurrent bus updates. Multiple concurrent loops appear as siblings.

**Addresses:** Sidebar tree (table stakes), click-to-select state (table stakes), status badges, auto-select latest running node, multiple loops as top-level roots, timing display on iteration nodes, `parent_loop_id` tree rendering logic.

**Avoids:** Pitfalls 7 (sidebar loses selection on bus events), 8 (subagent events with unknown parent loop).

**Key tasks:**
- Implement `AiDebugApp` root component with `useState({ traces: Map, selection, connectionStatus })`; include `loopsById` index for O(1) lookup and subagent-ready parent/child insertion
- Wire 4 bus event handlers (`_onNewTrace`, `_onIteration`, `_onToolCall`, `_onTraceUpdate`) in `onMounted`
- Implement `TraceList` + `LoopItem` + `IterationItem` + `ToolCallItem` OWL components; all use `setSelection` callback upward (no EventBus)
- Add `t-key` on all `t-foreach` nodes (loop.id, iter.id, tc.id)
- Add status badge CSS classes (running spinner, done checkmark, error X, paused indicator)
- Add `formatDuration(ms)` inline display on `IterationItem` nodes
- Verify stability: click iteration #1 detail, trigger new tool call via a second agentic run, confirm iteration #1 remains selected and detail does not blank

### Phase 4: Detail Panel + Polish

**Rationale:** The detail panel is the payoff for sidebar selection. It reuses existing `JsonTree` and `StateDiff` components from v1.0 — implementation cost is low once Phase 3's selection state is stable. Polish items (keyboard navigation, connection status, listening state copy) complete the v1.1 feature set with no new architectural dependencies.

**Delivers:** A fully working AI Debugger v1.1 where clicking any sidebar node shows type-appropriate detail content, with keyboard navigation, connection status display, and listen mode (auto-attach to next incoming loop).

**Addresses:** Detail panel type-aware tabs, `JsonTree` and `StateDiff` integration, keyboard navigation, connection status carry-forward, confirmation pause badge visual, listen mode preservation.

**Avoids:** UX pitfalls — sidebar collapses on reconnect (sessionStorage restore), no visual distinction for running loops, no timeout indicator in listening state.

**Key tasks:**
- Implement `DetailPanel` switcher with `t-if`/`t-elif` on selected node type (loop / iteration / tool_call)
- Implement `LoopDetail` (System Prompt / RAG Context / Tools tabs using `JsonTree`)
- Implement `IterationDetail` (Messages Sent / LLM Response / State Diff tabs using `JsonTree` and `StateDiff`)
- Implement `ToolCallDetail` (Args / Result / State Diff tabs)
- Port `JsonTree` and `StateDiff` from `static/src/debug_panel/` to `static/src/app/components/`; no source changes expected
- Add keyboard navigation (W3C ARIA tree pattern: Down/Up Arrow moves selection, Right/Left Arrow expands/collapses)
- Add connection status indicator (carry forward `_syncConnectionStatus` logic from v1.0)
- Add confirmation pause badge distinct from running/done/error
- Add "Listening for next session... (Xs elapsed)" copy in the empty state
- Final cleanup: delete all v1.0-only source files; verify module upgrades cleanly from a fresh database

### Phase Ordering Rationale

- Phase 1 before Phase 2: The standalone app must resolve at `/ai-debug` before the browser can receive bus events. DB cleanup must happen before instrumentation is rewritten to avoid `KeyError: 'ai.debug.trace'` at runtime.
- Phase 2 before Phase 3: The sidebar component cannot be verified without real bus events arriving. The event schema (payload shape, UUID keys, `parent_loop_id`) must be locked before the frontend state model is built against it.
- Phase 3 before Phase 4: The `DetailPanel` reads `state.selection` — that selection state object is established in Phase 3. The `selectedNode` getter and component tree topology must exist before detail panel rendering is meaningful.
- No phase should be merged without passing the PITFALLS.md "Looks Done But Isn't" verification checklist.

### Research Flags

Phases with standard, well-documented patterns (skip `/gsd:research-phase`):
- **Phase 1 (Scaffold):** Every pattern is verified against Odoo master source at specific file paths. The controller, template, and bundle structure are direct adaptations of `pos_self_order` — no unknowns.
- **Phase 4 (Detail Panel):** `JsonTree` and `StateDiff` are already written and working. The detail panel is a type-switch with existing components — standard OWL component composition.

Phases that would benefit from a targeted spike before task breakdown:
- **Phase 2 (Bus Payload Size Decision):** The meta/detail payload split strategy has two viable options (split events vs. single capped payload). The right choice depends on actual production payload sizes. A quick empirical check — instrument `len(json.dumps(payload))` in a test session with RAG enabled — would resolve this in 30 minutes and prevent a costly refactor later.
- **Phase 3 (OWL Map Reactivity Proof-of-Concept):** OWL's reactive `Map` behavior (`.set()` triggers re-render, `[...map.values()]` in template spreads reactively) is confirmed in OWL source comments but is an uncommon pattern. A 30-minute standalone OWL proof-of-concept with a Map in `useState` would confirm the pattern before the full sidebar is built on it.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All patterns verified against Odoo master source at specific file paths and line numbers. No inference from documentation alone — direct source reads of `pos_self_order`, `bus_service.js`, `env.js`, `bus.py`. |
| Features | HIGH | Table stakes features derived from direct comparison with VS Code debugger, LangSmith, Langfuse, and Jaeger (official documentation). Odoo-specific features (confirmation pause, agent name label, ephemeral design) derived from direct v1.0 code review and PROJECT.md requirements. |
| Architecture | HIGH | Component decomposition mirrors the verified POS self-order architecture. OWL reactive Map confirmed in OWL source. Data flow matches existing v1.0 bus send mechanics (separate cursor pattern already proven in production). |
| Pitfalls | HIGH | Each pitfall includes the exact source file, mechanism, and verified fix. Not inferred — all confirmed by reading `bus.py`, `websocket.py`, `ir_module.py`, `pos_assets_index.xml`, and the existing v1.0 module source. |

**Overall confidence:** HIGH

### Gaps to Address

- **Payload size empirical baseline:** The research recommends capping at approximately 32 KB but does not have production data on typical Odoo AI session payload sizes. Before finalizing the Phase 2 payload split strategy, run a test session with RAG enabled and measure `SELECT max(length(message)) FROM bus_bus WHERE channel LIKE '%ai_debug%'`. If payloads are consistently under 32 KB, the split adds unnecessary complexity; if they routinely exceed it, the split is mandatory.

- **`loadMenusPromise` requirement with `base_app` bundle:** STACK.md recommends `point_of_sale.base_app` and notes the bundle does not include menu services. PITFALLS.md notes POS adds `loadMenusPromise = Promise.resolve()` as a guard. During Phase 1 scaffold, verify whether the `base_app` bundle includes anything that triggers menu loading — if not, the guard is unnecessary; if yes, it must be added to the template. This is a 5-minute check.

- **`bus_service.unsubscribe()` API availability:** The architecture uses `unsubscribe()` in `onWillUnmount`. Verify this method exists in the current `bus_service.js` at the time of Phase 3 implementation. The v1.0 panel did not use it, and the API may have been added recently. If the method is absent, use the named-handler pattern with `addChannel`/`deleteChannel` alone.

---

## Sources

### Primary (HIGH confidence — direct Odoo master source inspection)

- `addons/point_of_sale/controllers/main.py` — HTTP controller pattern, `session_info()`, `_is_internal()`, `Cache-Control: no-store`
- `addons/point_of_sale/views/pos_assets_index.xml` — standalone HTML template, `odoo` JS global, `__session_info__`, `loadMenusPromise`
- `addons/point_of_sale/__manifest__.py` — `point_of_sale.base_app` bundle, bus service file list, `main.js` remove+re-add pattern
- `addons/point_of_sale/static/src/app/main.js` — `mountComponent(Chrome, document.body)` boot pattern
- `addons/pos_self_order/views/pos_self_order.index.xml` — minimal standalone template without POS session complexity
- `addons/pos_self_order/static/src/app/root.js` — cleanest `whenReady(async () => { await mountComponent(...) })` example
- `addons/pos_self_order/__manifest__.py` — `('include', 'point_of_sale.base_app')` in custom bundle
- `addons/web/static/src/env.js` — `mountComponent`, `makeEnv`, `startServices` implementations (lines 226-250)
- `addons/bus/models/bus.py` — `_sendone` precommit/postcommit; `NOTIFY_PAYLOAD_MAX_LENGTH` applies to pg_notify channel list only, not message content; messages fetched from `bus_bus` table by ID
- `addons/bus/static/src/services/bus_service.js` — `addChannel()` calls `ensureWorkerStarted()` and `BUS:START` (lines 174-181)
- `addons/bus/websocket.py` — `MESSAGE_MAX_SIZE = 2**20` is inbound frame limit only; outbound frames have no server-side size check
- `odoo/addons/base/models/ir_module.py` — `module_uninstall` removes `ir_model_data` entries but does NOT drop PostgreSQL tables
- `ai_debug/models/ai_session.py` (v1.0) — existing instrumentation, separate cursor pattern, `_debug_strip_binaries`
- `ai_debug/models/ir_websocket.py` (v1.0) — existing `_build_bus_channel_list` override with `group_system` check (must change to `group_user`)
- `enterprise/spreadsheet_edition/models/ir_websocket.py` — reference implementation of `_build_bus_channel_list` with access check pattern

### Secondary (MEDIUM confidence — official documentation and changelogs)

- [Langfuse Tracing Data Model](https://langfuse.com/docs/observability/data-model) — observation tree pattern, `parent_observation_id` for nested traces
- [Langfuse New Trace View changelog 2025-03-19](https://langfuse.com/changelog/2025-03-19-new-trace-view) — tree/timeline toggle UX, right-side detail pane design
- [LangSmith Debugging Deep Agents](https://blog.langchain.com/debugging-deep-agents-with-langsmith/) — run tree, status badges, input/output tabs
- [VS Code Debugger Documentation](https://code.visualstudio.com/docs/debugtest/debugging) — call stack tree, multi-session sidebar behavior
- [W3C ARIA TreeView Pattern](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/) — keyboard navigation specification (Down/Up/Left/Right arrow behavior)
- [PatternFly Primary-detail pattern](https://www.patternfly.org/patterns/primary-detail/design-guidelines/) — master/detail layout design guidelines

### Tertiary (LOW confidence — inferred from architecture, needs runtime validation)

- OWL `Map` inside `useState` reactivity on `.set()` — confirmed in OWL source comments and mentioned in OWL documentation but no dedicated test coverage found; validate with a Phase 3 proof-of-concept before committing the full sidebar to this pattern
- `bus_service.unsubscribe()` availability — referenced in STACK.md research reasoning but not line-verified in current `bus_service.js` source; confirm during Phase 3 implementation

---
*Research completed: 2026-02-20*
*Ready for roadmap: yes*
