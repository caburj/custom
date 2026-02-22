---
phase: quick
plan: 23
subsystem: ai_debug/frontend
tags: [refactor, ui, tabs, owl, state-diff]
dependency_graph:
  requires: [quick-22]
  provides: [tc_detail-tabbed-layout, tc_detail-statediff-guard]
  affects: [ai_debug.ToolCallDetail]
tech_stack:
  added: []
  patterns: [OWL Notebook slots, t-if guard on nullable props]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/detail/tc_detail.xml
    - ai_debug/static/src/app/detail/tc_detail.js
decisions:
  - "Moved error banner above Notebook (between header and Notebook) to keep it always visible regardless of active tab"
  - "Used same StateDiff guard pattern from quick-22/iter_detail: t-if with || {} fallback"
metrics:
  duration: ~10 minutes
  completed: 2026-02-22
---

# Quick Task 23: Refactor ToolCallDetail to 4-tab Notebook with StateDiff guard

**One-liner:** Replaced stacked Arguments/Result + 2-tab Notebook layout with a single 4-tab Notebook (Arguments, Result, State Diff, Confirmation Info) and applied t-if guard on StateDiff to prevent OWL props validation errors.

## What Was Done

### Task 1 — Add stateBefore/stateAfter getters (commit: f33939e)

Added two getter properties to `ToolCallDetail` class in `tc_detail.js`, following the same pattern used in `IterationDetail`:

```js
get stateBefore() {
    return this.props.toolCall.state_before;
}

get stateAfter() {
    return this.props.toolCall.state_after;
}
```

These expose the tool call's raw state values to the template for use in the t-if guard.

### Task 2 — Refactor tc_detail.xml to single Notebook with 4 tabs (commit: af74663)

Rewrote the template body:

- **Removed** the two stacked sections (Arguments, Result) that appeared above the old 2-tab Notebook
- **Moved** the error banner between the header and the Notebook (always visible, tab-independent)
- **Replaced** the 2-tab Notebook with a single 4-tab Notebook containing:
  - Arguments tab: `<JsonTree>` with `<CopyButton>`
  - Result tab: conditional `<JsonTree>` or text (with long-text expansion), with `<CopyButton>`
  - State Diff tab: `<StateDiff>` guarded by `t-if="stateBefore or stateAfter"` with `|| {}` fallback, or "No state data available" message
  - Confirmation Info tab: unchanged placeholder message

## Verification Results

| Check | Result |
|-------|--------|
| XML well-formed | PASS |
| Single Notebook element | PASS (1) |
| 4 t-set-slot children | PASS (4) |
| 4 ai-detail-section divs (all inside Notebook) | PASS (4) |
| StateDiff t-if guard present | PASS |
| CopyButton in Arguments and Result tabs | PASS (2 occurrences) |
| JsonTree for args and object results | PASS (3 occurrences: args, result-object, result-else) |
| resultIsLong text expansion handler | PASS (1 occurrence) |

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `ai_debug/static/src/app/detail/tc_detail.js` modified and committed (f33939e)
- [x] `ai_debug/static/src/app/detail/tc_detail.xml` modified and committed (af74663)
- [x] All 7 overall verification checks passed
