# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.
**Current focus:** v1.1 Phase 7 — Detail Panel

## Current Position

Milestone: v1.1 Live Tracer Standalone App
Phase: 7 of 7 (Detail Panel)
Plan: 2 of 2 in current phase (complete)
Status: Complete
Last activity: 2026-02-21 - Completed quick task 10: hide mail ChatHub/ChatBubble in standalone app

Progress: [█████░░░░░] 50% (v1.1)

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
- [Phase 06-sidebar-tree]: Remove display:flex;flex-direction:column from .ai-tree-content — flex column intrinsic sizing prevents overflow scroll; block layout is correct for list of rows
- [Phase 06-sidebar-tree]: Add min-height:0 to .ai-tree-content — overrides default min-height:auto on flex items so overflow-y:auto actually triggers
- [06-05]: [...traces.keys()].reverse() on trace t-foreach — extends existing iteration reverse ordering pattern to traces so newest loops appear at top of sidebar
- [07-01]: Auto-select in _onNewTrace only when state.selectedId === null — single exception to SIDE-05, permitted because condition guarantees no active selection disrupted
- [07-01]: result field in _onToolCall stored without fallback (payload.result directly) — may legitimately be null, false, 0, or empty string; || {} fallback would obscure meaningful falsy results
- [07-01]: JsonTree defaults to depth 0 auto-expanded (expanded: props.depth < 1) — top-level keys visible, nested objects collapsed; matches DevTools default behavior
- [07-01]: Prism.highlightElement over Prism.highlight + innerHTML — set textContent first then highlightElement for safe, simpler DOM update
- [Phase 07-detail-panel]: try/catch around useService('dialog') — standalone app context may not have dialog service; null fallback disables popup gracefully rather than crashing
- [Phase 07-detail-panel]: resultIsObject getter in tc_detail.js — moves typeof check out of OWL template to avoid 'and' vs && issues in XML expressions
- [Phase 07-detail-panel]: ragContextMessages returns null before first iteration arrives — template differentiates waiting vs no RAG found states

### Pending Todos

None.

### Blockers/Concerns

- [Phase 5]: Payload size for RAG-enabled sessions unknown — research recommends ~32 KB cap but needs empirical baseline before finalizing meta/detail split strategy
- [Phase 6 RESOLVED]: OWL reactive Map (.set() triggers re-render) confirmed in OWL source comments — verified HIGH confidence from OWL source (COLLECTION_RAW_TYPES includes Map)

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 7 | fix the cosmetic gaps | 2026-02-21 | 4e321a3 | [7-fix-the-cosmetic-gaps](./quick/7-fix-the-cosmetic-gaps/) |
| 8 | fix json tree compounding indentation | 2026-02-21 | 9efe0f2 | [8-fix-json-tree-compounding-indentation](./quick/8-fix-json-tree-compounding-indentation/) |
| 9 | fix TextPopupDialog not opening in standalone app | 2026-02-21 | b74eeba | [9-fix-textpopupdialog-not-opening-in-stand](./quick/9-fix-textpopupdialog-not-opening-in-stand/) |
| 10 | hide mail ChatHub/ChatBubble in standalone app | 2026-02-21 | 1fe2c3b | [10-hide-o-mail-chathub-chatbox-in-standalon](./quick/10-hide-o-mail-chathub-chatbox-in-standalon/) |

## Session Continuity

Last session: 2026-02-21
Stopped at: Completed quick-10 (hide mail ChatHub/ChatBubble in standalone app)
Resume file: None
