# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.
**Current focus:** v1.1 Phase 4 — Infrastructure

## Current Position

Milestone: v1.1 Live Tracer Standalone App
Phase: 4 of 7 (Infrastructure)
Plan: 2 of ? in current phase
Status: In progress
Last activity: 2026-02-21 — Phase 4 Plan 02 complete (standalone OWL app shell, HTTP controller, bus subscription)

Progress: [░░░░░░░░░░] 5% (v1.1)

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

### Pending Todos

None.

### Blockers/Concerns

- [Phase 5]: Payload size for RAG-enabled sessions unknown — research recommends ~32 KB cap but needs empirical baseline before finalizing meta/detail split strategy
- [Phase 6]: OWL reactive Map (.set() triggers re-render) confirmed in OWL source comments but not test-covered — validate with proof-of-concept before building full sidebar

## Session Continuity

Last session: 2026-02-21
Stopped at: Completed 04-infrastructure/04-02-PLAN.md (standalone OWL app shell, HTTP controller, bus subscription)
Resume file: None
