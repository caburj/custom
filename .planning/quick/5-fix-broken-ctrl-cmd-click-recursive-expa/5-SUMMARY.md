---
phase: quick-5
plan: 01
subsystem: ai_debug/json_tree
tags: [owl, json-tree, recursive-expand, ctrl-click, bug-fix]
dependency_graph:
  requires: [quick-3]
  provides: [working-recursive-expand-collapse]
  affects: [json_tree.js]
tech_stack:
  added: []
  patterns: [owl-mount-aware-prop-propagation]
key_files:
  created: []
  modified:
    - ai_debug/static/src/debug_panel/json_tree/json_tree.js
decisions:
  - "Honor forceCollapsed on mount (not just onWillUpdateProps) so freshly created children receive recursive force signal"
  - "Reset childForceCollapsed to undefined on normal clicks to prevent stale force state leaking into subsequent interactions"
metrics:
  duration: "2 min"
  completed: "2026-02-20"
  tasks_completed: 1
  files_modified: 1
---

# Phase quick-5 Plan 01: Fix Broken Ctrl/Cmd+Click Recursive Expand Summary

**One-liner:** Mount-aware force propagation in JsonTree so Ctrl+click recursively expands freshly created children via setup() initialization, not just onWillUpdateProps.

## What Was Built

Fixed the `JsonTree` component's recursive expand/collapse (Ctrl/Cmd+click) to correctly handle the mount lifecycle path. Previously, when a collapsed node was Ctrl+clicked to expand it, its children were freshly mounted by OWL — `onWillUpdateProps` never fired for new components, so `forceCollapsed` props were ignored and deep children stayed collapsed.

The fix adds two complementary behaviors:

1. **Mount path (setup):** When `forceCollapsed` is a boolean on mount, use it as the initial `collapsed` state and immediately initialize `childForceCollapsed` / `childForceVersion` so the node's own children (when they mount) also receive the force signal.

2. **Normal click cleanup (toggle):** When clicking without Ctrl/Cmd, reset `childForceCollapsed` to `undefined` so subsequent expansions use depth-based defaults, not stale force state from a prior Ctrl+click.

The update path (`onWillUpdateProps`) was already correct and required no changes.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix JsonTree setup() and toggle() for mount-aware force propagation | 8a78338 | ai_debug/static/src/debug_panel/json_tree/json_tree.js |

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- File exists: `ai_debug/static/src/debug_panel/json_tree/json_tree.js` - FOUND
- Commit 8a78338 - FOUND
- `forceActive` pattern present in setup() - FOUND
- `childForceCollapsed = undefined` in else branch of toggle() - FOUND
