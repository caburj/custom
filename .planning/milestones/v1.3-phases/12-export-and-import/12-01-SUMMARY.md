---
phase: 12-export-and-import
plan: "01"
subsystem: ui
tags: [owl, indexeddb, blob-url, file-download, serialization]

# Dependency graph
requires:
  - phase: 11-hydration-and-trace-management
    provides: "serializeTrace internal function in db.js, checkbox selection state (checkedTraceIds)"
  - phase: 10-local-persistence
    provides: "db.js module with serializeTrace, writeTrace, IDB infrastructure"
provides:
  - "serializeTrace exported from db.js for external callers"
  - "exportSelected() method on AiDebugApp — downloads checked traces as timestamped JSON file"
  - "Export button in sidebar header action bar (before delete button)"
affects: [13-import, future-export-features]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Blob URL file download pattern: createObjectURL → anchor click → revokeObjectURL"
    - "JSON.parse(JSON.stringify(serializeTrace(trace))) Proxy-stripping for Blob content (same as writeTrace)"
    - "export button disabled via 't-att-disabled: expr or undefined' idiom"

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/db.js
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml

key-decisions:
  - "serializeTrace exported with minimal change (function keyword → export function) — no refactoring"
  - "Raw JSON array format (no metadata envelope) — locked from CONTEXT.md"
  - "URL.revokeObjectURL runs immediately after a.click() to prevent memory leaks"
  - "filter(Boolean) handles race condition where checked ID's trace was removed before export"
  - "Export button ordered before delete button; import button will insert between them in Plan 02"

patterns-established:
  - "Blob URL download: create → click → revoke in same sync frame"

requirements-completed: [XPRT-01]

# Metrics
duration: 4min
completed: 2026-02-22
---

# Phase 12 Plan 01: Export Selected Traces Summary

**Blob URL file download of checked traces serialized via serializeTrace() with ai-debug-traces-YYYY-MM-DD.json filename pattern**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-22T17:06:49Z
- **Completed:** 2026-02-22T17:10:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Exported `serializeTrace` from db.js (one-word change: `function` -> `export function`)
- Added `exportSelected()` to `AiDebugApp` — serializes checked traces, strips reactive Proxies via JSON round-trip, downloads as Blob URL with timestamped filename
- Added export button to sidebar header action bar, before delete button, with same disabled-when-nothing-checked idiom

## Task Commits

Each task was committed atomically:

1. **Task 1: Export serializeTrace from db.js and add exportSelected() to app.js** - `48df6ad` (feat)
2. **Task 2: Add export button to sidebar header action bar in app.xml** - `3dc2133` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `ai_debug/static/src/app/db.js` - Changed `function serializeTrace` to `export function serializeTrace`
- `ai_debug/static/src/app/app.js` - Added `serializeTrace` to import, added `exportSelected()` method
- `ai_debug/static/src/app/app.xml` - Added export button before delete button in `.ai-tree-header-actions`

## Decisions Made
- Used `&#x2913;` (DOWNWARDS ARROW TO BAR) as the export button icon — represents download clearly
- Raw JSON array output (no envelope) — locked decision from CONTEXT.md
- `URL.revokeObjectURL` immediately after `a.click()` — browser queues the download before the URL is revoked

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Export is complete; Plan 02 (import) can now proceed
- Import button will be inserted between the export and delete buttons in app.xml
- serializeTrace export is stable — import's hydrateTrace() already exists in app.js

---
*Phase: 12-export-and-import*
*Completed: 2026-02-22*
