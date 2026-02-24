---
phase: 16-backend-token-extraction-and-per-iteration-timing
plan: 01
subsystem: api
tags: [odoo, python, monkey-patch, threading, token-extraction, bus-events, instrumentation]

# Dependency graph
requires:
  - phase: 15-sub-agent-tracing-and-nesting
    provides: agentic loop bus event infrastructure (_ai_debug_bus_send, _run_agentic_loop override, _handle_tool_calls override)
provides:
  - threading.local() monkey-patch on AIApiService._request capturing raw completion responses
  - Per-provider token extractors (OpenAI/Google) normalizing to {input, output, total, cached?, reasoning?}
  - pop_last_completion_data() atomic read-and-clear function
  - Iteration bus events enriched with tokens (conditional), duration_ms (LLM call time), and provider name
  - tool_call_completed bus events enriched with duration_ms
  - TIME-02 verified: loop_end.duration_ms unchanged
affects:
  - 17-reactive-store-live-metrics
  - 18-live-metrics-display

# Tech tracking
tech-stack:
  added: []
  patterns:
    - threading.local() for per-thread state accumulation across call boundaries
    - monkey-patch at module load time (applied in __init__.py as first import)
    - pop-and-clear pattern to prevent cross-iteration thread-local contamination
    - conditional field inclusion in bus event dicts (absent key = failure signal)

key-files:
  created:
    - ai_debug/models/ai_provider_patch.py
  modified:
    - ai_debug/models/__init__.py
    - ai_debug/models/ai_session.py

key-decisions:
  - "Token total uses raw provider value (not computed from input + output) — matches CONTEXT.md locked decision"
  - "cached/reasoning fields are sparse — omitted when 0, only included when non-zero"
  - "tokens field is absent (not null) on errored iterations — absence signals failure per CONTEXT.md"
  - "provider_name resolved once before loop start using AIProvider.get_by_model (same model for entire loop)"
  - "pop_last_completion_data() called as the very first action when an iteration item arrives — prevents stale reads"
  - "Endpoint filter uses endswith('responses') for OpenAI and contains 'generateContent' for Google"

patterns-established:
  - "Monkey-patch pattern: save original, wrap with instrumentation, restore on module load"
  - "Thread-local pop pattern: read both fields, clear both immediately, then process — atomic read-clear"
  - "Graceful degradation: all instrumentation in try/except, LLM call never disrupted"

requirements-completed: [TOKN-01, TOKN-02, TOKN-03, TOKN-04, TIME-01, TIME-02]

# Metrics
duration: 3min
completed: 2026-02-24
---

# Phase 16 Plan 01: Backend Token Extraction and Per-Iteration Timing Summary

**threading.local() monkey-patch on AIApiService._request captures OpenAI and Google token usage and LLM call duration, wired into iteration and tool_call_completed bus events for Phase 17 reactive store consumption**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-24T16:52:09Z
- **Completed:** 2026-02-24T16:54:57Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `ai_provider_patch.py`: monkey-patches `AIApiService._request` at module load time, filters to completion endpoints only, times the HTTP call, stashes raw response + duration in `threading.local()`
- Per-provider extractors normalize both response shapes: OpenAI `usage.{input_tokens,output_tokens,total_tokens}` and Google `usageMetadata.{promptTokenCount,candidatesTokenCount,totalTokenCount}` — canonical `{input, output, total}` dict with sparse `cached`/`reasoning`
- `pop_last_completion_data()` reads and immediately clears both thread-local fields (prevents cross-iteration contamination per Pitfall 1 from research)
- Iteration bus events now include `tokens` (conditional), `duration_ms` (LLM call ms), and `provider` fields — error iterations include `duration_ms` and `provider` but skip `tokens`
- `tool_call_completed` events include `duration_ms` measured from batch start to completion
- Verified TIME-02: `loop_end.duration_ms` unchanged

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ai_provider_patch.py with threading.local() interception and token extractors** - `1b85695` (feat)
2. **Task 2: Wire tokens, timing, and provider into iteration and tool_call bus events** - `85f4a27` (feat)

**Plan metadata:** _(final docs commit follows)_

## Files Created/Modified

- `ai_debug/models/ai_provider_patch.py` - New file: monkey-patch, thread-local storage, OpenAI/Google extractors, pop_last_completion_data()
- `ai_debug/models/__init__.py` - Added `ai_provider_patch` as first import so patch runs at module load
- `ai_debug/models/ai_session.py` - Added provider resolution, pop_last_completion_data() call per iteration, conditional tokens/duration_ms in bus events, timing on tool_call_completed

## Decisions Made

- Token `total` uses the raw provider value rather than computing `input + output` — matches CONTEXT.md locked decision, preserves any provider-internal discrepancy
- `cached` and `reasoning` fields are sparse — only included in the tokens dict when non-zero, not defaulted to 0
- `tokens` field is absent (not null/undefined) on errored iterations — per CONTEXT.md "absence signals failure"
- Provider name resolved once before the loop using `AIProvider.get_by_model` — same model used for the entire agentic loop call
- `pop_last_completion_data()` called as the very first action inside the `if 'tool_calls' in item or 'final_message' in item:` branch — before `iteration_count += 1` — to minimize risk of reading data from the next iteration

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 17 (reactive store live metrics) can now consume `tokens`, `duration_ms`, and `provider` fields from iteration bus events
- Phase 18 (live metrics display) can rely on these fields being present on all successful iterations
- No frontend changes in this phase — purely backend instrumentation

---
*Phase: 16-backend-token-extraction-and-per-iteration-timing*
*Completed: 2026-02-24*
