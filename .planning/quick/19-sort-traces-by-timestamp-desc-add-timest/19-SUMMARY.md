---
phase: "19"
plan: 1
type: quick
subsystem: ai_debug
tags: [sorting, timestamp, persistence, import, hydration]
dependency_graph:
  requires: []
  provides: [created_ts-on-traces, deterministic-sidebar-order]
  affects: [ai_debug/static/src/app/app.js, ai_debug/static/src/app/db.js]
tech_stack:
  added: []
  patterns: [epoch-ms-timestamp, map-insertion-order-sort, legacy-fallback]
key_files:
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/db.js
decisions:
  - "Sort oldest-first before Map insertion so template .reverse() can yield newest-first without additional changes to app.xml"
  - "Fall back to started_at for legacy records that pre-date created_ts field"
metrics:
  duration: "~10 minutes"
  completed: "2026-02-22"
  tasks_completed: 1
  files_modified: 2
---

# Quick Task 19: Sort Traces by Timestamp Desc — Add created_ts Summary

**One-liner:** Epoch ms `created_ts` field added to every trace with oldest-first Map insertion sort so sidebar always displays newest-first across live, IDB-hydrated, and imported traces.

## What Was Built

Added a numeric `created_ts` timestamp to every trace object and sorted traces chronologically before inserting into the reactive Map. The template's existing `.reverse()` on `[...traces.keys()]` then produces correct newest-first display without any XML changes.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add created_ts to trace lifecycle and serialize/hydrate paths | b3d16f4 | app.js, db.js |

## Changes Made

### db.js — serializeTrace()

Added `created_ts: trace.created_ts` to the serialized record. This ensures exported JSON includes the timestamp so round-trip import preserves original creation order. `created_ts` (when created) is distinct from `storedAt` (when last persisted to IDB).

### app.js — _onNewTrace handler

Added `created_ts: Date.now()` to the trace object literal alongside `started_at: new Date()`. Captures exact creation time as a sortable numeric epoch ms value.

### app.js — hydrateTrace()

Added `created_ts` field to the reconstructed trace object:
```js
created_ts: plain.created_ts || (plain.started_at ? new Date(plain.started_at).getTime() : 0),
```
Handles legacy records without `created_ts` by falling back to `started_at` converted to epoch ms, or 0 if neither is available.

### app.js — onWillStart hydration block

Sorts `stored[]` oldest-first before the Map insertion loop:
```js
stored.sort((a, b) =>
    (a.created_ts || new Date(a.started_at || 0).getTime()) -
    (b.created_ts || new Date(b.started_at || 0).getTime())
);
```
Previously, IDB `getAll()` returned records in UUID lexicographic order (not chronological). This sort makes hydrated trace order deterministic.

### app.js — _applyImport()

Sorts `records[]` oldest-first before the loop using the same comparator pattern. Imported traces are then inserted in chronological order, matching the hydration behavior.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

Manual browser verification steps (from plan):
1. Open the AI Debugger app — hydrated traces from IDB should appear newest-first
2. Export traces, reimport — order should match original, not be jumbled by UUID
3. Trigger a live trace — should appear at the top (newest)
4. No console errors during any flow

Code-level verification:
- `created_ts` appears at 6 locations in app.js (hydrateTrace, _onNewTrace, 2x in hydration sort, 2x in import sort)
- `created_ts` appears at 1 location in db.js (serializeTrace)
- Commit b3d16f4 confirmed in git log

## Self-Check: PASSED

- FOUND: ai_debug/static/src/app/app.js
- FOUND: ai_debug/static/src/app/db.js
- FOUND: commit b3d16f4
