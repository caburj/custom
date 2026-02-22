---
phase: 11-hydration-and-trace-management
plan: 01
subsystem: ai_debug persistence read path
tags: [hydration, indexeddb, owl-reactive, persistence, trace-management]
dependency_graph:
  requires: [10-01]
  provides: [PERS-02, PERS-03]
  affects: [ai_debug/static/src/app/db.js, ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.xml, ai_debug/static/src/app/app.scss]
tech_stack:
  added: []
  patterns: [getAll() single-transaction bulk IDB read, hydrateTrace deserializer pattern, onWillStart pre-render hydration]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/db.js
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
decisions:
  - "loadAllTraces uses idb.execute() with native getAll() — single transaction, not N sequential reads"
  - "hydrateTrace is module-level (not a class method) — pure function with no this dependency"
  - "Iterations and toolCalls Maps explicitly wrapped in reactive(new Map()) so bus event .set() calls trigger OWL re-renders post-hydration"
  - "hydrated: true is a permanent marker never removed — used by template badge, consistent with session context"
  - "at(-1) selects most recent trace for auto-select (insertion order matches arrival order)"
metrics:
  duration: ~2 minutes
  completed: 2026-02-22
  tasks_completed: 2
  files_modified: 4
---

# Phase 11 Plan 01: IDB Hydration on Page Load Summary

**One-liner:** Bulk IDB read via `getAll()` with reactive Map reconstruction in `hydrateTrace()` populates sidebar before first render, with "archived" badge on hydrated traces.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add loadAllTraces() to db.js | b521838 | db.js |
| 2 | Wire hydration into app.js with hydrateTrace deserializer and hydrated badge | 2c71b7a | app.js, app.xml, app.scss |

## What Was Built

### Task 1: loadAllTraces() in db.js

Added `loadAllTraces()` as the 4th exported function in `db.js`. Uses `idb.execute()` with a native `getAll()` IDB cursor for a single-transaction bulk read — avoids N sequential reads (Option B from research). Returns `[]` when `db` is falsy (IDB unavailable), matching the ephemeral mode guard. The `STORE` constant ("traces") is shared with the existing write functions.

### Task 2: Hydration wiring in app.js + visual indicator

**`hydrateTrace()` function:** Module-level pure function placed before the class definition. Reconstructs reactive Maps from the serialized `[id, record]` pair arrays produced by `serializeTrace()`. Parses ISO date strings back to `Date` objects for `started_at`, `ended_at`, and `receivedAt`. Sets `expanded: false` on both trace and iterations (collapsed on hydration). Sets `hydrated: true` as a permanent marker.

Critical detail: both `iterations` and `toolCalls` are wrapped in `reactive(new Map())`. Without this, subsequent bus event handlers calling `.set()` on these Maps would not trigger OWL re-renders (because OWL only tracks reactive-wrapped Maps in its dependency graph).

**`onWillStart` hydration block:** After `probeIDB()` succeeds, calls `loadAllTraces()` and hydrates each record into `this.traces` via `hydrateTrace()`. Auto-selects the most recent trace (last key in insertion order = top of reversed sidebar list) when nothing is selected. All of this runs in `onWillStart`, before the first render, eliminating any flash of empty state.

**app.xml badge:** Added `<span t-if="trace.hydrated" class="ai-tree-hydrated-badge" title="Loaded from storage">archived</span>` after the label span, before status indicators. Uses text label (not Unicode) consistent with the Phase 10 "Ephemeral" indicator decision.

**app.scss styling:** `.ai-tree-hydrated-badge` uses `font-size: 0.7em`, `opacity: 0.55`, `font-style: italic`, `margin-left: 4px`, `flex-shrink: 0`. Muted appearance distinguishes hydrated from live traces without visual dominance.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files exist
- `ai_debug/static/src/app/db.js` — FOUND
- `ai_debug/static/src/app/app.js` — FOUND
- `ai_debug/static/src/app/app.xml` — FOUND
- `ai_debug/static/src/app/app.scss` — FOUND

### Commits exist
- b521838 — FOUND
- 2c71b7a — FOUND

## Self-Check: PASSED
