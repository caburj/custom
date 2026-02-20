# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-20)

**Core value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.
**Current focus:** Phase 3 — Live Panel and Polish

## Current Position

Phase: 3 of 3 (Live Panel and Polish)
Plan: 2 of 2 in current phase
Status: Phase 3 in progress — 03-01 complete, 03-02 pending
Last activity: 2026-02-20 — Completed 03-01 (backend bus pipeline for real-time debug streaming)

Progress: [█████████░] 80%

## Performance Metrics

**Velocity:**
- Total plans completed: 4
- Average duration: 2 min
- Total execution time: 8 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-data-models-and-instrumentation | 2 | 4 min | 2 min |
| 02-backend-views | 1 | 2 min | 2 min |
| 03-live-panel-and-polish | 1 | 2 min | 2 min |

**Recent Trend:**
- Last 5 plans: 2min, 2min, 2min, 2min
- Trend: baseline

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Persistent Model (not TransientModel) for debug data — ai.session is transient; traces must survive session cleanup
- Generator yield passthrough (`for item in super()...: yield item`) — preserves streaming semantics and confirmation flow
- Models + backend views before live panel — verify captured data quality before adding WebSocket complexity
- Live panel as separate `ir.actions.client` tab — avoids patching the chat UI
- fields.Json (not fields.Text) for all JSON payload fields — native JSONB, no double-serialization (01-01)
- agent_id ondelete='set null' on ai.debug.trace — _run_agentic_loop is @api.model, may have no agent context (01-01)
- result field on ai.debug.tool.call is fields.Text (not Json) — tool results may be plain strings not JSON (01-01)
- Mutable dict _debug_ctx via Odoo context to share iteration_id between _run_agentic_loop and _handle_tool_calls — context values freeze on with_context(), mutable container required (01-02)
- _generate_next_response captures RAG context before super() — after super() context_input is merged into message parts and cannot be separated (01-02)
- Batch-level state snapshots in _handle_tool_calls (state_before/after batch, not per-tool) — base method processes tools sequentially inside its own generator (01-02)
- Computed Text pretty-print fields (not raw Json fields) used as ace widget targets — json.dumps with indent=2 on each Json field (02-01)
- result field on tool_call uses plain text widget not ace — result may be plain string not JSON (02-01)
- trace action sets search_default_today:1 in context — defaults list to today's traces on open (02-01)
- _debug_write_trace returns (trace_id, bus_channel) tuple — bus_channel needed in debug_ctx before loop starts (03-01)
- _debug_bus_send helper receives local cursor env argument — avoids duplicating channel lookup in three write helpers (03-01)
- Summary-only bus payloads — no messages_sent/raw_response; frontend RPC-fetches detail on demand (03-01)

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 3: Confirm exact `bus_service` API name for channel removal on OWL component unmount before implementing DebugPanel (03-02).

## Session Continuity

Last session: 2026-02-20
Stopped at: Completed 03-01-PLAN.md (backend bus pipeline — Phase 3 plan 1 of 2)
Resume file: None
