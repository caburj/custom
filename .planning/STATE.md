# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.
**Current focus:** v1.1 Phase 6 — Sidebar Tree

## Current Position

Milestone: v1.1 Live Tracer Standalone App
Phase: 6 of 7 (Sidebar Tree)
Plan: 1 of 1 in current phase (complete)
Status: In progress
Last activity: 2026-02-21 — Phase 6 Plan 01 complete (reactive sidebar tree with Loop > Iteration > Tool Call hierarchy)

Progress: [███░░░░░░░] 30% (v1.1)

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.1]: No DB persistence — ephemeral session-scoped data only; no ir.model or tables
- [v1.1]: Full bus.bus payloads — all display data must arrive in bus events (no lazy ORM reads)
- [v1.1]: Standalone OWL app (POS self-order pattern) — mountComponent from @web/env, own asset bundle
- [v1.1]: UUID keys for all identifiers — no DB autoincrement available
- [04-01]: ai_debug.assets bundle uses ('include', 'web.assets_backend') first so standalone OWL app loads with full Odoo backend environment
- [04-01]: debug_menu_button.js registered in web.assets_backend (not custom bundle) so it loads every backend session
- [04-02]: auth='user' on the route handles unauthenticated users automatically; is_user_internal() is the second gate for portal users
- [04-02]: session_info() (not get_frontend_session_info) provides the full session needed by bus_service in standalone context
- [04-02]: BUS:WORKER_STATE_UPDATED event tracked via addEventListener on bus_service EventTarget (not bus_service.subscribe)
- [05-01]: messages_sent sends full accumulated conversation history per iteration (not deltas) for downstream simplicity
- [05-01]: _handle_tool_calls uses batch-level state granularity (state before/after entire tool batch) — per-tool Option C deferred to v1.2
- [05-01]: _debug_ctx mutable dict propagated via self.with_context() so _handle_tool_calls can reference trace_id and iteration_id
- [05-01]: Failed iterations emit an iteration event with error field before loop_end so errors appear in the sidebar tree
- [06-01]: reactive(new Map()) for trace store — NOT inside useState; nested reactive Maps for iterations and toolCalls
- [06-01]: Bus handlers write only to trace Maps, never to state.selectedId — SIDE-05 stable selection
- [06-01]: toggleExpand unified signature: (id, 'trace') for loops or (traceId, iterationId) for iterations
- [06-01]: Flash animation on new loop arrivals only; iterations/tool calls appear without flash to avoid visual noise

### Pending Todos

None.

### Blockers/Concerns

- [Phase 5]: Payload size for RAG-enabled sessions unknown — research recommends ~32 KB cap but needs empirical baseline before finalizing meta/detail split strategy
- [Phase 6 RESOLVED]: OWL reactive Map (.set() triggers re-render) confirmed in OWL source comments — verified HIGH confidence from OWL source (COLLECTION_RAW_TYPES includes Map)

## Session Continuity

Last session: 2026-02-21
Stopped at: Completed 06-sidebar-tree/06-01-PLAN.md (reactive sidebar tree, bus handlers, three-level hierarchy, selection state)
Resume file: None
