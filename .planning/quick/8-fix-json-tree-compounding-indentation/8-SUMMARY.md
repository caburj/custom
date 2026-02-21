---
phase: quick-8
plan: 8
subsystem: ui
tags: [json-tree, css, indentation]

requirements-completed: []

duration: <1min
completed: 2026-02-21
---

# Quick Task 8: Fix JSON tree compounding indentation

**Root cause:** JsonTree is a recursive OWL component — child nodes are physically nested inside parent `div` elements. Using `padding-left: depth * 10px` meant padding compounded as a triangular sum (0 + 10 + 20 + 30 + ...), growing quadratically instead of linearly.

**Fix:** Changed to a flat `padding-left: 12px` for all nodes with depth > 0 (root gets no padding). Since the DOM nesting already provides the hierarchy, each level now adds exactly 12px regardless of depth.

## Files Modified
- `ai_debug/static/src/app/detail/json_tree.xml` — line 5: `props.depth * 10` → `props.depth > 0 ? 'padding-left:12px' : false`

## Commit
- `9efe0f2` fix(quick-8): use flat 12px indent per json tree depth level
