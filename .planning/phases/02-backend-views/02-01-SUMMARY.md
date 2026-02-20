---
phase: 02-backend-views
plan: 01
subsystem: ui
tags: [odoo, views, xml, computed-fields, ace-editor, badge-widget]

# Dependency graph
requires:
  - phase: 01-data-models-and-instrumentation
    provides: ai.debug.trace, ai.debug.iteration, ai.debug.tool.call models with Json payload fields

provides:
  - duration_human computed Char field on trace, iteration, and tool_call models
  - tool_call_count computed Integer field on iteration model
  - pretty-print computed Text fields for all Json payload fields (json.dumps with indent=2)
  - Odoo backend list, form, and search views for all three debug models
  - Settings > Technical > AI Debug menu with Traces, Iterations, Tool Calls sub-items
  - Manifest data list wired up to load all view XML files

affects: [03-live-panel, any future phase reading ai.debug.* fields in views]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - computed Text fields as ace-editor targets (pretty-print Json fields via json.dumps)
    - duration_human formatting pattern: ms/<1000 -> "{n}ms", <60000 -> "{n:.1f}s", else "{m}m {s}s"
    - badge widget with decoration-* attrs for colored state display
    - Odoo 17 syntax: <list> not <tree>, invisible="expr" not attrs, readonly="1"

key-files:
  created:
    - ai_debug/views/ai_debug_trace_views.xml
    - ai_debug/views/ai_debug_iteration_views.xml
    - ai_debug/views/ai_debug_tool_call_views.xml
    - ai_debug/views/menus.xml
  modified:
    - ai_debug/models/ai_debug_trace.py
    - ai_debug/models/ai_debug_iteration.py
    - ai_debug/models/ai_debug_tool_call.py
    - ai_debug/__manifest__.py

key-decisions:
  - "Computed Text pretty-print fields (not raw Json fields) used as ace widget targets — json.dumps with indent=2 on each Json field"
  - "result field on tool_call uses plain text widget (not ace) — result may be plain string, not JSON"
  - "Today search filter uses relativedelta(days=0) Odoo domain pattern"
  - "trace action sets search_default_today:1 in context — defaults list to today's traces"
  - "Error Details tab uses invisible=\"state != 'error'\" — Odoo 17 inline invisible expression"

patterns-established:
  - "Pretty-print pattern: computed Text field + @api.depends(source_Json_field) + json.dumps(record.field, indent=2, ensure_ascii=False) if record.field else ''"
  - "Duration formatting: ms < 1000 -> Xms, ms < 60000 -> X.Xs, else Xm Xs"
  - "Ace editor: widget=\"ace\" options=\"{'mode': 'json'}\" readonly=\"1\" nolabel=\"1\" on computed Text field"

requirements-completed: [VIEW-01, VIEW-02, VIEW-03, VIEW-04]

# Metrics
duration: 2min
completed: 2026-02-20
---

# Phase 2 Plan 01: Backend Views Summary

**Odoo backend list/form/search views for ai.debug.* models with ace JSON editors, colored state badges, and Settings > Technical > AI Debug navigation**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-20T10:31:06Z
- **Completed:** 2026-02-20T10:33:20Z
- **Tasks:** 2
- **Files modified:** 8 (3 Python models, 4 XML files, 1 manifest)

## Accomplishments
- Added computed display fields (duration_human, tool_call_count, *_pretty) to all three debug models so views have clean display values without touching stored data
- Created 4 XML view files: list + form + search for trace, form + search for iteration, form + search for tool_call, plus menus/actions file
- Wired up Settings > Technical > AI Debug root menu with Traces (default-filtered to today), Iterations, and Tool Calls sub-items

## Task Commits

Each task was committed atomically:

1. **Task 1: Add computed display fields to all three debug models** - `7d13d80` (feat)
2. **Task 2: Create XML views, actions, menus, and update manifest** - `c314717` (feat)

## Files Created/Modified
- `ai_debug/models/ai_debug_trace.py` - Added duration_human computed Char field
- `ai_debug/models/ai_debug_iteration.py` - Added duration_human, tool_call_count, messages_sent_pretty, raw_response_pretty, state_before_pretty, state_after_pretty; added import json and api
- `ai_debug/models/ai_debug_tool_call.py` - Added duration_human, args_pretty, state_before_pretty, state_after_pretty; added import json and api
- `ai_debug/views/ai_debug_trace_views.xml` - List (6 cols, badge state), form (3 tabs: Iterations/System Prompt & RAG/Error Details), search (agent/model/state/error + Errors+Today filters + 3 group-by)
- `ai_debug/views/ai_debug_iteration_views.xml` - Form (4 tabs: Messages Sent/Raw Response/State Snapshots/Tool Calls, all JSON with ace), search view
- `ai_debug/views/ai_debug_tool_call_views.xml` - Form (4 tabs: Arguments/Result/Confirmation/State Snapshots), search with Confirmations filter
- `ai_debug/views/menus.xml` - 3 act_window actions + AI Debug root + 3 sub-menus
- `ai_debug/__manifest__.py` - data list updated to include all 4 view XML files

## Decisions Made
- Computed Text fields as ace targets rather than using raw Json fields directly — Odoo's ace widget works on Text/Char not Json field types
- result field on tool_call uses plain text widget (not ace) — confirmed by locked decision that results may be plain strings
- trace action sets `search_default_today: 1` in context per research pattern 8 — defaults to today's traces on open
- Error Details tab uses `invisible="state != 'error'"` in Odoo 17 inline syntax (not attrs)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. Module upgrade needed to apply view changes to existing Odoo instance.

## Next Phase Readiness
- All captured trace data is now browsable from the Odoo backend
- Developers can verify Phase 1 instrumentation quality by browsing real traces
- Phase 3 (live panel) can proceed — the data layer is observable and correct
- No blockers identified

## Self-Check: PASSED

All 9 key files found on disk. Both task commits (7d13d80, c314717) confirmed in git log.

---
*Phase: 02-backend-views*
*Completed: 2026-02-20*
