---
phase: 06-sidebar-tree
plan: 01
subsystem: ui
tags: [owl, reactive, bus, sidebar, tree, scss]

# Dependency graph
requires:
  - phase: 05-bus-instrumentation
    provides: "four bus event types (new_trace, iteration, tool_call, loop_end) with trace_id/iteration_id/tool_call_id payload fields"

provides:
  - "Reactive trace store (reactive Map) driven by bus events"
  - "Three-level sidebar tree: Loop > Iteration > Tool Call"
  - "Click-to-select with stable selection under concurrent bus updates (SIDE-05)"
  - "Chevron expand/collapse independent of selection"
  - "Running/completed visual indicators (pulse dot, checkmark, X)"
  - "Traces header with clear/trash button"
  - "Ancestor tint getters for breadcrumb highlighting"
  - "Auto-scroll via onPatched + _needsScroll flag"
  - "Flash animation for newly arrived loop entries"

affects: [07-detail-panel, 06-02]

# Tech tracking
tech-stack:
  added: [reactive (from @odoo/owl), onPatched (from @odoo/owl), useRef (from @odoo/owl)]
  patterns:
    - "reactive(new Map()) for top-level trace store — NOT inside useState"
    - "Nested reactive Maps: traces -> iterations -> toolCalls"
    - "Bus handlers write only to trace Maps, never to selection state (SIDE-05)"
    - "onPatched with _needsScroll flag for post-render scroll (DOM not available in bus handlers)"
    - "[...map.keys()].reverse() for latest-on-top iteration display"
    - "toggleExpand(id, 'trace') vs toggleExpand(traceId, iterationId) unified signature"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss

key-decisions:
  - "New loops start expanded (locked decision from CONTEXT.md)"
  - "Clicking a loop selects AND expands it (locked decision from CONTEXT.md)"
  - "Iterations display in reverse chronological order via .reverse() on Map keys"
  - "Loops display in insertion order (oldest first) — not reversed; plan spec uses [...traces.keys()] without reverse"
  - "toggleExpand unified: (id, 'trace') or (traceId, iterationId) — type string vs UUID string distinguishes the two calls"
  - "Flash animation applied only to new loop arrivals (_flashId in _onNewTrace, not _onIteration/_onToolCall)"

patterns-established:
  - "Reactive Map bus-driven tree: reactive(new Map()) + bus handlers that only write to Maps"
  - "Stable selection: selectedId/selectedType in useState; bus handlers never touch them"
  - "Ancestor getters (selectedTraceId, selectedIterationId) computed from reactive Map traversal"

requirements-completed: [SIDE-01, SIDE-02, SIDE-03, SIDE-04, SIDE-05]

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 6 Plan 01: Sidebar Tree Summary

**OWL reactive Map sidebar with Loop > Iteration > Tool Call tree, bus-driven real-time updates, and stable click-to-select (SIDE-05)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-21T18:03:04Z
- **Completed:** 2026-02-21T18:05:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Rewrote `app.js` with `reactive(new Map())` trace store, four typed bus event handlers, and selection/expand/clear methods
- Built three-level XML tree template (Loop > Iteration > Tool Call) with chevron expand, selection highlighting, and ancestor tinting
- Added comprehensive SCSS tree styles: 34px rows, level indentation, chevron rotation, status icons, flash animation

## Task Commits

Each task was committed atomically:

1. **Task 1: Reactive trace store, bus handlers, and selection methods** - `dbd349c` (feat)
2. **Task 2: Three-level tree template and all sidebar styles** - `84cd993` (feat)

**Plan metadata:** (final commit — TBD)

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - Added reactive Map store, four bus handlers, selectItem/toggleExpand/clearAll, ancestor getters, onPatched scroll/flash
- `ai_debug/static/src/app/app.xml` - Three-level tree template with chevrons, labels, status indicators, Traces header, conditional detail panel
- `ai_debug/static/src/app/app.scss` - Tree row styles, selection highlight, chevron rotation, indentation levels, status icons, flash animation

## Decisions Made

- **Loop display order:** Loops display in insertion order (oldest first at top) — `[...traces.keys()]` without `.reverse()`. The plan spec matched this; iterations use `.reverse()` per locked decision.
- **toggleExpand signature:** Unified as `(id, 'trace')` for loops or `(traceId, iterationId)` for iterations — the second arg is either a literal string `'trace'` or a UUID, making the two call forms unambiguous.
- **Flash effect scope:** Only new loop arrivals get the flash animation (`_flashId` set in `_onNewTrace`). Individual iterations and tool calls do not flash to avoid visual noise on tool batches.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. All changes are frontend JS/XML/SCSS.

## Next Phase Readiness

- Sidebar tree is fully functional: bus events populate the tree in real time, three levels expand/collapse, click-to-select works, selection is stable under concurrent bus updates
- `t-ref="sidebar"` is on the `<aside>` element, ready for Plan 02 auto-scroll enhancements
- `state.selectedId` and `state.selectedType` are wired and displayed as placeholder in the detail panel
- Phase 7 (detail panel) can read `state.selectedId` and `state.selectedType` to render appropriate content

---
*Phase: 06-sidebar-tree*
*Completed: 2026-02-21*
