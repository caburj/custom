---
phase: quick-35
plan: 01
subsystem: ai_debug sidebar
tags: [template, iteration-row, duration, tokens, metrics]
dependency_graph:
  requires: []
  provides: [iteration-row-actual-duration, iteration-row-token-counts]
  affects: [ai_debug/static/src/app/app.xml]
tech_stack:
  added: []
  patterns: [owl-template, t-if-conditional-display]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.xml
decisions:
  - "Use node.iter.duration_ms directly instead of getIterationDuration() — backend provides actual LLM call time, wall-clock delta was misleading"
  - "Keep getIterationDuration() method in app.js — removing it from the template doesn't break callers"
metrics:
  duration: "2 min"
  completed: "2026-02-24"
  tasks: 1
  files: 1
---

# Quick Task 35: Show Actual Iteration Duration and In/Out Tokens Summary

## One-liner

Replaced wall-clock delta duration with actual `duration_ms` LLM call time and added per-iteration input/output token counts with directional arrows.

## What Was Built

Updated the sidebar iteration row template in `app.xml` to:

1. Show the actual LLM call duration from `node.iter.duration_ms` instead of the computed wall-clock delta from `getIterationDuration()`. The old approach was misleading because it included tool execution time and bus latency.

2. Show per-iteration input/output token counts (e.g., `3.4k↑ 1.2k↓`) after the duration, using the same directional arrow format established in the trace meta-line. Tokens are only shown when `node.iter.tokens` exists and has nonzero input or output values.

3. Preserve the pulsing dot for running iterations that don't yet have a `duration_ms`.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Replace wall-clock duration with actual duration_ms and add token display | 4e8f602 | ai_debug/static/src/app/app.xml |

## Verification

- `getIterationDuration` - NOT present in app.xml (removed from template)
- `node.iter.duration_ms` - 2 matches in app.xml (condition + display)
- `node.iter.tokens` - 2 matches in app.xml (condition + display)
- `formatTokens` in app.xml - 4 matches total (trace rows + new iteration row)

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- File exists: ai_debug/static/src/app/app.xml - FOUND
- Commit 4e8f602 exists - FOUND
