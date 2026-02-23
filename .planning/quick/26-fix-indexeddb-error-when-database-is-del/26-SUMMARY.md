---
phase: quick-26
plan: "01"
subsystem: ai_debug/static/src/app/db.js
tags: [bug-fix, indexeddb, resilience]
dependency_graph:
  requires: []
  provides: [resilient-idb-operations]
  affects: [ai_debug/static/src/app/db.js]
tech_stack:
  added: []
  patterns: [defensive-guard, eager-store-registration]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/db.js
decisions:
  - "Register 'traces' store eagerly via idb._tables.add(STORE) rather than relying solely on read/write/getAllKeys to register it"
  - "Belt-and-suspenders: add objectStoreNames.contains() guards even though eager registration is the root-cause fix"
metrics:
  duration: "5 minutes"
  completed: "2026-02-23"
  tasks_completed: 1
  tasks_total: 1
---

# Quick Task 26: Fix IndexedDB NotFoundError After External DB Deletion

**One-liner:** Eagerly register the "traces" object store in idb._tables and add objectStoreNames guards so the ai_debug page survives external IDB deletion without throwing NotFoundError.

## What Was Done

Fixed a `NotFoundError` thrown when the `ai_debug_traces` IndexedDB database was deleted externally (e.g., via DevTools) and the ai_debug page was refreshed.

**Root cause:** `loadAllTraces()` and `deleteTrace()` call `idb.execute()` directly without first calling `idb._tables.add(STORE)`. The upstream `IndexedDB` utility only creates object stores during `onupgradeneeded` for stores registered in `_tables`. Since the direct `execute()` callers never registered the "traces" store, after DB recreation only the internal `__DBVersion__` store was created. The subsequent `db.transaction("traces")` call failed with `NotFoundError`.

**Fix applied in `ai_debug/static/src/app/db.js`:**

1. **Eager store registration (root cause fix):** Added `idb._tables.add(STORE)` immediately after constructing the `IndexedDB` instance. This ensures the "traces" store is always registered before any `execute()` call fires, so `onupgradeneeded` will create it whenever the DB is opened fresh.

2. **Defensive guard in `loadAllTraces()`:** Added `if (!db.objectStoreNames.contains(STORE)) return [];` before opening the transaction. Handles the edge case where the store is missing mid-session (race with external deletion).

3. **Defensive guard in `deleteTrace()`:** Same pattern — return silently if the store doesn't exist (nothing to delete).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Register store eagerly and guard against missing object stores | 9774a91 | ai_debug/static/src/app/db.js |

## Verification

Automated checks confirmed:
- `grep -n "_tables.add" db.js` → line 13: `idb._tables.add(STORE);`
- `grep -n "objectStoreNames.contains" db.js` → line 111 (deleteTrace) and line 134 (loadAllTraces)

Manual verification steps (expected behavior after fix):
1. Open ai_debug page, create a trace so IDB has data
2. Delete the `ai_debug_traces` database via DevTools > Application > IndexedDB
3. Refresh the page — no console error, page loads with empty trace list
4. Ephemeral mode is NOT triggered (IDB is available, just empty)
5. Create a new trace — persists to IDB normally
6. Refresh again — trace is hydrated from IDB

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `ai_debug/static/src/app/db.js` modified: FOUND
- [x] Commit 9774a91 exists: FOUND

## Self-Check: PASSED
