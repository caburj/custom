---
phase: quick-25
plan: 01
subsystem: ui
tags: [owl, bus, python, odoo, ai-debug, tool-call, confirmation]

# Dependency graph
requires: []
provides:
  - Backend detection of tool_confirmation_request items in _handle_tool_calls
  - Enriched tool_call bus events with triggered_confirmation and confirmation_message fields
  - Frontend storage of confirmation fields in toolCalls Map
  - Conditional Confirmation Info tab in ToolCallDetail showing HTML message with warning badge
  - Pending status badge for tool calls with success=null
affects: [ai_debug]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Walrus operator (elif confirmation := item.get(...)) for clean item-type dispatch in generator loop"
    - "isVisible getter pattern for OWL Notebook tab conditional visibility"
    - "t-out for rendering trusted HTML from enterprise confirmation messages"

key-files:
  created: []
  modified:
    - ai_debug/models/ai_session.py
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/detail/tc_detail.js
    - ai_debug/static/src/app/detail/tc_detail.xml

key-decisions:
  - "Use t-out (not t-esc) for confirmation_message since it comes from make_batch_update_preview which produces safe HTML"
  - "Tab completely hidden (isVisible=false) when no confirmation — no empty state fallback needed"
  - "success===null signals pending confirmation state, distinct from true/false"

patterns-established:
  - "Confirmation tab: isVisible driven by hasConfirmation getter (not inline expression)"

requirements-completed: [CONFIRM-01]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Quick Task 25: Implement Confirmation Info Tab in AI Debugger Summary

**Backend captures tool_confirmation_request events from enterprise and emits enriched tool_call bus events; frontend stores and renders the Confirmation Info tab with conditional visibility and a Pending status badge.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-22T20:48:13Z
- **Completed:** 2026-02-22T20:49:29Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Backend: added `tool_calls_by_id` lookup and `elif` branch in `_handle_tool_calls` to detect `tool_confirmation_request` items from enterprise and emit `tool_call` bus events with `triggered_confirmation=True`, `confirmation_message`, `result=None`, `success=None`
- Frontend: `_onToolCall` in app.js stores `triggered_confirmation` and `confirmation_message`; fields round-trip through existing `hydrateTrace` spread automatically
- ToolCallDetail: Confirmation Info tab uses `isVisible="hasConfirmation"` (hidden by default, visible when confirmation triggered), renders HTML message via `t-out` with a Bootstrap `text-bg-warning` badge
- Header badge: handles `success === null` state with "Pending" label in warning color

## Task Commits

Each task was committed atomically:

1. **Task 1: Backend -- detect confirmation events and emit enriched tool_call bus events** - `d1ea9a5` (feat)
2. **Task 2: Frontend -- store confirmation fields and render in Confirmation Info tab** - `99574e1` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `ai_debug/models/ai_session.py` - Added tool_calls_by_id lookup and elif branch for tool_confirmation_request detection
- `ai_debug/static/src/app/app.js` - Store triggered_confirmation and confirmation_message in _onToolCall handler
- `ai_debug/static/src/app/detail/tc_detail.js` - Added hasConfirmation getter
- `ai_debug/static/src/app/detail/tc_detail.xml` - Replaced placeholder confirmation tab with real content; added Pending header badge

## Decisions Made

- Used `t-out` instead of `t-esc` for confirmation_message because it contains HTML from `make_batch_update_preview` (safe server-generated HTML). Using `t-esc` would render the HTML as escaped text.
- Tab is completely hidden when no confirmation was triggered — no "no confirmation requested" fallback message needed since the tab disappears entirely via `isVisible="hasConfirmation"`.
- `success === null` (not `undefined` or `false`) is the signal for pending/confirmation-triggered state, since existing tool results always have boolean success values.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Confirmation observability is complete: enterprise tools that trigger user confirmation will now appear in the AI Debugger with their confirmation message visible
- The tab stays hidden for all normal tool calls (no noise in the UI)
- Pending/Success/Failed status badges correctly distinguish all three tool call states

---
*Phase: quick-25*
*Completed: 2026-02-22*
