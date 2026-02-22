---
phase: 10-idb-layer-and-write-through
plan: 01
subsystem: persistence
tags: [indexeddb, write-through, ephemeral-mode, idb-wrapper]
dependency_graph:
  requires: []
  provides: [db.js, writeTrace, probeIDB, deleteTrace, ephemeralMode]
  affects: [app.js, app.xml, app.scss]
tech_stack:
  added: []
  patterns: [fire-and-forget-write, onWillStart-probe, serialize-maps-to-entries]
key_files:
  created:
    - ai_debug/static/src/app/db.js
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
decisions:
  - "trace_id from backend is uuid.uuid4().hex — safe to use directly as IDB key, no client-side UUID needed"
  - "writeTrace is non-async, returns raw Promise — caller uses .catch() for error handling"
  - "serializeTrace is internal (not exported) — all IDB knowledge confined to db.js"
  - "Ephemeral indicator uses text label 'Ephemeral' not Unicode — more reliable cross-platform"
metrics:
  duration: "~15 minutes"
  completed_date: "2026-02-22"
  tasks_completed: 2
  files_modified: 4
---

# Phase 10 Plan 01: IDB Write-Through and Ephemeral Mode Summary

**One-liner:** IDB persistence module with fire-and-forget trace writes via Odoo's IndexedDB utility, ephemeral mode detection and amber badge indicator.

## What Was Built

Created `db.js` — a thin plain ES module wrapping Odoo's `@web/core/utils/indexed_db` utility — and wired write-through into `app.js`'s `_onLoopEnd` handler. Added startup IDB availability detection and a visible ephemeral mode indicator in the header.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create db.js IDB persistence module | c9643ed | ai_debug/static/src/app/db.js (created, 98 lines) |
| 2 | Wire IDB write-through and ephemeral mode into app | e405ac6 | app.js, app.xml, app.scss (modified) |

## Technical Details

### db.js Module

- Instantiates `new IndexedDB("ai_debug_traces", 1)` at module level (not in OWL reactive state — no `markRaw` needed)
- `probeIDB()`: uses `idb.execute((db) => (db ? "ok" : null))` to detect private browsing. Odoo's `_execute` calls `callback(undefined)` on `onerror` (not reject), so the `db ? "ok" : null` guard is the only reliable detection method.
- `serializeTrace()`: internal function — converts reactive Proxy Maps to plain entry arrays via `[...map.entries()]`. Includes `storedAt: Date.now()` for Phase 11 ordering. Excludes `expanded` (ephemeral UI state).
- `writeTrace()`: synchronous function returning the raw Promise — caller `.catch()`es for errors.
- `deleteTrace()`: exposed now for Phase 11 consumption — avoids needing to modify `db.js` later.

### app.js Integration

- `onWillStart` hook probes IDB before first render — no "flash of persistence available" state.
- `_onLoopEnd` writes after updating `status`/`ended_at`/`duration_ms` — trace is complete at write time.
- `if (!this.state.ephemeralMode)` guard skips writes when already in ephemeral mode.
- `.catch()` on `writeTrace()` switches to ephemeral mid-session on quota or transaction errors.

### Ephemeral Indicator

- `app.xml`: `<span t-if="state.ephemeralMode" class="ai-ephemeral-indicator">` — rendered only when IDB unavailable.
- `app.scss`: Amber badge using `$o-warning` color variables, monospace font, matching existing header aesthetic.
- Text label "Ephemeral" chosen over Unicode symbols — more reliable cross-platform.

## Deviations from Plan

None — plan executed exactly as written.

## Key Decisions Made

1. **trace_id as IDB key confirmed**: Inspected `ai_session.py` — `trace_id = uuid.uuid4().hex`. The backend already generates a UUID hex string. Used directly as the IDB key; no client-side UUID generation needed.

2. **writeTrace non-async**: The plan specified returning the raw Promise rather than making `writeTrace` async — maintained exactly. This is critical for the fire-and-forget pattern.

3. **Text label over Unicode**: Plan specified "Ephemeral" text label rather than Unicode combining characters. This was preserved as more reliable across platforms and consistent with the monospace status label aesthetic.

4. **Tool call fields fully serialized**: Each tool call entry in `serializeTrace` explicitly enumerates all fields (`tool_call_id`, `iteration_id`, `tool_name`, `success`, `args`, `result`, `error`, `state_before`, `state_after`, `call_id`) rather than using spread — produces a well-defined schema for Phase 12 export.

## Self-Check: PASSED

Files exist:
- ai_debug/static/src/app/db.js: FOUND
- ai_debug/static/src/app/app.js: FOUND (modified)
- ai_debug/static/src/app/app.xml: FOUND (modified)
- ai_debug/static/src/app/app.scss: FOUND (modified)

Commits exist:
- c9643ed: FOUND (feat(10-01): create db.js IDB persistence module)
- e405ac6: FOUND (feat(10-01): wire IDB write-through and ephemeral mode into app)
