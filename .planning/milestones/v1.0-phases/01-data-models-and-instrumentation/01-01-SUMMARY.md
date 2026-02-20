---
phase: 01-data-models-and-instrumentation
plan: 01
subsystem: database
tags: [odoo, orm, fields.Json, autovacuum, ir.model.access, cascade, Selection]

# Dependency graph
requires: []
provides:
  - "ai.debug.trace persistent model — one record per agentic loop run with agent/model context, state, timing, autovacuum retention"
  - "ai.debug.iteration persistent model — one record per LLM call with full messages_sent/raw_response Json, state snapshots, timing"
  - "ai.debug.tool.call persistent model — one record per tool execution with args, result, confirmation, state snapshots, timing"
  - "Cascade delete chain: trace -> iteration -> tool_call"
  - "Admin-only (base.group_system) CRUD access for all three models"
  - "ai_debug module scaffold installable on Odoo instances with enterprise ai module"
affects:
  - 01-02 (instrumentation layer will populate these models)
  - 02 (backend views will display these models)
  - 03 (live panel will read iteration/tool_call records via bus.bus)

# Tech tracking
tech-stack:
  added:
    - "fields.Json (Odoo 17.0+ JSONB) — messages_sent, raw_response, args, state_before, state_after, final_message"
    - "@api.autovacuum — retention cleanup, auto-registered by ir.autovacuum nightly cron"
  patterns:
    - "Separate persistent models.Model for debug data (not TransientModel — must survive ai.session GC)"
    - "Cascade delete chain (trace -> iteration -> tool_call) via ondelete='cascade' on Many2one fields"
    - "Admin-only security with base.group_system in ir.model.access.csv"
    - "ir.config_parameter for configurable retention (ai_debugger.retention_days, default 7)"

key-files:
  created:
    - ai_debug/__manifest__.py
    - ai_debug/__init__.py
    - ai_debug/models/__init__.py
    - ai_debug/models/ai_debug_trace.py
    - ai_debug/models/ai_debug_iteration.py
    - ai_debug/models/ai_debug_tool_call.py
    - ai_debug/security/ir.model.access.csv
  modified: []

key-decisions:
  - "fields.Json (not fields.Text) for all JSON payload fields — native JSONB, no double-serialization"
  - "agent_id ondelete='set null' (not cascade) — traces from _get_direct_response have no agent context"
  - "result field on tool.call is fields.Text (not Json) — tool results may be plain strings not JSON"
  - "No ir_cron.xml needed — @api.autovacuum auto-registered by ir.autovacuum nightly cron"
  - "No menu XML or views — Phase 2 scope"

patterns-established:
  - "Pattern: @api.autovacuum with ir.config_parameter for configurable retention cleanup"
  - "Pattern: fields.Json for all structured JSON storage (messages arrays, LLM responses, state dicts)"
  - "Pattern: cascade delete chain via ondelete='cascade' on Many2one inverse fields"
  - "Pattern: base.group_system for admin-only model access in ir.model.access.csv"

requirements-completed: [CAPT-01, CAPT-02, CAPT-03, CAPT-04, CAPT-05, CAPT-06, CAPT-07, CAPT-10, CAPT-11, CONF-02]

# Metrics
duration: 2min
completed: 2026-02-20
---

# Phase 1 Plan 01: Data Models and Instrumentation Summary

**Three persistent Odoo ORM models (ai.debug.trace, ai.debug.iteration, ai.debug.tool.call) with cascade deletes, Json fields for verbatim LLM payloads, admin-only security, and @api.autovacuum retention cleanup**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-20T09:16:09Z
- **Completed:** 2026-02-20T09:17:34Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- Created the `ai_debug` Odoo module scaffold (manifest, init files) with `depends=['ai']`, `application=False`, `license='LGPL-3'` — installs cleanly on any Odoo instance with the enterprise `ai` module
- Defined three persistent `models.Model` classes with all fields required for full agentic loop observability: trace (11 fields), iteration (9 fields), tool_call (11 fields)
- Established cascade delete chain: deleting a trace deletes all its iterations, deleting an iteration deletes all its tool calls
- Admin-only security CSV restricts all CRUD operations to `base.group_system`
- `@api.autovacuum` method on trace model reads `ai_debugger.retention_days` config param (default 7) and auto-deletes old traces — no separate `ir.cron` XML required

## Task Commits

Each task was committed atomically:

1. **Task 1: Create module scaffold** - `d8cdc4c` (feat)
2. **Task 2: Define data models, security CSV, and autovacuum** - `9355fbc` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `ai_debug/__manifest__.py` — Module declaration: `depends=['ai']`, `application=False`, `data=['security/ir.model.access.csv']`
- `ai_debug/__init__.py` — Imports `models` subpackage
- `ai_debug/models/__init__.py` — Imports `ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call`
- `ai_debug/models/ai_debug_trace.py` — `ai.debug.trace` model: agent context, instructions/rag_context, state selection, timing, `@api.autovacuum` retention method
- `ai_debug/models/ai_debug_iteration.py` — `ai.debug.iteration` model: trace_id cascade, index, messages_sent/raw_response Json, state snapshots, final_message, timing
- `ai_debug/models/ai_debug_tool_call.py` — `ai.debug.tool.call` model: iteration_id cascade, tool_name, call_id, args Json, result Text, confirmation fields, state snapshots, timing
- `ai_debug/security/ir.model.access.csv` — Admin-only CRUD (base.group_system) for all three models

## Decisions Made

- `agent_id` uses `ondelete='set null'` because `_run_agentic_loop` is `@api.model` — it may be called without an agent context (e.g., via `_get_direct_response`). Cascade would delete traces when agents are deleted, losing audit history.
- `result` on `ai.debug.tool.call` is `fields.Text` (not `fields.Json`) — tool results may be plain strings, not JSON objects. Using `fields.Json` would force JSON parsing and reject plain strings.
- No `ir_cron.xml` data file — `@api.autovacuum` is automatically registered by Odoo's `ir.autovacuum` nightly cron. This was confirmed against `base/models/ir_autovacuum.py`.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. The module installs via standard Odoo addon mechanism once the enterprise `ai` module is available.

## Next Phase Readiness

- Storage schema is complete — Plan 02 (instrumentation layer) can now implement `_inherit = 'ai.session'` overrides to populate these models
- The `ai_debug_trace.py` autovacuum method provides configurable retention via `ir.config_parameter` key `ai_debugger.retention_days`
- No blockers. Phase 1 Plan 02 (instrumentation) depends on these models being installable.

---
*Phase: 01-data-models-and-instrumentation*
*Completed: 2026-02-20*

## Self-Check: PASSED

All created files verified present on disk:
- FOUND: ai_debug/__manifest__.py
- FOUND: ai_debug/__init__.py
- FOUND: ai_debug/models/__init__.py
- FOUND: ai_debug/models/ai_debug_trace.py
- FOUND: ai_debug/models/ai_debug_iteration.py
- FOUND: ai_debug/models/ai_debug_tool_call.py
- FOUND: ai_debug/security/ir.model.access.csv
- FOUND: .planning/phases/01-data-models-and-instrumentation/01-01-SUMMARY.md

Task commits verified in git log:
- d8cdc4c — feat(01-01): create ai_debug module scaffold
- 9355fbc — feat(01-01): define ai.debug.trace, ai.debug.iteration, ai.debug.tool.call models
- f3a3984 — docs(01-01): complete data models and module scaffold plan
