---
phase: 06-sidebar-tree
plan: 02
subsystem: ui
tags: [owl, animation, scss, scroll, sidebar, css]

# Dependency graph
requires:
  - phase: 06-01
    provides: "Reactive sidebar tree with Loop > Iteration > Tool Call hierarchy, onPatched scroll/flash hooks, data-node-id attributes"

provides:
  - "Iteration duration computed and displayed in sidebar labels (e.g. 'Iteration 3 · 2.1s')"
  - "Tiny pulse dot for the currently-running iteration (last in a running trace)"
  - "Slide-in animation (0.15s) for newly inserted tree rows via OWL t-key stable-ID pattern"
  - "Pinned Traces header with scrollable .ai-tree-content below it"
  - "selection priority: animation:none on .selected rows suppresses re-animation on patch"

affects: [07-detail-panel]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "getIterationDuration: insertion-order Map keys to compute iteration delta or loop end delta"
    - "_formatDuration: ms → '150ms' | '2.1s' | '1m 5s' display format"
    - "Pinned header pattern: outer aside overflow:hidden + inner .ai-tree-content flex:1 overflow-y:auto"
    - "OWL slide-in trick: animation on .ai-tree-row fires only for new DOM nodes (t-key=stable-ID)"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss

key-decisions:
  - "t-ref='sidebar' moved from <aside> to inner <div class='ai-tree-content'> so scrollIntoView targets the scrollable area, not the full sidebar"
  - "Running iteration indicator: tiny pulse dot (6px) shown inline in label when trace.status==='running' and iterationId is the last Map key"
  - "animation:none on .selected suppresses slide-in re-animation for the selected row on each reactive patch"

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 6 Plan 02: Visual Polish Summary

**Iteration duration display, slide-in/flash animations, pinned header, running iteration pulse dot — real-time visual polish for the sidebar tree**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-21T18:08:16Z
- **Completed:** 2026-02-21T18:10:07Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `getIterationDuration()` and `_formatDuration()` methods to compute and format iteration timing from Map insertion order
- Updated XML iteration label to show computed duration or a tiny pulse dot (for the active running iteration)
- Restructured sidebar XML: pinned `.ai-tree-header` + scrollable `.ai-tree-content` with `t-ref="sidebar"` moved to the inner div
- Added `@keyframes ai-tree-slide-in` applied to all `.ai-tree-row` elements (fires only for new DOM nodes via OWL's stable t-key pattern)
- Added `.ai-debug-pulse-dot.tiny` variant for inline running-iteration indicator
- Added `animation: none` on `.selected` rows to suppress re-animation on each reactive patch
- Changed `.ai-debug-sidebar` from `overflow-y: auto` to `overflow: hidden` to pin the header

## Task Commits

Each task was committed atomically:

1. **Task 1: Iteration duration in JS and XML, pinned header restructure** - `3b268b7` (feat)
2. **Task 2: SCSS animations, tiny pulse dot, scroll isolation** - `f6834f4` (feat)

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - Added `getIterationDuration()` + `_formatDuration()` methods
- `ai_debug/static/src/app/app.xml` - Duration display in iteration labels, tiny pulse dot for running iteration, `.ai-tree-content` wrapper with `t-ref="sidebar"`
- `ai_debug/static/src/app/app.scss` - Slide-in keyframes, `animation:none` on selected, `.ai-debug-pulse-dot.tiny`, `.ai-tree-content` scroll container, `.ai-debug-sidebar` overflow:hidden

## Decisions Made

- **t-ref location:** Moved `t-ref="sidebar"` from `<aside>` to inner `.ai-tree-content` so `scrollIntoView` in `onPatched` targets the scrollable element, not the full sidebar container. This ensures the header stays pinned while only tree rows scroll.
- **Running iteration indicator:** Show tiny pulse dot only when `trace.status === 'running'` AND `iterationId` equals the last Map key (`[...trace.iterations.keys()].pop()`). This correctly identifies the active iteration without any extra state.
- **Slide-in animation scope:** Applied to all `.ai-tree-row` elements — OWL only creates new DOM nodes for new Map entries (stable t-key=UUID), so existing rows are never re-animated. Selected rows get `animation: none` to prevent the slide-in from re-triggering on each patch cycle.

## Deviations from Plan

None - plan executed exactly as written. Plan 01 had already implemented scroll/flash infrastructure (`onPatched`, `_needsScroll`, `_flashId`, `scrollIntoView`, `data-node-id` attributes, flash keyframes, ancestor tint) so Plan 02 tasks focused on the remaining items: duration computation, slide-in animation, tiny pulse dot, and scroll isolation.

## Issues Encountered

None.

## User Setup Required

None - all changes are frontend JS/XML/SCSS.

## Next Phase Readiness

- Sidebar tree is visually complete: auto-scroll, flash, slide-in, ancestor tint, duration labels, running indicator, pinned header
- `state.selectedId` and `state.selectedType` are wired and ready for Phase 7 (detail panel)
- Phase 7 can read `state.selectedId`/`state.selectedType` and look up full trace/iteration/toolCall data from `this.traces` reactive Map

---
*Phase: 06-sidebar-tree*
*Completed: 2026-02-21*
