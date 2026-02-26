---
phase: quick-38
plan: 01
subsystem: ui, api
tags: [ai_debug, thread-local, bus-event, owl, json-tree, request-body]

# Dependency graph
requires: []
provides:
  - HTTP request body captured per-iteration via thread-local in ai_provider_patch
  - request_body field in iteration bus events with binary stripping
  - Request tab in IterationDetail Notebook showing request body as JsonTree
affects: [ai_debug]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Capture mutable request data before async call in thread-local to guarantee availability"
    - "Shallow-copy + strip binary fields before bus transmission (OpenAI input / Google contents)"

key-files:
  created: []
  modified:
    - ai_debug/models/ai_provider_patch.py
    - ai_debug/models/ai_session.py
    - ai_debug/static/src/app/detail/iter_detail.js
    - ai_debug/static/src/app/detail/iter_detail.xml

key-decisions:
  - "Strip binary from OpenAI 'input' and Google 'contents' arrays (same keys as messages_sent stripping)"
  - "Use shallow copy (copy.copy) on request_body before mutation to avoid corrupting the original dict"
  - "Request tab always visible (isVisible=true); JsonTree renders nothing when data is null/undefined"
  - "request_body not included in error iteration payloads — no meaningful body when exception occurs"

patterns-established:
  - "Thread-local fields: stash BEFORE call, clear immediately after pop"

requirements-completed: [QUICK-38]

# Metrics
duration: 8min
completed: 2026-02-26
---

# Quick Task 38: Capture Request Body in AI Debug Iterations Summary

**HTTP request body captured per-iteration via thread-local, binary-stripped, and displayed in a new Request tab (between Messages Sent and Raw Response) using JsonTree with copy button**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-02-26
- **Completed:** 2026-02-26
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- `_patched_request` stashes the request body dict in `_ai_debug_local.last_request_body` before the LLM call — available even if the call raises
- `pop_last_completion_data()` now returns `request_body` as a third field alongside `tokens` and `llm_duration_ms`, with immediate clear on read
- `_run_agentic_loop` extracts, shallow-copies, binary-strips (OpenAI `input` / Google `contents`), and conditionally includes `request_body` in each `iteration` bus event
- `IterationDetail` component gains a `requestJson` getter and a "Request" tab in the Notebook — positioned between "Messages Sent" and "Raw Response"

## Task Commits

1. **Task 1: Capture request body in thread-local and include in iteration bus event** - `46b0e2f` (feat)
2. **Task 2: Add Request tab to iteration detail view** - `5bb2bd3` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified
- `ai_debug/models/ai_provider_patch.py` - Stash `last_request_body` before call; pop and clear in `pop_last_completion_data`
- `ai_debug/models/ai_session.py` - Extract, binary-strip, and include `request_body` in iteration bus payload
- `ai_debug/static/src/app/detail/iter_detail.js` - Add `requestJson` getter
- `ai_debug/static/src/app/detail/iter_detail.xml` - Add Request tab slot between Messages Sent and Raw Response

## Decisions Made
- Stash request body BEFORE the HTTP call so it's available even on exception
- Shallow copy before binary stripping to avoid mutating the original dict still held in thread-local
- Binary stripping handles both OpenAI (`input`) and Google (`contents`) key names
- `request_body` omitted from error iteration payloads — there's no meaningful body when an exception fires before completion data is available
- Tab always visible (`isVisible="true"`); JsonTree handles null data gracefully

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Request body observability is fully closed; the debugger now captures messages-sent, HTTP request body, and raw response per iteration
- No follow-up work required

---
*Phase: quick-38*
*Completed: 2026-02-26*
