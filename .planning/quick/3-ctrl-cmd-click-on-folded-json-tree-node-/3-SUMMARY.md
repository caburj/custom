---
phase: quick
plan: 3
subsystem: ai_debug/json_tree
tags: [ui, owl, json-tree, recursive, expand-collapse]
dependency_graph:
  requires: []
  provides: [recursive-json-tree-toggle]
  affects: [ai_debug/debug_panel]
tech_stack:
  added: []
  patterns: [owl-prop-signaling, forceVersion-counter-pattern]
key_files:
  modified:
    - ai_debug/static/src/debug_panel/json_tree/json_tree.js
    - ai_debug/static/src/debug_panel/json_tree/json_tree.xml
decisions:
  - "Use childForceVersion counter (not parent version passthrough) so each level sees a genuine version change even on repeated toggles"
  - "forceCollapsed is undefined by default so initial render ignores the prop entirely — no spurious collapses on mount"
metrics:
  duration: 5 min
  completed: 2026-02-20
  tasks_completed: 2
  files_modified: 2
---

# Quick Task 3: Ctrl/Cmd+Click Recursive JSON Tree Toggle — Summary

**One-liner:** Added Ctrl/Cmd+click recursive expand/collapse to JsonTree via forceCollapsed/forceVersion prop-signaling, with each node propagating to its children via an independent childForceVersion counter.

## What Was Built

The `JsonTree` OWL component now supports two toggle modes:

- **Normal click:** Toggles only the clicked node (existing behavior, unchanged).
- **Ctrl/Cmd+click:** Recursively expands or collapses the clicked node and all descendants.

## Implementation

### Propagation pattern

Rather than passing a global "collapse all" flag, each node signals its direct children by incrementing its own `childForceVersion` counter. Children react via `onWillUpdateProps` — when `forceVersion` changes, they update their own `collapsed` state and increment their own `childForceVersion`, cascading the signal down the tree.

This avoids the problem of re-using the same version number across multiple recursive calls: each level independently increments, so every level always sees a new version number.

### js changes (`json_tree.js`)

- Added `onWillUpdateProps` to the OWL import.
- Added `forceCollapsed: Boolean (optional)` and `forceVersion: Number (optional)` to `static props`.
- Expanded `state` to include `childForceCollapsed: undefined` and `childForceVersion: 0`.
- Added `onWillUpdateProps` callback: detects parent version bump, updates own `collapsed`, and bumps `childForceVersion` to propagate downward.
- Updated `toggle(ev)`: normal click unchanged; Ctrl/Cmd+click also sets `childForceCollapsed` and increments `childForceVersion`.

### Template changes (`json_tree.xml`)

- Added `forceCollapsed="state.childForceCollapsed"` and `forceVersion="state.childForceVersion"` to the child `<JsonTree>` element.

## Tasks Completed

| # | Task | Commit |
|---|------|--------|
| 1 | Add recursive toggle logic to JsonTree JS | 5b53199 |
| 2 | Update JsonTree template to pass force props to children | da8c6c8 |

## Verification

Manual verification steps (from plan):
1. Open AI Debugger panel with a debug trace containing nested JSON.
2. Normal click on collapsed node: only that node expands.
3. Normal click on expanded node: only that node collapses.
4. Ctrl+click (Cmd+click on Mac) on collapsed node: node and all descendants expand.
5. Ctrl+click (Cmd+click on Mac) on expanded node: node and all descendants collapse.
6. After recursive expand, normal-click a single child: only that child toggles independently.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- FOUND: ai_debug/static/src/debug_panel/json_tree/json_tree.js
- FOUND: ai_debug/static/src/debug_panel/json_tree/json_tree.xml
- FOUND: .planning/quick/3-ctrl-cmd-click-on-folded-json-tree-node-/3-SUMMARY.md
- FOUND commit: 5b53199 (Task 1)
- FOUND commit: da8c6c8 (Task 2)
