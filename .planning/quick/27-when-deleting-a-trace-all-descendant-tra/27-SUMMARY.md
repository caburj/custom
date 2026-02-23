---
phase: quick-27
plan: 01
subsystem: ai_debug/delete
tags: [cascade-delete, indexeddb, subagent, bulk-delete]
dependency_graph:
  requires: []
  provides: [CASCADE-DELETE]
  affects: [app.js deleteCheckedTraces, db.js]
tech_stack:
  added: []
  patterns: [recursive tree traversal, batch IDB transaction, Set deduplication]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/db.js
decisions:
  - Single IDB transaction for batch delete (deleteTraces) instead of N separate transactions
  - Recursive _collectDescendantIds collects full subtree before any deletion
  - selectedTraceId getter reused for selection clearing (handles trace/iteration/tool_call)
  - Set deduplication handles edge case where a descendant is also directly checked
metrics:
  duration: "~5 minutes"
  completed: "2026-02-23"
  tasks_completed: 1
  tasks_total: 1
  files_modified: 2
---

# Quick Task 27: Cascade Delete Descendant Traces — Summary

Cascade delete for subagent traces: deleting a checked root trace now also removes all descendant subagent traces from both the in-memory reactive Map and IndexedDB in a single batch transaction.

## What Was Built

Two coordinated changes implement full cascade delete:

**db.js — `deleteTraces(traceIds)`**

New batch delete function that removes multiple trace IDs in a single IDB `readwrite` transaction. This replaces N separate `deleteTrace()` calls (each opened its own transaction) with one atomic operation, reducing IDB overhead for trees with many subagent descendants.

**app.js — `_collectDescendantIds(traceId)`**

Recursive helper that walks `this.traces` to find all traces whose `parent_trace_id` matches the given ID, then recursively collects their descendants. Works at any depth (grandchild subagents, etc.).

**app.js — `deleteCheckedTraces()` updated**

1. After collecting `ids` from the checkbox set, expands to `uniqueIds` by calling `_collectDescendantIds(id)` for each checked ID
2. Uses `Set` deduplication in case a descendant was also directly checked
3. Clears detail panel if `selectedId` is in `uniqueIds` OR if `selectedTraceId` (the getter that resolves trace owners for iterations/tool_calls) is in `uniqueIds` — handles all selection types
4. Deletes from `this.traces` Map for all `uniqueIds` (OWL re-render)
5. Calls `deleteTraces(uniqueIds)` once for the full batch IDB deletion

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files Exist
- ai_debug/static/src/app/app.js — FOUND (modified)
- ai_debug/static/src/app/db.js — FOUND (modified)

### Commits
- 93bd1bc — feat(quick-27): cascade delete descendant traces on bulk delete

## Self-Check: PASSED
