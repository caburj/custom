---
phase: 05-bus-instrumentation
plan: 01
subsystem: api
tags: [bus.bus, odoo, python, ai-session, agentic-loop, websocket, real-time]

# Dependency graph
requires:
  - phase: 04-infrastructure
    provides: ir.websocket override gating 'ai_debug' bus channel to internal users; standalone OWL app subscribing to 'ai_debug'
provides:
  - AiSession override with _run_agentic_loop emitting new_trace, iteration, loop_end events
  - AiSession override with _handle_tool_calls emitting tool_call events with state snapshots
  - Separate-cursor bus send helper (_ai_debug_bus_send) for real-time event delivery
  - Binary content stripping (_ai_debug_strip_binary) for safe message payloads
  - Tool definition serialization (_ai_debug_serialize_tools) for new_trace payloads
  - State snapshot capture (_ai_debug_state_snapshot) for environment context
affects:
  - 06-sidebar (consumes new_trace, iteration, tool_call, loop_end events to populate sidebar tree)
  - 07-detail-panel (consumes iteration.messages_sent and tool_call.args/result for detail views)

# Tech tracking
tech-stack:
  added: [uuid (stdlib), time (stdlib), copy (stdlib)]
  patterns:
    - "registry.cursor() separate-cursor pattern for real-time bus sends (from ai/controllers/thread.py)"
    - "_debug_ctx dict propagated via env.context for cross-method coordination"
    - "Generator protocol preserved: yield from super() or explicit yield item"
    - "Instrumentation try/except swallow pattern: failures logged, never propagated"

key-files:
  created:
    - ai_debug/models/ai_session.py
  modified:
    - ai_debug/models/__init__.py

key-decisions:
  - "messages_sent sends full accumulated conversation history per iteration (not deltas) for downstream simplicity"
  - "state snapshots use batch-level granularity (state before/after entire tool batch, not per-tool) — Option B from research"
  - "_debug_ctx shared dict propagated via self.env.context so _handle_tool_calls can reference trace_id and iteration_id without method signature changes"
  - "Failed iterations emit a separate iteration event with error field before loop_end so errors appear in the sidebar tree"
  - "Binary content in messages replaced with {type, _binary_excluded: True} stubs to prevent payload bloat"

patterns-established:
  - "Separate cursor pattern: with self.env.registry.cursor() as cr: env = self.env(cr=cr); env['bus.bus']._sendone(...)"
  - "Context propagation: self = self.with_context(_debug_ctx=_debug_ctx) to pass mutable state to overridden child methods"
  - "Instrumentation guard: if not _debug_ctx: yield from super(); return — zero overhead when not instrumented"

requirements-completed: [BUS-01, BUS-02, BUS-03, BUS-04, BUS-05]

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 5 Plan 01: Bus Instrumentation Summary

**AiSession loop instrumentation emitting new_trace, iteration, tool_call, and loop_end bus events via registry.cursor() separate cursors for real-time delivery**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-21T11:03:42Z
- **Completed:** 2026-02-21T11:05:33Z
- **Tasks:** 2 of 2
- **Files modified:** 2

## Accomplishments

- Created `ai_debug/models/ai_session.py` with complete AiSession instrumentation
- `_run_agentic_loop` override emits `new_trace` at loop start (agent, model, system prompt, tools, state snapshot), `iteration` per LLM API call (full message history, raw response, error on failure), and `loop_end` at termination (success/max_iterations/error with stats)
- `_handle_tool_calls` override emits `tool_call` per tool result with args, result, success/error, and before/after state snapshots
- All four event types satisfy requirements BUS-01 through BUS-05: full payload, UUID identifiers, separate cursors for real-time delivery, matching Phase 4's `'ai_debug'` channel subscription
- Failed iterations emit an `iteration` event with `error` field before `loop_end` so failed agentic runs appear in the sidebar tree (Phases 6/7 dependency)

## Task Commits

Each task was committed atomically:

1. **Task 1 + 2: Create ai_session.py with loop lifecycle and tool call instrumentation** - `8b93ad2` (feat)

**Plan metadata:** (pending)

## Files Created/Modified

- `ai_debug/models/ai_session.py` - AiSession override with _run_agentic_loop, _handle_tool_calls, and four helper methods
- `ai_debug/models/__init__.py` - Added `from . import ai_session`

## Decisions Made

- **Full conversation history per iteration:** `messages_sent` sends a shallow copy of the full accumulated `messages` list (not deltas). Downstream Phase 7 detail panel reads `messages_sent[iteration]` directly without needing to reconstruct history. Payload size is the only tradeoff; user decided no truncation for v1.1.
- **Batch-level state granularity (Option B):** `_handle_tool_calls` captures state before and after the entire tool batch — not per-tool. Per-tool granularity (Option C) would require re-implementing the upstream method body. Deferred to v1.2.
- **`_debug_ctx` via env.context:** A mutable dict `{trace_id, iteration_id, tool_call_count}` is propagated via `self.with_context(_debug_ctx=_debug_ctx)` so `_handle_tool_calls` can reference the current trace/iteration without method signature changes.
- **Failed iteration events:** When the loop raises (UserError for max_iterations, any Exception for error), an `iteration` event with `error` and `error_type` fields is emitted before `loop_end`. This ensures the failed iteration appears as a node in the sidebar tree, not just as a loop_end attribute.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All five BUS requirements satisfied
- `new_trace`, `iteration`, `tool_call`, `loop_end` events flow to 'ai_debug' channel immediately during loop execution
- Phase 6 (sidebar) can subscribe to these events and populate the trace tree in real time
- Phase 7 (detail panel) can consume `iteration.messages_sent` and `tool_call.args/result` for full detail views
- Blocker noted in STATE.md: payload size for RAG-enabled sessions still unknown — empirical baseline needed before finalizing meta/detail split strategy (Phase 6 concern)

---
*Phase: 05-bus-instrumentation*
*Completed: 2026-02-21*
