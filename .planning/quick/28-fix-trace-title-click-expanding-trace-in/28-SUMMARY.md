---
phase: quick-28
plan: "01"
subsystem: ai_debug
tags: [bugfix, event-propagation, sidebar, trace]
dependency_graph:
  requires: []
  provides: [QUICK-28]
  affects: [ai_debug/static/src/app/app.js]
tech_stack:
  added: []
  patterns: [stopPropagation to prevent event bubbling]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
decisions:
  - stopPropagation added before the early-return guard so it fires unconditionally, even when dialog or query is absent
metrics:
  duration: "< 5 minutes"
  completed: "2026-02-24"
  tasks_completed: 1
  files_modified: 1
---

# Phase quick-28 Plan 01: Fix Trace Title Click Expanding Trace Summary

**One-liner:** Added `ev.stopPropagation()` to `showFullQuery` so clicking the trace title opens the dialog without expanding the trace via the parent `selectItem` handler.

## What Was Done

In `ai_debug/static/src/app/app.js`, the `showFullQuery` method was updated:
- Renamed the unused `_ev` parameter to `ev` (it is now used)
- Added `ev.stopPropagation()` as the first statement in the method body

This prevents the click event from bubbling from the inner `ai-tree-query-title` span up to the parent `ai-tree-label` span, which calls `selectItem('trace')`. `selectItem` unconditionally sets `trace.expanded = true`, which caused collapsed traces to expand whenever the title was clicked.

The XML template was already correctly passing `ev` to `showFullQuery` via `t-on-click="(ev) => this.showFullQuery(ev, node.trace.user_query)"` — no template changes were needed.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Stop click propagation in showFullQuery | 5bec7dc |

## Deviations from Plan

None — plan executed exactly as written.

## Verification

- `grep -n "stopPropagation" ai_debug/static/src/app/app.js` returns line 394 inside `showFullQuery`
- `grep -n "_ev" ai_debug/static/src/app/app.js` returns no matches for `showFullQuery` (parameter renamed to `ev`)
- No other methods in app.js were modified

## Self-Check: PASSED

- [x] `ai_debug/static/src/app/app.js` modified with stopPropagation
- [x] Commit 5bec7dc exists
