---
phase: 15-sidebar-rendering
plan: "01"
subsystem: ui
tags: [owl, sidebar, tree, subagents, scss, computed-getter, indexeddb]

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
  - IDB serialization fix — parent_trace_id, parent_tool_call_id, session_id persisted in serializeTrace()
affects: [phase-14-data-model-idb-color, sidebar-visual-qa]

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
    - ai_debug/static/src/app/db.js

key-decisions:
  - "Flat node array via JS getter (not recursive OWL components) — OWL doesn't support template recursion"
  - "Child trace matching by tc.call_id (LLM call_id field), not UUID key — parent_tool_call_id on child traces is the LLM call_id"
  - "Iteration rows and tool call rows share same depth value — only subagent trace rows increment depth"
  - "Checkboxes only on depth===0 trace rows — subagent traces excluded from select-all/delete operations"
  - "COLR-03/04/05 color requirements deferred — no color work in this plan per CONTEXT.md decision"
  - "Iteration rows default expanded=true so subagent traces are immediately visible without extra clicks"
  - "serializeTrace() must persist parent_trace_id, parent_tool_call_id, session_id — omitting them silently drops parent linkage on page refresh"

patterns-established:
  - "sidebarNodes getter: reactive reads on this.traces and nested Maps inside getter ensures OWL tracks changes"
  - "Guide lines: --ai-depth CSS custom property + ::before pseudo-element avoids extra DOM nodes"
  - "Tool call status: null-safe tc.success === false check distinguishes 'not yet completed' from explicit failure"
  - "IDB serialize completeness: every field used for parent linkage or tree structure must be included in serializeTrace()"

requirements-completed: [TREE-01, TREE-02, TREE-03, TREE-04]

# Metrics
duration: 65min
completed: 2026-02-23
---

# Phase 15 Plan 01: Sidebar Rendering Summary

**Single flat OWL t-foreach over computed sidebarNodes getter replaces 3-level nested loops, enabling arbitrary-depth subagent trace nesting with VS Code-style guide lines and IDB-persistent parent linkage**

## Performance

- **Duration:** ~65 min (including checkpoint verification and post-checkpoint fixes)
- **Started:** 2026-02-23T20:34:00Z
- **Completed:** 2026-02-23T21:38:00Z
- **Tasks:** 3 of 3 complete
- **Files modified:** 4

## Accomplishments

- `sidebarNodes` getter computes a flat depth-first node array; `_collectTraceNodes` recurses with `depth+1` for child subagent traces, satisfying TREE-01 through TREE-04
- Sidebar XML template replaced: single `t-foreach="sidebarNodes"` with three `t-if/elif` branches for trace/iter/tc row types, inline depth-based `padding-left` for arbitrary nesting
- SCSS updated: removed static `level-0/1/2` classes, added `ai-tree-trace-row`, guide-line `::before` styles, and iteration/tool-call styles
- Checkbox logic fixed: `allChecked` and `toggleSelectAll` use `rootTracesCount` so subagent traces don't inflate denominator or get bulk-selected
- Fixed `serializeTrace()` in db.js to include `parent_trace_id`, `parent_tool_call_id`, and `session_id` — nested trace hierarchy now survives page refresh

## Task Commits

Each task was committed atomically:

1. **Task 1: sidebarNodes getter, _collectTraceNodes helper, checkbox fixes** - `4d3d99e` (feat)
2. **Task 2: Rewrite sidebar template + SCSS guide lines** - `875eb8f` (feat)
3. **Task 3: Visual verification + post-checkpoint fixes** - `a7ac163` (fix)

**Plan metadata:** `fd73c8d` (docs: complete plan paused at checkpoint)

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - Added `sidebarNodes` getter, `_collectTraceNodes` recursive helper, `rootTracesCount` getter; fixed `allChecked` and `toggleSelectAll` to exclude subagent traces; changed iteration default expanded to true
- `ai_debug/static/src/app/app.xml` - Replaced 3-level nested `t-foreach` with single flat loop over `sidebarNodes`; added trace/iter/tc row templates with depth-based inline padding; removed row icons per user feedback
- `ai_debug/static/src/app/app.scss` - Removed `level-0/1/2` classes; added `ai-tree-trace-row`, `ai-tree-has-guide` guide-line styles; added `position: relative` to `.ai-tree-row`
- `ai_debug/static/src/app/db.js` - Fixed `serializeTrace()` to include `parent_trace_id`, `parent_tool_call_id`, and `session_id` in IDB write — previously omitted fields caused nested traces to appear at root level after page refresh

## Decisions Made

- Child trace matching uses `tc.call_id` (LLM call_id field) rather than the UUID key (`tcId`). The `parent_tool_call_id` on child traces equals the LLM `call_id`, not the UUID we assign.
- Iteration and tool call rows share the same `depth` value as their owning trace. Only subagent trace rows increment to `depth + 1`. This is the "flat within trace" rule (TREE-03).
- Checkboxes render only on `node.depth === 0` rows. Subagent traces at depth >= 1 have no checkbox and cannot be individually checked.
- COLR-03, COLR-04, COLR-05 requirements are listed in the plan for traceability only — color assignment is deferred to Phase 14 per CONTEXT.md.
- Iteration rows default to expanded=true so subagent traces under those iterations are immediately visible.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed serializeTrace() omitting parent linkage fields**
- **Found during:** Task 3 (visual verification checkpoint) — nested traces lost parent linkage on page refresh
- **Issue:** `serializeTrace()` in db.js did not write `parent_trace_id`, `parent_tool_call_id`, or `session_id` to IDB. After page refresh, these fields were undefined so all traces appeared as root traces, collapsing the hierarchy
- **Fix:** Added the three fields to the serialized object in `serializeTrace()` in db.js
- **Files modified:** `ai_debug/static/src/app/db.js`
- **Verification:** Confirmed during visual checkpoint that nested traces persisted correctly across page refresh
- **Committed in:** `a7ac163` (Task 3 commit)

**2. [User feedback] Removed iteration cycle icon and tool call arrow icon**
- **Found during:** Task 3 checkpoint — user requested cleaner hierarchy readability without row icons
- **Fix:** Removed the `&#x21BA;` cycle icon span from iteration rows and the `&#x2192;` arrow icon span from tool call rows in the template
- **Files modified:** `ai_debug/static/src/app/app.xml`
- **Committed in:** `a7ac163` (Task 3 commit)

**3. [User feedback] Changed iteration expanded default from false to true**
- **Found during:** Task 3 checkpoint — user requested subagent traces be immediately visible without expand clicks
- **Fix:** Changed the default `expanded` value for new iteration objects from `false` to `true` in the `_onNewIteration` handler in app.js
- **Files modified:** `ai_debug/static/src/app/app.js`
- **Committed in:** `a7ac163` (Task 3 commit)

---

**Total deviations:** 3 (1 auto-fix bug, 2 user-requested adjustments during checkpoint)
**Impact on plan:** The db.js fix was necessary for correctness — parent linkage must survive page refresh. The icon removal and expanded-default change are minor UX improvements requested by the user at visual verification. No scope creep.

## Issues Encountered

The `serializeTrace()` omission was a pre-existing gap in db.js that only became visible once the sidebar tree began rendering nested traces. It was not introduced by this plan's changes but was discovered and fixed during verification.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 15 Plan 01 complete — TREE-01 through TREE-04 all satisfied
- COLR-03, COLR-04, COLR-05 (colored left borders, agent legend, color chip) remain deferred pending Phase 14 color assignment infrastructure
- Phase 14 (Data Model, IDB Schema, Color Assignment) is the blocking next step — it must deliver `agentColors` before Phase 15 color display can proceed
- The `sidebarNodes` getter is ready to incorporate `agentColors` lookup once Phase 14 ships

---
*Phase: 15-sidebar-rendering*
*Completed: 2026-02-23*

## Self-Check: PASSED

- SUMMARY.md: FOUND at .planning/phases/15-sidebar-rendering/15-01-SUMMARY.md
- Commit 4d3d99e (Task 1): FOUND
- Commit 875eb8f (Task 2): FOUND
- Commit a7ac163 (Task 3): FOUND
