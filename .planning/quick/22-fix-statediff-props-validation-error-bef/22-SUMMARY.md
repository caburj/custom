---
phase: 22-fix-statediff-props-validation-error-bef
plan: 01
type: quick-fix
tags: [owl, props-validation, state-diff, bugfix]
dependency_graph:
  requires: []
  provides: [BUGFIX-22]
  affects: [ai_debug/static/src/app/detail/iter_detail.xml, ai_debug/static/src/app/detail/state_diff.js]
tech_stack:
  added: []
  patterns: [OWL conditional rendering, OWL prop type union]
key_files:
  modified:
    - ai_debug/static/src/app/detail/iter_detail.xml
    - ai_debug/static/src/app/detail/state_diff.js
decisions:
  - Guard at the template level (t-if) is the primary fix; null-accepting prop types are defense-in-depth
metrics:
  duration: ~5min
  completed: 2026-02-22
---

# Quick Task 22: Fix StateDiff Props Validation Error — Summary

**One-liner:** Guard StateDiff with `t-if` in iter_detail.xml so it never mounts with null props, and extend prop type definitions to accept null as defense-in-depth.

## What Was Built

The StateDiff component was being unconditionally mounted even when `stateBefore` and `stateAfter` were both `null` (iterations with no tool calls). In OWL `debug=assets` mode, strict prop validation threw an OwlError because the declared prop type was `Object` but the received value was `null`.

Two changes fix this:

1. **`iter_detail.xml`** — Conditionally render StateDiff only when at least one of the state props is truthy. The `|| {}` fallback ensures the props are always plain objects when the component does mount. The `t-else` branch shows "No state data available." directly in the template (rather than inside StateDiff), which avoids the mount entirely.

2. **`state_diff.js`** — Extended prop type definitions from `{ type: Object }` to `{ type: [Object, { value: null }] }`. This is a defense-in-depth measure: if any other caller ever passes null, OWL will accept it rather than throw.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Guard StateDiff rendering and fix prop types | b4cf5b6 | iter_detail.xml, state_diff.js |

## Verification

- Clicking State Diff tab on an iteration with no tool calls shows "No state data available." with no console errors.
- Clicking State Diff tab on an iteration with tool calls still shows the diff grid or "No state changes detected" as before.
- No OwlError about invalid props in debug=assets mode.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `ai_debug/static/src/app/detail/iter_detail.xml` — modified, contains `t-if="stateBefore or stateAfter"`
- `ai_debug/static/src/app/detail/state_diff.js` — modified, contains `{ value: null }`
- Commit b4cf5b6 exists
