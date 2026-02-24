---
phase: quick-36
plan: 01
subsystem: ai_debug/static/src/app
tags: [cleanup, dead-code, timing, client-side]
dependency_graph:
  requires: [quick-35]
  provides: [clean-trace-store-no-client-timing]
  affects: [app.js, loop_detail.js, loop_detail.xml, db.js]
tech_stack:
  added: []
  patterns: [server-provided-duration, sort-key-separation]
key_files:
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/detail/loop_detail.js
    - ai_debug/static/src/app/detail/loop_detail.xml
    - ai_debug/static/src/app/db.js
decisions:
  - "Replaced live timer chip showing client-derived elapsed time with static 'running' text"
  - "Simplified created_ts hydration fallback to use storedAt instead of started_at"
  - "Sort comparators now use storedAt as fallback instead of started_at"
metrics:
  duration: 3 min
  completed: 2026-02-24
---

# Quick Task 36: Remove Client-Side JS-Derived Duration Values — Summary

**One-liner:** Removed all client-side timing artifacts (started_at, ended_at, receivedAt, getIterationDuration, live timer) in favor of server-provided duration_ms throughout app.js, loop_detail.js, loop_detail.xml, and db.js.

## Tasks Completed

| # | Name | Commit | Files |
|---|------|--------|-------|
| 1 | Remove client timestamps and dead duration code from app.js | 75c5fd8 | app.js |
| 2 | Remove live timer from loop_detail.js and loop_detail.xml | ac6cd98 | loop_detail.js, loop_detail.xml |
| 3 | Clean up db.js serialization of removed fields | 5871a55 | db.js |

## What Changed

### app.js
- Removed `started_at: new Date()` and `ended_at: null` from `_placeTrace()` trace object
- Removed `trace.ended_at = new Date()` from `_onLoopEnd` handler
- Removed `receivedAt: new Date()` from `_onIteration` handler
- Removed `receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null` from `hydrateTrace()` iteration loop
- Removed `started_at` and `ended_at` Date reconstruction from `hydrateTrace()` return value
- Simplified `created_ts` fallback in `hydrateTrace()` from `plain.started_at ? new Date(...)` to `plain.storedAt || 0`
- Simplified sort comparators in `onWillStart` and `_applyImport` to use `storedAt` instead of `started_at`
- Deleted `getIterationDuration()` method (was dead code computing durations from client `receivedAt`)
- Deleted `_formatDuration()` method (was only called by the now-deleted `getIterationDuration`)

### loop_detail.js
- Removed `useRef`, `onMounted`, `onWillUnmount`, `onPatched` from OWL imports (all unused after timer removal)
- Removed `timerRef = useRef("liveTimer")` and `_timerInterval = null` from `setup()`
- Removed `onMounted` block that started the timer for running traces
- Removed `onWillUnmount` block that stopped the timer
- Removed `onPatched` block that managed timer start/stop on status transitions
- Deleted `_startTimer()`, `_updateTimerDisplay()`, `_stopTimer()` methods

### loop_detail.xml
- Replaced `<span t-ref="liveTimer">0s</span>` with `<span>running</span>` for in-progress traces
- The `t-ref` attribute and "0s" placeholder are gone; no client-derived elapsed time displayed

### db.js
- Removed `started_at: trace.started_at` from `serializeTrace()` trace record
- Removed `ended_at: trace.ended_at` from `serializeTrace()` trace record
- Removed `receivedAt: iter.receivedAt` from iteration serialization in `serializeTrace()`
- Updated stale comments that mentioned Date objects

## Retained (Intentionally)

- `created_ts: Date.now()` in `_placeTrace()` — monotonic sort key, not a displayed duration
- `storedAt: Date.now()` in `serializeTrace()` — IDB write timestamp, legacy hydration fallback
- All `duration_ms` fields everywhere — server-provided, correct, unchanged
- `new Date()` on line 913 in `exportSelected()` — export filename date, unrelated to trace timing

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- FOUND: ai_debug/static/src/app/app.js
- FOUND: ai_debug/static/src/app/detail/loop_detail.js
- FOUND: ai_debug/static/src/app/detail/loop_detail.xml
- FOUND: ai_debug/static/src/app/db.js
- FOUND commit: 75c5fd8 (app.js cleanup)
- FOUND commit: ac6cd98 (loop_detail timer removal)
- FOUND commit: 5871a55 (db.js serialization cleanup)
