---
phase: 13-python-instrumentation-and-bus-event-handling
plan: 01
subsystem: api
tags: [odoo, python, bus-events, agentic-loop, instrumentation, subagents]

# Dependency graph
requires: []
provides:
  - "new_trace bus event includes session_id (ORM int), parent_trace_id (UUID hex or null), parent_tool_call_id (call_id string or null)"
  - "tool_call_started event fires BEFORE super() delegation with tool name, args, call_id, stable tool_call_id UUID"
  - "tool_call_completed event fires AFTER super() yields tool_results with matching tool_call_id, result, success, error"
  - "ai_parent_trace_id injected into env.context in _handle_tool_calls before super() so child sessions can read it"
  - "ai_parent_tool_call_id injected into env.context by ai.agent override when subagent tool is invoked"
  - "Zero overhead path when instrumentation not active (_debug_ctx guard in ai_agent override)"
affects:
  - 14-javascript-flat-map-and-bus-event-handling
  - 15-sidebar-hierarchy-and-agent-color-coding

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "env.context threading with with_context() for propagating parent linkage across Odoo ORM boundaries"
    - "Pre-generated UUID map (_tc_id_map) for stable event ID correlation across started/completed event pairs"
    - "Minimal model override pattern: ai.agent inherit with _debug_ctx guard for zero overhead when not instrumented"

key-files:
  created:
    - ai_debug/models/ai_agent.py
  modified:
    - ai_debug/models/ai_session.py
    - ai_debug/models/__init__.py

key-decisions:
  - "No parent_session_id in new_trace — parent_trace_id (UUID) is the direct frontend pointer; CONTEXT.md supersedes REQUIREMENTS.md on this"
  - "ai_parent_trace_id injected in _handle_tool_calls (not in base _run_agentic_loop) so it propagates through super() to any subagent session spawned during tool execution"
  - "ai_parent_tool_call_id injected in ai.agent._ai_tool_request_sub_agent override using tool_context['tool_call_id'] which the base _handle_tool_calls sets to the LLM call_id"
  - "_tc_id_map pre-generated before super() call ensures tool_call_started and tool_call_completed share the same stable UUID regardless of execution order"
  - "tool_call_completed replaces old single tool_call event; result_item.get('tool_call', {}) key access is a data accessor (not an event), retained unchanged"

patterns-established:
  - "Split event pattern: emit started event before super(), emit completed event after super() yields results, use pre-generated ID map for correlation"
  - "Context threading: use self.with_context() not dict mutation; inherited by all ORM calls within the same env lineage"

requirements-completed: [INST-01, INST-02, INST-03]

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 13 Plan 01: Python Instrumentation and Bus Event Handling Summary

**Parent linkage in new_trace (session_id + parent_trace_id + parent_tool_call_id) and split tool_call events (started/completed with stable UUID correlation) enabling subagent hierarchy construction in the JS frontend**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T13:56:55Z
- **Completed:** 2026-02-23T13:59:16Z
- **Tasks:** 2
- **Files modified:** 3 (ai_session.py modified, ai_agent.py created, __init__.py modified)

## Accomplishments
- new_trace payload now includes session_id (ORM int), parent_trace_id (UUID hex or null), parent_tool_call_id (LLM call_id or null) — consistent shape for all sessions (root and subagent)
- tool_call events split into tool_call_started (before execution) and tool_call_completed (after execution) with stable UUID correlation via _tc_id_map
- Context threading chain complete: _handle_tool_calls injects ai_parent_trace_id, ai.agent override injects ai_parent_tool_call_id, child session reads both in _run_agentic_loop

## Task Commits

Each task was committed atomically:

1. **Task 1: Add parent linkage to new_trace payload and inject context in _handle_tool_calls** - `a6e5758` (feat)
2. **Task 2: Split tool_call event into tool_call_started and tool_call_completed** - `6ee9f01` (feat)
3. **Docstring update (_run_agentic_loop)** - `9159bfc` (refactor)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `ai_debug/models/ai_session.py` - new_trace parent fields, _handle_tool_calls context injection, split tool_call events
- `ai_debug/models/ai_agent.py` - new file: ai.agent override threading ai_parent_tool_call_id to subagent sessions
- `ai_debug/models/__init__.py` - added `from . import ai_agent`

## Decisions Made
- No `parent_session_id` field — `parent_trace_id` (UUID) is sufficient for the frontend; ORM ID not needed
- `_tc_id_map` pre-generated before super() to guarantee UUID stability across the started/completed event pair
- `ai.agent` override guarded by `_debug_ctx` presence so non-instrumented sessions pay zero overhead
- `result_item.get('tool_call', {})` is a data key accessor into the Odoo tool_results structure, not a bus event — correctly retained

## Deviations from Plan

None — plan executed exactly as written. The docstring update was a minor cleanup to keep the _run_agentic_loop docstring accurate after replacing the `tool_call` event with the split pair.

## Issues Encountered

The Task 2 automated verification script flagged a false positive: `result_item.get('tool_call', {})` contains the string `'tool_call'` but is a data accessor, not a bus event emission. The check was inspected and confirmed correct — all three bus event emissions of `'tool_call'` type were successfully replaced with `'tool_call_started'` and `'tool_call_completed'`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Phase 14 (JavaScript flat map and bus event handling) can consume the new event fields immediately
- new_trace.parent_trace_id and new_trace.parent_tool_call_id are the two fields the JS _onNewTrace handler will use to position child traces in the hierarchy
- tool_call_started events must be processed before tool_call_completed to build the parent node before associating child traces

---
*Phase: 13-python-instrumentation-and-bus-event-handling*
*Completed: 2026-02-23*
