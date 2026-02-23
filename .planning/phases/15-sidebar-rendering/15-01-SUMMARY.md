---
phase: 15-sidebar-rendering
plan: 01
subsystem: ui
tags: [owl, sidebar, tree, subagents, scss, computed-getter]

# Dependency graph
requires:
  - phase: 13-python-instrumentation-and-bus-event-handling
    provides: parent_trace_id and parent_tool_call_id fields on trace objects, enabling child trace detection
provides:
  - sidebarNodes computed getter — flat depth-first node descriptor array for OWL t-foreach
  - _collectTraceNodes recursive helper — depth+1 for child subagent traces
  - rootTracesCount getter — count of non-subagent traces for correct checkbox logic
  - Single t-foreach sidebar template over sidebarNodes (replaces 3-level nested loops)
  - VS Code-style vertical guide lines via ::before pseudo-element on ai-tree-has-guide rows
  - Iteration rows with cycle icon and tool call count; tool call rows with arrow icon
affects: [phase-16-color-assignment, sidebar-visual-qa]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "sidebarNodes computed getter pattern: JS builds flat node array, OWL renders single t-foreach — avoids recursive OWL component anti-pattern"
    - "Depth-first tree traversal: _collectTraceNodes emits trace/iter/tc nodes; child subagent traces increment depth+1"
    - "Flat-within-trace rule: iteration and tool call rows share same depth as owning trace, only subagent traces add depth"
    - "CSS custom property --ai-depth on each row for guide line ::before left calculation"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss

key-decisions:
  - "Flat node array via JS getter (not recursive OWL components) — OWL doesn't support template recursion"
  - "Child trace matching by tc.call_id (LLM call_id field), not UUID key — parent_tool_call_id on child traces is the LLM call_id"
  - "Iteration rows and tool call rows share same depth value — only subagent trace rows increment depth"
  - "Checkboxes only on depth===0 trace rows — subagent traces excluded from select-all/delete operations"
  - "COLR-03/04/05 color requirements deferred — no color work in this plan per CONTEXT.md decision"

patterns-established:
  - "sidebarNodes getter: reactive reads on this.traces and nested Maps inside getter ensures OWL tracks changes"
  - "Guide lines: --ai-depth CSS custom property + ::before pseudo-element avoids extra DOM nodes"
  - "Tool call status: null-safe tc.success === false check distinguishes 'not yet completed' from explicit failure"

requirements-completed: [TREE-01, TREE-02, TREE-03, TREE-04]

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 15 Plan 01: Sidebar Rendering Summary

**Single flat OWL t-foreach over computed sidebarNodes getter replaces 3-level nested loops, enabling arbitrary-depth subagent trace nesting with VS Code-style guide lines**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-23T00:13:46Z
- **Completed:** 2026-02-23T00:16:06Z
- **Tasks:** 2 of 3 (Task 3 is human-verify checkpoint)
- **Files modified:** 3

## Accomplishments

- `sidebarNodes` getter computes a flat depth-first node array; `_collectTraceNodes` recurses with `depth+1` for child subagent traces, satisfying TREE-01 through TREE-04
- Sidebar XML template replaced: single `t-foreach="sidebarNodes"` with three `t-if/elif` branches for trace/iter/tc row types, inline depth-based `padding-left` for arbitrary nesting
- SCSS updated: removed static `level-0/1/2` classes, added `ai-tree-trace-row`, guide-line `::before` styles, and iteration/tool-call icon styles
- Checkbox logic fixed: `allChecked` and `toggleSelectAll` use `rootTracesCount` so subagent traces don't inflate denominator or get bulk-selected

## Task Commits

Each task was committed atomically:

1. **Task 1: sidebarNodes getter, _collectTraceNodes helper, checkbox fixes** - `4d3d99e` (feat)
2. **Task 2: Rewrite sidebar template + SCSS guide lines** - `875eb8f` (feat)

Task 3 (human-verify) is a checkpoint — awaiting visual confirmation before plan metadata commit.

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - Added `sidebarNodes` getter, `_collectTraceNodes` recursive helper, `rootTracesCount` getter; fixed `allChecked` and `toggleSelectAll` to exclude subagent traces
- `ai_debug/static/src/app/app.xml` - Replaced 3-level nested `t-foreach` with single flat loop over `sidebarNodes`; added trace/iter/tc row templates with depth-based inline padding
- `ai_debug/static/src/app/app.scss` - Removed `level-0/1/2` classes; added `ai-tree-trace-row`, `ai-tree-has-guide` guide-line styles, `ai-tree-iter-icon`/`ai-tree-tc-icon` icon styles; added `position: relative` to `.ai-tree-row`

## Decisions Made

- Child trace matching uses `tc.call_id` (LLM call_id field) rather than the UUID key (`tcId`). The `parent_tool_call_id` on child traces equals the LLM `call_id`, not the UUID we assign.
- Iteration and tool call rows share the same `depth` value as their owning trace. Only subagent trace rows increment to `depth + 1`. This is the "flat within trace" rule (TREE-03).
- Checkboxes render only on `node.depth === 0` rows. Subagent traces at depth >= 1 have no checkbox and cannot be individually checked.
- COLR-03, COLR-04, COLR-05 requirements are listed in the plan for traceability only — color assignment is deferred to Phase 14 per CONTEXT.md.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. The `! grep level-N` verification command produced exit 1 due to a comment in SCSS mentioning "level-0" — the actual CSS rules were removed correctly, only a comment referenced the old name.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Task 3 (human-verify checkpoint) must be completed before plan is fully done
- Visual verification: confirm nested subagent traces indent under parent tool calls, guide lines appear, collapse works recursively, checkbox select-all only targets root traces
- Phase 16 (color assignment) can build on the `sidebarNodes` node descriptor structure to add per-agent color badges

---
*Phase: 15-sidebar-rendering*
*Completed: 2026-02-23*
