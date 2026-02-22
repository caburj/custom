---
phase: 12-export-and-import
plan: "02"
subsystem: ui
tags: [owl, indexeddb, file-api, dialog, validation]

# Dependency graph
requires:
  - phase: 12-export-and-import/12-01
    provides: "exportSelected() and export button; serializeTrace exported; hydrateTrace() in app.js"
  - phase: 11-hydration-and-trace-management
    provides: "hydrateTrace() function, writeTrace(), reactive Map pattern"
provides:
  - "ImportPreviewDialog OWL component (import_dialog.js + import_dialog.xml)"
  - "Import flow on AiDebugApp: openImportPicker(), onFileSelected(), _handleImportFile(), _applyImport()"
  - "Import button in sidebar header between export and delete (always enabled)"
  - "All-or-nothing file validation with inline error display in dialog"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "File.text() Promise API for reading file contents (cleaner than FileReader callbacks)"
    - "ev.target.value = '' reset pattern to allow re-selecting same file"
    - "All-or-nothing validation: first invalid element rejects entire import"
    - "hydrateTrace() before writeTrace() — import records have iterations as arrays not Maps"
    - "try/catch useService guard for dialog service in standalone contexts"

key-files:
  created:
    - ai_debug/static/src/app/import_dialog.js
    - ai_debug/static/src/app/import_dialog.xml
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml

key-decisions:
  - "Import button always enabled (no disabled state) — locked from CONTEXT.md"
  - "All-or-nothing validation: any invalid element rejects entire file (no partial imports)"
  - "hydrateTrace() called before writeTrace() in _applyImport — raw import records have iterations as arrays, not Maps"
  - "No success toast — sidebar updating with new traces is sufficient feedback (locked from CONTEXT.md)"
  - "Duplicate handling: this.traces.set() overwrites if trace_id already exists"
  - "&#x2912; (UPWARDS ARROW TO BAR) used as import button icon — matches export &#x2913;"
  - "Error dialog shows only Cancel button — no mutation allowed when errorMessage is present"

patterns-established:
  - "ImportPreviewDialog: pure display dialog with errorMessage prop as error/normal mode toggle"

requirements-completed: [XPRT-02, XPRT-03]

# Metrics
duration: 2min
completed: 2026-02-22
---

# Phase 12 Plan 02: Import Traces Summary

**File-picker import flow with all-or-nothing JSON validation, preview dialog showing trace/duplicate counts, and merge into reactive store + IDB via hydrateTrace() before writeTrace()**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-22T17:10:22Z
- **Completed:** 2026-02-22T17:12:00Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Created `ImportPreviewDialog` OWL component — pure display with error/summary conditional and Import/Cancel footer
- Wired full import flow in `AiDebugApp`: file picker trigger, file read, validation, preview dialog, merge
- Added import button to sidebar header (always enabled, between export and delete) with hidden file input
- Validation is all-or-nothing: JSON parse failure, non-array, or any element missing `trace_id`/`iterations` rejects entire file
- `_applyImport` hydrates records via `hydrateTrace()` before `writeTrace()` — prevents Map/array type mismatch

## Task Commits

Each task was committed atomically:

1. **Task 1: Create ImportPreviewDialog OWL component** - `7934b8b` (feat)
2. **Task 2: Wire import flow into app.js and add import button to app.xml** - `237bb38` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified
- `ai_debug/static/src/app/import_dialog.js` - ImportPreviewDialog component (pure display, no setup())
- `ai_debug/static/src/app/import_dialog.xml` - ImportPreviewDialog template with error/summary/footer slots
- `ai_debug/static/src/app/app.js` - Added import, dialog service, fileInputRef, and four import methods
- `ai_debug/static/src/app/app.xml` - Import button in header + hidden file input after MainComponentsContainer

## Decisions Made
- Import button always enabled (no `t-att-disabled`) per CONTEXT.md locked decision
- `&#x2912;` (UPWARDS ARROW TO BAR) as import icon — symmetric with `&#x2913;` export icon
- `ev.target.value = ""` reset before reading file text — allows re-selecting same file on change event
- `hydrateTrace(record)` before `writeTrace(hydrated)` — export format stores `iterations` as `[id, record]` pair arrays (from `serializeTrace().entries()`); `hydrateTrace` converts these to reactive Maps before writing back to IDB
- Error dialog shows only Cancel button — no Import button when `errorMessage` is set
- No success toast after import — sidebar updating with new traces is the feedback

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 12 (Export and Import) is fully complete — both export (Plan 01) and import (Plan 02) are implemented
- Export/import round-trip is now functional: check traces, export to JSON, import from JSON file
- No further phases planned for v1.3

---
*Phase: 12-export-and-import*
*Completed: 2026-02-22*
