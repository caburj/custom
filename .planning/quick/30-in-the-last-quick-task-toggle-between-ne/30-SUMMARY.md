---
phase: 30-indent-mode-tool-call-nesting
plan: "01"
subsystem: ai_debug-ui
tags: [scss, indentation-mode, visual-hierarchy, css]
dependency_graph:
  requires: [quick-29]
  provides: [indent-mode-hierarchy]
  affects: [ai_debug/static/src/app/app.scss]
tech_stack:
  added: []
  patterns: [scss-for-loop, compound-selectors, padding-left-offsets]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.scss
decisions:
  - CSS-only fix: node.depth values remain flat (correct for SVG mode); per-row-type padding overrides inside .ai-indent-mode provide visual hierarchy without touching JS or XML
  - 16px indent step: one step per sub-row type (iter=+16, tc=+32) matches the existing depth progression cadence
metrics:
  duration: "< 5 minutes"
  completed: "2026-02-24"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 1
---

# Phase 30 Plan 01: Indentation Mode Tool-Call Nesting Summary

**One-liner:** CSS-only per-row-type padding offsets inside `.ai-indent-mode` giving trace < iteration (+16px) < tool call (+32px) visual hierarchy at all depth levels.

## What Was Built

The indentation mode toggle (added in quick task 29) rendered all rows at the same depth — trace, iteration, and tool call rows all shared the same `padding-left` because they all carry the same `node.depth` value (intentionally flat for SVG mode).

This plan adds compound CSS selectors inside `.ai-indent-mode` so that:

- `.ai-tree-iter-row` gets an extra +16px over its trace row
- `.ai-tree-tc-row` gets an extra +32px over its trace row
- At each depth level (0–4), the same relative offsets are maintained via a `@for` loop targeting `.ai-depth-N.ai-tree-*-row` compound selectors

Visual hierarchy at depth 0:
- Trace row: 8px
- Iteration row: 24px
- Tool call row: 40px

At depth 1 (subagent):
- Trace: 24px
- Iteration: 40px
- Tool call: 56px

## Commits

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 1 | Add per-row-type indent offsets in .ai-indent-mode SCSS block | 3d87b6a | ai_debug/static/src/app/app.scss |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- [x] `ai_debug/static/src/app/app.scss` modified with new `.ai-indent-mode` block
- [x] Commit 3d87b6a exists
- [x] No changes to app.js or app.xml
- [x] `.ai-tree-iter-row` present in the updated block
- [x] `.ai-tree-tc-row` present in the updated block
