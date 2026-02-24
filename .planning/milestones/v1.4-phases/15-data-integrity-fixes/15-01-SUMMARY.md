---
phase: 15-data-integrity-fixes
plan: "01"
subsystem: ui
tags: [owl, indexeddb, export, hydration, subagent]

# Dependency graph
requires:
  - phase: 15-01 (Phase 14 Plan 01)
    provides: serializeTrace() parent linkage fields (parent_trace_id, parent_tool_call_id, session_id) fixed in a7ac163; _collectDescendantIds() helper established in quick task 27
provides:
  - exportSelected() with descendant cascade via _collectDescendantIds() + Set dedup
  - onWillStart two-pass IDB hydration: first pass loads all traces, second pass promotes orphans to root
  - Root-only auto-select on page load (newest root trace by created_ts, never a subagent child)
  - Formal closure of DATA-01: serializeTrace/hydrateTrace roundtrip verified
affects:
  - future export/import features
  - any future IDB hydration changes

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Cascade pattern: collect IDs + _collectDescendantIds() + new Set() dedup — consistent across export, delete
    - Two-pass hydration: first pass loads all, second pass validates cross-references (orphan detection)
    - Root-only auto-select: filter to !parent_trace_id traces, pick newest by created_ts

key-files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js

key-decisions:
  - "exportSelected() uses _collectDescendantIds() + Set dedup — same proven pattern as deleteCheckedTraces()"
  - "Orphan promotion nulls both parent_trace_id and parent_tool_call_id — consistent with sidebarNodes root detection via !t.parent_trace_id"
  - "Auto-select picks newest root trace by created_ts comparison — never a subagent child trace"
  - "DATA-01 verified with no code change: serializeTrace() writes all three parent linkage fields; hydrateTrace() ...plain spread restores them (fixed in a7ac163)"

patterns-established:
  - "Cascade pattern: collect root IDs, push _collectDescendantIds() results, deduplicate with new Set() — use for any operation that must include subagent descendants"
  - "Two-pass hydration: always validate cross-references in a second pass after all records are loaded into the Map"

requirements-completed: [DATA-01, DATA-02, DATA-03]

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 15 Plan 01: Data Integrity Fixes Summary

**Export cascade to subagent descendants, two-pass IDB orphan promotion, and root-only auto-select — closing all three DATA requirements for v1.4**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-24T08:46:05Z
- **Completed:** 2026-02-24T08:47:40Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `exportSelected()` now includes all subagent descendant traces via `_collectDescendantIds()` + `new Set()` dedup — mirrors the proven `deleteCheckedTraces()` cascade pattern
- `onWillStart` second pass nulls `parent_trace_id` / `parent_tool_call_id` on orphan traces (parent_trace_id points to a trace not in IDB), promoting them to root level
- Auto-select on page load now picks the newest root trace by `created_ts`, never a subagent child trace
- DATA-01 formally closed: `serializeTrace()` writes all three parent linkage fields; `hydrateTrace()` `...plain` spread restores them (no code change needed — fixed in commit `a7ac163`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Export cascade to subagent descendants + DATA-01 verification** - `a1b886a` (feat)
2. **Task 2: Two-pass IDB hydration with orphan promotion and root-only auto-select** - `1132803` (feat)

## Files Created/Modified

- `ai_debug/static/src/app/app.js` - exportSelected() cascade + onWillStart two-pass hydration + root-only auto-select

## Decisions Made

- `exportSelected()` follows the identical cascade pattern as `deleteCheckedTraces()` — collect root IDs, push descendant IDs, deduplicate with `new Set()`. Consistency over cleverness.
- Orphan promotion nulls both `parent_trace_id` and `parent_tool_call_id` together — `sidebarNodes` uses `!t.parent_trace_id` as the root-detection predicate, so nulling just one would leave stale data.
- Auto-select picks newest by `created_ts` (not Map insertion order) — `created_ts` is always set (either from payload or derived from `started_at`) making it more reliable than key ordering.
- DATA-01 required no code change — `serializeTrace()` already persists all three parent fields (lines 52-54 in db.js); `hydrateTrace()` uses `...plain` spread (line 39 in app.js) which restores them unconditionally.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three DATA requirements (DATA-01, DATA-02, DATA-03) satisfied — v1.4 Subagent Support milestone is now complete
- Export/import roundtrip preserves full nested hierarchy including subagent descendants
- Page refresh correctly promotes orphan traces to root and auto-selects a root trace

---
*Phase: 15-data-integrity-fixes*
*Completed: 2026-02-24*

## Self-Check: PASSED

- FOUND: ai_debug/static/src/app/app.js
- FOUND: .planning/phases/15-data-integrity-fixes/15-01-SUMMARY.md
- FOUND: a1b886a (Task 1 commit)
- FOUND: 1132803 (Task 2 commit)
- FOUND: _collectDescendantIds in exportSelected
- FOUND: orphan validation second pass
- FOUND: root-only auto-select (bestTrace)
