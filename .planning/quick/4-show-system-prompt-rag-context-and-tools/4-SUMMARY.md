---
phase: quick
plan: 4
subsystem: ui
tags: [owl, debug-panel, javascript, scss, xml]

# Dependency graph
requires:
  - phase: quick
    provides: "quick-2 added instructions/rag_context/tools_definition fields to ai.debug.trace"
provides:
  - "Collapsible Trace Context section in debug panel showing system prompt, RAG context, and tools definition"
  - "Eager-load of trace detail fields in direct-link mode (single ORM round-trip)"
  - "Lazy-load of trace detail fields in live mode (on first expand)"
affects: [debug-panel, ai-debug-trace]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy-load detail fields on first expand (same pattern as toggleIteration/toggleToolCall)"
    - "Eager-load in direct-link mode by extending the initial orm.read fields array"
    - "Guard against missing fields with 'instructions' in check for lazy-load trigger"

key-files:
  created: []
  modified:
    - ai_debug/static/src/debug_panel/debug_panel.js
    - ai_debug/static/src/debug_panel/debug_panel.xml
    - ai_debug/static/src/debug_panel/debug_panel.scss

key-decisions:
  - "Lazy-load via presence check ('instructions' in traceInfo) so direct-link mode avoids extra round-trip"
  - "Collapsed by default — users expand on demand, keeps UI clean for simple traces"
  - "Empty sections hidden individually via t-if; all-empty shows 'No trace context data recorded' message"

patterns-established:
  - "Trace detail expand pattern: state flags (traceDetailExpanded/traceDetailLoading) + Object.assign merge on lazy-load"

requirements-completed: [QUICK-4]

# Metrics
duration: 2min
completed: 2026-02-20
---

# Quick Task 4: Show System Prompt, RAG Context and Tools Summary

**Collapsible "Trace Context" section added to debug panel showing system prompt (instructions), RAG context, and tools definition with eager-load in direct-link mode and lazy-load in live mode**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-20T13:32:01Z
- **Completed:** 2026-02-20T13:33:44Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Extended `_loadTrace` to eagerly fetch `instructions`, `rag_context`, and `tools_definition` in a single ORM read (no extra round-trip for direct-link mode)
- Added `toggleTraceDetail()` with lazy-load logic for live mode: triggers ORM read on first expand only when fields are absent
- Inserted collapsible "Trace Context" section between error state and timeline in template; collapsed by default
- System prompt and RAG context render as scrollable preformatted text blocks; tools render via existing JsonTree component with count badge
- Empty fields hidden individually; all-empty shows "No trace context data recorded" message

## Task Commits

Each task was committed atomically:

1. **Task 1: Add trace detail state, lazy-load method, and eager-load in _loadTrace** - `4f4c5a7` (feat)
2. **Task 2: Add collapsible Trace Context section to template and style it** - `71a219c` (feat)

## Files Created/Modified
- `ai_debug/static/src/debug_panel/debug_panel.js` - Added traceDetailExpanded/traceDetailLoading state, bind, reset in _switchToTraceChannel, extend _loadTrace fields, new toggleTraceDetail method
- `ai_debug/static/src/debug_panel/debug_panel.xml` - Inserted collapsible Trace Context block between error state and timeline
- `ai_debug/static/src/debug_panel/debug_panel.scss` - Added styles for trace context toggle, body, sections, pre blocks, and count badge

## Decisions Made
- Used field presence check (`"instructions" in this.state.traceInfo`) rather than null check to distinguish "not fetched" from "fetched but empty" — ensures lazy-load only fires when fields haven't been loaded yet, not when they're legitimately empty
- Collapsed by default to keep the panel focused on iterations for the common case

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Trace Context section ready for use
- All three trace detail fields (instructions, rag_context, tools_definition) now surfaced in the live panel UI

---
*Phase: quick*
*Completed: 2026-02-20*
