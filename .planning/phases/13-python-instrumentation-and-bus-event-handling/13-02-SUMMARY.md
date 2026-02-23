---
phase: 13-python-instrumentation-and-bus-event-handling
plan: "02"
subsystem: ui
tags: [owl, bus-service, javascript, reactive, subagents]

# Dependency graph
requires:
  - phase: 13-python-instrumentation-and-bus-event-handling
    provides: "Split tool_call_started/tool_call_completed Python bus events (Plan 01)"
provides:
  - "Split _onToolCallStarted/_onToolCallCompleted JS handlers consuming new event types"
  - "_pendingChildren buffer preventing out-of-order child traces from landing at root"
  - "_placeTrace helper method for unconditional trace creation (root and child paths)"
  - "parent_trace_id, parent_tool_call_id, session_id fields stored on trace objects"
affects:
  - "14-js-tree-rendering-and-agent-colors"
  - "15-sidebar-ui-for-subagent-display"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Split event handlers for two-phase lifecycle (started/completed) enabling live progress display"
    - "Pending-child buffer keyed by LLM call_id with setTimeout promotion prevents silent root placement"
    - "_placeTrace extracted helper used by both root and re-attachment paths (single source of truth)"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js

key-decisions:
  - "Buffer keyed by parent_tool_call_id (LLM call_id) so _onToolCallStarted can match using payload.call_id"
  - "clearTimeout must run before delete _pendingChildren to prevent double-fire on re-attachment"
  - "_pendingChildren is a plain JS object (not reactive) — internal bookkeeping, not rendered"
  - "Orphan traces promoted to root after 30s retain parent fields for potential future silent re-attachment"
  - "status field ('running'/'completed') stored now for Phase 15 visual indicators, not yet rendered"

patterns-established:
  - "Two-phase event pattern: *_started creates entry with running status, *_completed fills result in-place"
  - "Defensive _onToolCallCompleted creates entry if started was missed — always consistent state"
  - "Buffer pattern: check parent in traces map, buffer if missing, re-attach on parent arrival"

requirements-completed: [TREE-05]

# Metrics
duration: 2min
completed: 2026-02-23
---

# Phase 13 Plan 02: JS Split Event Handlers and Pending-Child Buffer Summary

**Split bus event handlers (tool_call_started/completed) and _pendingChildren buffer preventing out-of-order subagent child traces from silently landing at root level**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-23T13:56:58Z
- **Completed:** 2026-02-23T13:58:56Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Replaced monolithic `_onToolCall` handler with split `_onToolCallStarted`/`_onToolCallCompleted` pair — tool call nodes now appear immediately with status "running", filled in when result arrives
- Added `_pendingChildren` plain object buffer with 30s timeout promotion — child traces arriving before their parent tool call no longer silently land at root
- Extracted `_placeTrace` helper eliminating duplicate trace creation logic between root and re-attachment paths
- Stored `parent_trace_id`, `parent_tool_call_id`, `session_id` on all trace objects for Phase 14 tree rendering

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace _onToolCall with _onToolCallStarted and _onToolCallCompleted handlers** - `3266b1f` (feat)
2. **Task 2: Add pending-child buffer for out-of-order subagent traces** - `1f201e3` (feat)

## Files Created/Modified

- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` - Split event handlers, pending-child buffer, _placeTrace helper, parent fields on traces

## Decisions Made

- Buffer is keyed by `parent_tool_call_id` (the LLM's `call_id`) so `_onToolCallStarted` can match it using `payload.call_id` — the two identifiers are the same value from opposite directions.
- `clearTimeout` is called before `delete _pendingChildren[key]` to guarantee no double-fire even if JS engine flushes the timer queue between those two operations.
- `_pendingChildren` is a plain JS object (not OWL reactive) — it's internal bookkeeping that doesn't need to trigger re-renders.
- Orphan traces promoted after 30s retain their `parent_trace_id` and `parent_tool_call_id` fields — no data is lost, and future phases could implement silent re-attachment if desired.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 14 (JS tree rendering and agent colors) can now rely on `parent_trace_id` and `parent_tool_call_id` being stored on every trace object
- The `_placeTrace` helper is the canonical trace creation path for both root and child traces
- `status: "running"` field on tool calls is ready for Phase 15 visual indicator rendering

---
*Phase: 13-python-instrumentation-and-bus-event-handling*
*Completed: 2026-02-23*
