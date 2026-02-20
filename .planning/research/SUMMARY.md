# Project Research Summary

**Project:** AI Debugger — Custom Odoo module for agentic loop instrumentation
**Domain:** Odoo-native LLM observability and developer tooling
**Researched:** 2026-02-20
**Confidence:** HIGH

## Executive Summary

The AI Debugger is a custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide real-time visibility into each LLM call, tool execution, and loop termination — all within the Odoo ORM and frontend stack with no external infrastructure. The module is implemented through three clean layers: a generator yield passthrough that wraps `ai.session._run_agentic_loop()` via `_inherit`, persistent ORM models (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) that capture every event, and an OWL panel delivered via `ir.actions.client` that shows the loop running live using `bus.bus` WebSocket notifications. All patterns are verified against Odoo master source code. No external libraries, no monkey-patching, no custom HTTP endpoints.

The recommended build order follows component dependencies: data models first, then the `ai.session` instrumentation override, then backend XML views (immediately useful for verifying captured data), then the real-time OWL panel with bus integration, and finally polish (JSON tree viewer, state diff, configuration UI). This order allows incremental verification at each phase and avoids building a UI before the underlying data model is confirmed correct. The existing `ai` module already shows every bus pattern needed; this module is principally a consumer and observer, not a producer of novel infrastructure.

The primary risks are behavioral — not architectural. The generator wrapping must preserve streaming semantics or it breaks the confirmation flow silently. Bus channel design must use per-trace channels rather than user-partner channels, or every open browser tab receives debug payloads. JSON payloads must not be sent over the bus directly; only a reference should be sent, with the frontend fetching detail on demand. These risks are well-defined and avoidable with established patterns from `spreadsheet_edition`, `im_livechat`, `hr_attendance`, and `google_calendar` in the Odoo codebase.

## Key Findings

### Recommended Stack

All stack choices are Odoo-native and verified against master source. There are no npm installs, no external Python packages, and no custom websocket servers needed.

**Core technologies:**
- **Python ORM (`models.Model`, `_inherit`):** Generator yield passthrough for instrumentation; persistent models for debug data. The only Odoo-idiomatic way to wrap generator methods without breaking the caller.
- **OWL 2.8.1 (bundled):** Live debug panel as an `ir.actions.client` component. Imports from `@odoo/owl` and `@web/core/*` — no npm install needed.
- **`bus.bus` / `bus_service`:** Real-time push from backend to frontend via `env['bus.bus']._sendone()` + `bus_service.subscribe()`. Use a per-trace channel (not user-partner) to avoid fan-out to all tabs.
- **`ir.websocket._build_bus_channel_list`:** Override to authorize per-trace bus channels. Must include an access check — follow the `spreadsheet_edition` pattern exactly.
- **`ir.config_parameter` + `@api.autovacuum`:** Enable/disable switch and auto-vacuuming of old trace records. Both are stable, lightweight Odoo patterns.

**Critical version constraints:**
- `bus_service.subscribe()` / `bus_service.start()` — Odoo 16+ (master) API. Older `addEventListener` pattern is not current.
- `registry.category("actions").add(tag, Component)` — OWL 2 client action registration (Odoo 16+).

See `.planning/research/STACK.md` for verified import paths and code examples.

### Expected Features

LangSmith, Langfuse, Arize Phoenix, and Braintrust define the domain expectations. This module translates those patterns to Odoo-native, adding two unique differentiators: live real-time streaming (none of the external tools show the loop mid-execution) and confirmation-flow tracking (unique to Odoo's two-phase tool confirmation pattern).

**Must have (table stakes):**
- Trace capture (`ai.debug.trace`) — one record per agentic loop run
- Iteration records (`ai.debug.iteration`) — one per LLM call, with full messages sent and raw response
- Tool call records (`ai.debug.tool.call`) — per-execution with args, result, success, timing
- Enable/disable config param — must exist before any data is captured in any environment
- Trace retention / auto-cleanup — configurable TTL; required before first real deployment
- Backend list + form views — searchable trace history for post-mortem inspection
- Error surfacing — `state = 'error'` with exception message visible without reading server logs

**Should have (differentiators):**
- Live real-time debug panel — the core development-time value proposition; no equivalent in any Odoo-native tool
- State diff viewer — shows exactly what changed in `tools_context['state']` between iterations
- JSON tree renderer — collapsible, syntax-highlighted inline viewer for messages and raw responses
- System prompt + RAG context capture — hook into `_generate_next_response()` in addition to `_run_agentic_loop()`
- Confirmation flow tracking — explicit capture of which tool triggered a pause and the pending call ID

**Defer (v2+):**
- Prompt replay / re-run — significant scope; requires safe re-execution flow
- OTLP / OpenTelemetry export — only useful if the module outlives local development
- Evaluation / scoring — a separate product category (LLM-as-judge pipeline)

See `.planning/research/FEATURES.md` for the full prioritization matrix and competitor analysis.

### Architecture Approach

The module has three layers connected by two clean interfaces: the generator yield passthrough writes to ORM models and schedules bus sends; the OWL panel subscribes to per-trace bus channels and renders state reactively. The architecture is intentionally read-only at the instrumentation level — the inherited methods observe and re-yield without modifying any yielded item.

**Major components:**
1. **`AiSessionDebug` (`_inherit = 'ai.session'`)** — wraps `_run_agentic_loop()` and `_handle_tool_calls()` generators; writes to debug models; schedules bus sends via `postcommit` hook with a separate cursor
2. **Persistent debug models** (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) — the trace hierarchy; all `models.Model` (not TransientModel) to survive session cleanup
3. **`IrWebsocket` (`_inherit = 'ir.websocket'`)** — adds per-trace channels to the bus subscription list with access validation
4. **`DebugPanel` (OWL `ir.actions.client`)** — subscribes to the trace-scoped channel on mount; renders iterations and tool calls as they arrive; unsubscribes on unmount
5. **Backend XML views** — standard list/form views for `ai.debug.trace`; no custom frontend code; useful from day one

The most architecturally subtle point is the bus notification timing: `_sendone()` fires via `postcommit` on the outer `thoughts_generator` cursor, meaning all notifications would arrive at the end of the loop if sent directly. Real-time (per-iteration) notifications require a separate `registry.cursor()` inside a `postcommit` hook, following the `google_calendar` sync pattern.

See `.planning/research/ARCHITECTURE.md` for the full data flow diagrams and build-order analysis.

### Critical Pitfalls

1. **Generator wrapping that collapses streaming** — calling `list(super()._run_agentic_loop(...))` destroys streaming and silently breaks the tool confirmation flow (`pending_tool_call_id` is never set). Always use `for item in super()...: yield item` with `try/except` around capture logic so instrumentation errors never surface to the user.

2. **Bus notifications sent over the user-partner channel** — `env.user._bus_send()` delivers to all browser tabs for that user, including unrelated production workflows. Use a per-trace channel (`ai_debugger_{trace_uuid}`) and override `ir.websocket._build_bus_channel_list` with an access check. Never use sequential integer IDs as channel names (enumerable); use UUIDs.

3. **Full JSON payloads in bus notifications** — `bus.bus` truncates payloads above 8 KB (`NOTIFY_PAYLOAD_MAX_LENGTH`). Sending a full LLM response (potentially 50-200 KB) will be silently truncated. Send only `{trace_id, event_type, iteration_idx}` via bus; have the frontend fetch full payload via RPC on demand.

4. **`TransientModel` vacuumed mid-session** — `ai.session` records are cleaned up by Odoo's autovacuum cron. An instrumented generator can be suspended at a `yield` boundary when the vacuum runs, causing `MissingError` on the next iteration. Never hold `self` (the session recordset) across yield boundaries; copy `session_id = self.id` before the first yield.

5. **Missing `onWillUnmount` unsubscribe in OWL** — `bus_service.subscribe()` does not auto-cleanup on component destruction. Store the callback as `this.handleEvent` (not an inline arrow function) and call `bus_service.unsubscribe(type, this.handleEvent)` in `onWillUnmount`. Same reference must be used for both calls.

6. **`_build_bus_channel_list` without access check** — any authenticated user knowing the channel name can subscribe and receive full debug payloads (which contain LLM prompts, tool args, and internal state). Follow `spreadsheet_edition/models/ir_websocket.py` exactly: parse the channel string, resolve the trace record, call `has_access('read')`, reject if it fails.

See `.planning/research/PITFALLS.md` for the full checklist including the `_handle_tool_calls` early-return trap and SQL index requirements.

## Implications for Roadmap

### Phase 1: Data Models and Generator Instrumentation

**Rationale:** Trace capture is the root dependency for everything else — views, live panel, state diff. The generator instrumentation is the highest-risk component (behavioral correctness) and must be proven correct before adding UI. This phase has no frontend dependencies.

**Delivers:** A working instrumentation layer that captures traces, iterations, and tool calls to persistent ORM models. Verifiable via Odoo shell queries or the Phase 2 views.

**Addresses:** All P1 table-stakes features (trace capture, iteration records, tool call records, enable/disable switch, error surfacing, auto-cleanup).

**Avoids:** Generator yield contract breakage (Pitfall 1), TransientModel vacuum mid-session (Pitfall 5), large JSON in model fields (Pitfall 4 — design fields conservatively from the start).

**Research flag:** Standard pattern. No additional research needed. The generator override pattern is fully documented in STACK.md and ARCHITECTURE.md with verified source examples.

### Phase 2: Backend Views and Security

**Rationale:** Backend XML views have zero JS dependencies and can be built immediately after models exist. They provide the first real verification that captured data looks correct. Security (ir.model.access.csv) is a prerequisite for any view to load.

**Delivers:** A searchable, filterable history of all debug traces visible in the Odoo backend. Usable for post-mortem debugging without any live panel work.

**Addresses:** Backend list + form views feature, trace retention UI (via Settings), per-agent filter (trivial search filter).

**Avoids:** No significant pitfall exposure in this phase. Standard Odoo XML view patterns.

**Research flag:** Skip. Fully standard Odoo views — well-documented patterns.

### Phase 3: Bus Integration and Live Panel

**Rationale:** The live debug panel is the core differentiator but depends on both the data model (Phase 1) and confidence that the captured data is correct (Phase 2 validation). Bus channel design is the most security-sensitive part of the module and must be done carefully.

**Delivers:** A real-time OWL panel showing the agentic loop as it runs — iterations and tool calls appearing one by one as the backend yields them.

**Uses:** `ir.websocket._build_bus_channel_list` override with UUID channel names and access checks. `bus_service.addChannel()` + `bus_service.subscribe()` in OWL with full lifecycle management. Separate `registry.cursor()` in a `postcommit` hook for per-iteration bus sends.

**Implements:** `DebugPanel` OWL component, `IrWebsocket` override, bus notification sender.

**Avoids:** Fan-out to all tabs via user-partner channel (Pitfall 3), full payloads in bus (Pitfall 4 — send reference only), missing OWL unsubscribe (Pitfall 7), channel without access check (Pitfall 6).

**Research flag:** Needs careful implementation. The separate cursor / postcommit pattern is documented in ARCHITECTURE.md but subtle. Recommend tracing through the `thoughts_generator` execution model during task breakdown to confirm notification timing.

### Phase 4: Polish and Differentiators

**Rationale:** JSON tree viewer and state diff are enhancements to the live panel; they are only valuable once the panel is working correctly. System prompt capture requires a separate `_generate_next_response()` instrumentation hook — straightforward but a distinct concern.

**Delivers:** Collapsible JSON viewer for messages and raw responses. State diff showing exactly what changed in `tools_context['state']` between iterations. System prompt + RAG context captured per trace. Configuration UI in Settings.

**Addresses:** All P2 differentiator features (state diff viewer, JSON tree renderer, system prompt capture, confirmation flow tracking fields are already in the model by Phase 1).

**Avoids:** No new architectural risks. Incremental additions to established patterns.

**Research flag:** Skip. Standard OWL component patterns; no novel integration.

### Phase Ordering Rationale

- **Models before UI:** Every frontend component and XML view depends on the schema. Building the schema first also forces the developer to think through what data is needed before writing capture code.
- **Backend views before live panel:** Backend views give immediate feedback on captured data quality with no WebSocket complexity. If the generator instrumentation has a bug, it's much easier to diagnose from a list view than from a live panel.
- **Bus channel design before component:** The channel naming scheme (UUID vs integer, user-scoped vs trace-scoped) must be decided before any frontend subscribes. Changing it later requires synchronized frontend and backend changes.
- **Polish last:** JSON tree viewer and state diff require accurate data to be useful. Building them before validating data correctness wastes effort.

### Research Flags

Phases needing deeper research during task breakdown:
- **Phase 3 (Bus Integration):** The `postcommit` hook with a separate cursor is the subtle part — verify the exact commit timing by tracing through `thoughts_generator` → `_run_agentic_loop` → each yield → cursor exit. The ARCHITECTURE.md documents this but implementation will surface edge cases.

Phases with standard patterns (no additional research needed):
- **Phase 1:** Generator override pattern is fully specified with working code in STACK.md and ARCHITECTURE.md.
- **Phase 2:** Standard Odoo XML views. Nothing novel.
- **Phase 4:** Standard OWL component composition. JSON diff is a library function or simple recursive comparison.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All patterns verified against Odoo master source code at specific file paths and line numbers. No inference — direct reads. |
| Features | MEDIUM-HIGH | Table-stakes features are HIGH confidence (translated from well-documented external tools). Live panel differentiator is HIGH confidence (core project goal). v2+ features are LOW confidence (intentionally deferred). |
| Architecture | HIGH | Grounded in direct source inspection of `ai_session.py`, `thoughts_generator`, `bus.bus`, `ir_websocket`, and multiple reference modules. Separate cursor / postcommit pattern has a verified precedent in `google_calendar`. |
| Pitfalls | HIGH | All pitfalls are derived from direct source inspection, not inference. The generator yield contract, bus payload limits, and TransientModel vacuum behavior are all verified against actual Odoo code. |

**Overall confidence:** HIGH

### Gaps to Address

- **State diff implementation:** The research identifies `state_before` / `state_after` fields as the mechanism. The actual diff algorithm (Python `deepdiff` vs simple key comparison vs JS-side rendering) is not specified. Decide during Phase 4 task breakdown — `deepdiff` is not in Odoo's Python env; a simple recursive comparison or JSON patch format is safer.

- **`busService.removeChannel()` API name:** ARCHITECTURE.md notes "check actual API name" for removing a channel on component unmount. This must be verified against `bus_service.js` before implementing the OWL panel. Likely `busService.deleteChannel()` or similar — look up during Phase 3.

- **`_generate_next_response` hook depth:** System prompt and RAG context capture requires instrumenting a level above `_run_agentic_loop`. The exact hook point and what data is available at that level is documented in FEATURES.md but not fully code-verified. Needs source read during Phase 4 task breakdown.

- **Auto-vacuum: `@api.autovacuum` vs `ir.cron`:** STACK.md recommends `@api.autovacuum`. ARCHITECTURE.md mentions `data/ir_cron_data.xml`. The decision should be finalized in Phase 1: `@api.autovacuum` is simpler (no XML data record) and correct for this use case; `ir.cron` is only needed if configurable scheduling is required.

## Sources

### Primary (HIGH confidence — direct Odoo source reads)

- `enterprise/ai/models/ai_session.py` — `_run_agentic_loop` generator, `_handle_tool_calls`, yield structure, tool confirmation early return
- `enterprise/ai/controllers/thread.py` — `thoughts_generator` cursor management, how the generator is consumed
- `addons/bus/models/bus.py` — `_sendone` precommit/postcommit, `NOTIFY_PAYLOAD_MAX_LENGTH`
- `addons/bus/models/bus_listener_mixin.py` — `_bus_send()` / `BusListenerMixin` implementation
- `addons/bus/models/ir_websocket.py` — `_build_bus_channel_list`, `_prepare_subscribe_data` security model
- `addons/bus/models/res_users.py` — `res.users._bus_channel()` routes to `partner_id`
- `addons/bus/static/src/services/bus_service.js` — `subscribe()`, `unsubscribe()`, `addChannel()`, `start()` JS API
- `addons/web/static/src/core/utils/hooks.js` — `useService()` hook
- `enterprise/spreadsheet_edition/models/ir_websocket.py` — reference `_build_bus_channel_list` with access check
- `addons/google_calendar/models/google_sync.py` — `@postcommit.add` with separate `registry.cursor()` precedent
- `addons/hr_attendance/models/ir_websocket.py` — custom string channel + `_build_bus_channel_list` override example
- `enterprise/ai/static/src/ai_natural_language_service.js` — `bus_service.subscribe()` + `bus_service.start()` in a service; `ai_session_identifier` tab-scoping pattern
- `addons/web/static/lib/owl/owl.js` — OWL version 2.8.1 confirmed
- `odoo/orm/models_transient.py` — `_transient_vacuum` and TransientModel lifecycle

### Secondary (MEDIUM confidence — official ecosystem documentation)

- [Langfuse data model](https://langfuse.com/docs/observability/data-model) — trace/span/observation hierarchy
- [Langfuse observability overview](https://langfuse.com/docs/observability/overview) — feature expectations
- [LangSmith Observability](https://www.langchain.com/langsmith/observability) — competitor feature baseline
- [Arize Phoenix docs](https://arize.com/docs/phoenix) — competitor feature baseline

### Tertiary (LOW confidence — vendor/community blogs)

- [Braintrust observability tools](https://www.braintrust.dev/articles/best-ai-observability-tools-2026) — vendor-written comparison
- [LLM observability best practices](https://www.getmaxim.ai/articles/llm-observability-best-practices-for-2025/) — third-party blog

---
*Research completed: 2026-02-20*
*Ready for roadmap: yes*
