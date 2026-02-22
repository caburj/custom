---
phase: quick-20
plan: 01
subsystem: ai_debug/frontend
tags: [ux, sidebar, owl-template, quick-fix]
dependency_graph:
  requires: []
  provides: [conditional-chevron-on-iteration-rows]
  affects: [ai_debug/static/src/app/app.xml]
tech_stack:
  added: []
  patterns: [owl-t-if-t-else, conditional-rendering]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.xml
decisions:
  - "Use t-if/t-else on the same two span variants already in the codebase — chevron span and ai-tree-chevron-placeholder — so no new CSS or JS is required"
metrics:
  duration: "< 5 minutes"
  completed: "2026-02-22"
  tasks_completed: 1
  files_changed: 1
---

# Quick Task 20: Hide Chevron Icon on Iteration Rows That Have No Tool Calls — Summary

**One-liner:** Added `t-if="iteration.toolCalls.size > 0"` conditional so iteration rows without tool call children display a placeholder spacer instead of a misleading expand arrow.

## What Was Done

Modified `ai_debug/static/src/app/app.xml` to wrap the Level-1 iteration chevron in a `t-if`/`t-else` pair:

- When `iteration.toolCalls.size > 0`: renders the existing `ai-tree-chevron` span with its click handler and `expanded` class binding — unchanged behavior.
- When `iteration.toolCalls.size === 0`: renders `ai-tree-chevron-placeholder` — a 16x16 invisible spacer already used by Level-2 tool call leaf rows, maintaining horizontal alignment.

No changes to `app.js` or `app.scss` — the `ai-tree-chevron-placeholder` class already provided the correct spacer style.

## Commits

| Task | Commit  | Description                                                  |
|------|---------|--------------------------------------------------------------|
| 1    | 7d87b5f | feat(quick-20): conditionally hide chevron on iteration rows with no tool calls |

## Verification Criteria Met

- Iteration rows with `toolCalls.size === 0` show no arrow icon (placeholder rendered)
- Iteration rows with `toolCalls.size > 0` show a clickable chevron that toggles child visibility
- All iteration labels remain horizontally aligned (placeholder occupies same 16px width as chevron)
- No JS console errors (pure XML template change, no runtime logic added)

## Deviations from Plan

None — plan executed exactly as written.
