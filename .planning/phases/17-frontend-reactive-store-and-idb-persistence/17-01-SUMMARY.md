---
phase: 17-frontend-reactive-store-and-idb-persistence
plan: 01
subsystem: ui
tags: [owl, reactive, indexeddb, tokens, timing, bus-events]

# Dependency graph
requires:
  - phase: 16-backend-token-extraction-and-per-iteration-timing
    provides: Bus events with tokens/duration_ms/provider fields per iteration

provides:
  - normalizeTokens() helper translating backend token schema to store schema
  - _onIteration sets tokens/duration_ms/ai_provider on reactive iteration objects
  - getTraceTotals(trace) reactive aggregation method for Phase 18 sidebar display
  - serializeTrace includes tokens/duration_ms/ai_provider per iteration in IDB
  - hydrateTrace backfills missing token/timing fields with zero defaults (backward compat)

affects:
  - 18-frontend-live-metrics-sidebar-display

# Tech tracking
tech-stack:
  added: []
  patterns:
    - normalizeTokens pure function at module scope for schema translation
    - Fields set inside iterations.set() literal at creation time, not post-mutation
    - getTraceTotals computes on access via reactive proxy reads (no accumulator on trace)
    - hydrateTrace uses ?? operator for zero-defaulting pre-phase records

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/db.js

key-decisions:
  - "normalizeTokens maps backend 'cached' field to store 'cache_read' (locked schema decision)"
  - "cache_write always 0 — no backend field exists yet, placeholder for future"
  - "hydrateTrace does NOT use normalizeTokens — stored records already normalized at ingestion; ?? handles missing fields only"
  - "DB_VERSION remains 1 — additive JSON fields on iteration blob require no IDB schema migration"
  - "No hasTokenData flag — use iter.has_error for distinguishing errored iterations (locked decision)"
  - "No per-event IDB writes in _onIteration — persist fires only on loop_end (existing pattern)"

patterns-established:
  - "Schema translation helpers (normalizeTokens) at module scope, pure functions, no side effects"
  - "All iteration fields set inside the iterations.set() object literal, not as post-creation mutations"
  - "Reactive aggregation via getTraceTotals reading through proxy chain — no cached accumulator on trace"

requirements-completed: [SIDE-02, PERS-01, PERS-02]

# Metrics
duration: 1min
completed: 2026-02-24
---

# Phase 17 Plan 01: Frontend Reactive Store and IDB Persistence Summary

**OWL reactive store wired with token/timing/provider fields via normalizeTokens, with symmetric IDB round-trip and zero-default backward-compatible hydration**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-02-24T19:22:54Z
- **Completed:** 2026-02-24T19:24:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `normalizeTokens()` module-scope helper translating backend `cached` field to store `cache_read` with zero defaults for null/missing payloads (errored iterations produce uniform zero shape, no NaN)
- Extended `_onIteration` handler to set `tokens`, `duration_ms`, and `ai_provider` on each iteration object at creation time inside the `iterations.set()` literal (avoids post-creation mutation pitfall)
- Added `getTraceTotals(trace)` method on AiDebugApp that reads through reactive proxy chain to trigger OWL re-renders — provides `{total_tokens, total_duration_ms, total_input, total_output, total_cached, total_reasoning}` for Phase 18 sidebar
- Extended `serializeTrace` in db.js to persist `tokens`, `duration_ms`, `ai_provider` per iteration to IDB on `loop_end`
- Extended `hydrateTrace` to backfill missing fields with zero defaults using `??` operator — pre-Phase 17 IDB records hydrate cleanly without downstream null checks
- DB_VERSION remains 1 — no schema migration triggered

## Task Commits

Each task was committed atomically:

1. **Task 1: normalizeTokens, _onIteration extension, getTraceTotals** - `d8c76b9` (feat)
2. **Task 2: serializeTrace and hydrateTrace IDB round-trip** - `6c41418` (feat)

**Plan metadata:** *(docs commit follows)*

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - Added normalizeTokens() helper, extended _onIteration with tokens/duration_ms/ai_provider, added getTraceTotals() method, extended hydrateTrace with zero-default backfill
- `ai_debug/static/src/app/db.js` - Extended serializeTrace to persist tokens/duration_ms/ai_provider per iteration

## Decisions Made

- Used `??` (nullish coalescing) in hydrateTrace rather than `normalizeTokens()` to avoid re-mapping `cached->cache_read` on records that were already normalized at ingestion — stored records have `cache_read` key, not `cached`
- Hydration default object shape `{ input: 0, output: 0, cache_read: 0, cache_write: 0, reasoning: 0, total: 0 }` exactly matches normalizeTokens output for uniform downstream access
- `ai_provider` sourced from `payload.provider` (not `payload.ai_provider`) to match backend bus event field name

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 17 Plan 01 complete — reactive data layer fully wired
- Phase 18 (frontend live metrics sidebar display) can now read `getTraceTotals(trace)` and `iter.tokens` / `iter.duration_ms` through reactive proxies and get correct re-renders
- SIDE-02 precondition satisfied: `getTraceTotals(trace)` reactively recomputes when iteration tokens change
- IDB round-trip verified symmetric: serialize includes all fields, hydrate backfills missing with defaults

## Self-Check: PASSED

- FOUND: ai_debug/static/src/app/app.js
- FOUND: ai_debug/static/src/app/db.js
- FOUND: .planning/phases/17-frontend-reactive-store-and-idb-persistence/17-01-SUMMARY.md
- FOUND commit: d8c76b9 (feat(17-01): add normalizeTokens, extend _onIteration, add getTraceTotals)
- FOUND commit: 6c41418 (feat(17-01): extend serializeTrace and hydrateTrace for IDB round-trip)

---
*Phase: 17-frontend-reactive-store-and-idb-persistence*
*Completed: 2026-02-24*
