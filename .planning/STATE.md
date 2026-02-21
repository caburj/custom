# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.
**Current focus:** v1.1 Phase 7 — Detail Panel

## Current Position

Milestone: v1.1 Live Tracer Standalone App
Phase: 7 of 7 (Detail Panel)
Plan: 0 of 1 in current phase (ready to start)
Status: In progress
Last activity: 2026-02-21 — Phase 6 Plan 03 complete (reactive->useState gap closure fix, unblocks all 11 UAT sidebar tests)

Progress: [████░░░░░░] 40% (v1.1)

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
- [06-01 REVERSED by 06-03]: this.traces uses useState(new Map()) — reactive(new Map()) without callback was wrong; nested reactive Maps for iterations and toolCalls remain
- [06-01]: Bus handlers write only to trace Maps, never to state.selectedId — SIDE-05 stable selection
- [06-01]: toggleExpand unified signature: (id, 'trace') for loops or (traceId, iterationId) for iterations
- [06-01]: Flash animation on new loop arrivals only; iterations/tool calls appear without flash to avoid visual noise
- [Phase 06]: t-ref moved from aside to .ai-tree-content so scrollIntoView targets scrollable area, pinning the header
- [Phase 06]: animation:none on .selected rows suppresses slide-in re-animation on each reactive patch
- [Phase 06-sidebar-tree]: Reversed [06-01] reactive(new Map()) decision: this.traces now uses useState(new Map()) — reactive without callback uses NO_CALLBACK sentinel blocking OWL render observation

### Pending Todos

None.

### Blockers/Concerns

- [Phase 5]: Payload size for RAG-enabled sessions unknown — research recommends ~32 KB cap but needs empirical baseline before finalizing meta/detail split strategy
- [Phase 6 RESOLVED]: OWL reactive Map (.set() triggers re-render) confirmed in OWL source comments — verified HIGH confidence from OWL source (COLLECTION_RAW_TYPES includes Map)

## Session Continuity

Last session: 2026-02-21
Stopped at: Completed 06-sidebar-tree/06-03-PLAN.md (reactive->useState fix for trace store)
Resume file: None
