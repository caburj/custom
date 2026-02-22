---
phase: quick-14
plan: 01
subsystem: ai_debug/json_tree
tags: [ui, owl, json-tree, recursive, expand-collapse, alt-click]
dependency_graph:
  requires: []
  provides: [alt-click-recursive-json-tree-toggle]
  affects: [ai_debug/detail/json_tree]
tech_stack:
  added: []
  patterns: [owl-prop-signaling, forceVersion-counter-pattern, mount-aware-force-propagation]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/detail/json_tree.js
    - ai_debug/static/src/app/detail/json_tree.xml
decisions:
  - "Use Alt/Option key (ev.altKey) for recursive toggle — Ctrl/Cmd was already used at the old component path; Alt is the natural Option key equivalent on Mac for expand-all UX patterns"
  - "Re-apply the proven forceCollapsed/forceVersion prop-signaling pattern from quick tasks #3 and #5 to the new component path"
  - "Mount-aware propagation (setup() checks forceCollapsed on init) ensures freshly mounted children during recursive expand receive the force signal"
  - "Reset childForceCollapsed to undefined on normal clicks to prevent stale force state from prior Alt+clicks"
metrics:
  duration: "5 min"
  completed: "2026-02-22"
  tasks_completed: 2
  files_modified: 2
---

# Quick Task 14: Alt/Option+Click Recursive JSON Tree Toggle — Summary

**One-liner:** Added Alt/Option+click recursive expand/collapse to JsonTree at the new component path via the proven forceCollapsed/forceVersion prop-signaling pattern with mount-aware initialization.

## What Was Built

The `JsonTree` OWL component at `ai_debug/static/src/app/detail/json_tree.js` now supports two toggle modes:

- **Normal click:** Toggles only the clicked node (existing behavior, unchanged).
- **Alt+click (Option+click on Mac):** Recursively expands or collapses the clicked node and all descendants.

## Implementation

### Propagation pattern

Each node signals its direct children by incrementing its own `childForceVersion` counter. Children react via `onWillUpdateProps` — when `forceVersion` changes, they update their own `collapsed` state and increment their own `childForceVersion`, cascading the signal down the tree.

For freshly mounted children (the case when expanding a collapsed node), `setup()` checks `forceCollapsed` at init time and sets both the initial `expanded` state and the `childForceCollapsed`/`childForceVersion` to propagate the signal further down.

### JS changes (`json_tree.js`)

- Added `onWillUpdateProps` to the `@odoo/owl` import.
- Added `forceCollapsed: Boolean (optional)` and `forceVersion: Number (optional)` to `static props`.
- Expanded `state` to include `childForceCollapsed: undefined` and `childForceVersion: 0`.
- `setup()` checks `typeof forceCollapsed === "boolean"` at mount; if active, uses it as initial `expanded` and pre-initializes `childForceCollapsed`/`childForceVersion: 1` for propagation.
- Added `onWillUpdateProps` callback: detects parent version bump, updates own `expanded`, and bumps `childForceVersion` to propagate downward.
- Updated `toggle(ev)`: on `ev.altKey`, sets `childForceCollapsed = !expanded` and increments `childForceVersion`; on normal click, resets `childForceCollapsed = undefined`.

### Template changes (`json_tree.xml`)

- Added `forceCollapsed="state.childForceCollapsed"` and `forceVersion="state.childForceVersion"` to the child `<JsonTree>` element inside the `t-foreach` loop.

## Tasks Completed

| # | Task | Commit |
|---|------|--------|
| 1 | Add Alt+click recursive expand/collapse logic to json_tree.js | 84909ee |
| 2 | Update json_tree.xml to pass force props to child JsonTree | 46dd86c |

## Verification

Manual verification steps (from plan):
1. Open AI Debugger and navigate to a detail panel with nested JSON data.
2. Normal click on a collapsed node's toggle arrow: only that node expands.
3. Normal click on an expanded node: only that node collapses.
4. Alt+click (Option+click on Mac) on a collapsed node: node and all descendants recursively expand.
5. Alt+click on an expanded node: node and all descendants recursively collapse.
6. After recursive expand, normal-click a single child: only that child toggles independently.
7. After recursive collapse, Alt+click to expand again: all descendants expand correctly.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- FOUND: ai_debug/static/src/app/detail/json_tree.js
- FOUND: ai_debug/static/src/app/detail/json_tree.xml
- FOUND: .planning/quick/14-add-alt-option-click-recursive-expand-co/14-SUMMARY.md
- FOUND commit: 84909ee (Task 1)
- FOUND commit: 46dd86c (Task 2)
