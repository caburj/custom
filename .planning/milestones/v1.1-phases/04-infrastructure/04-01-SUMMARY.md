---
phase: 04-infrastructure
plan: 01
subsystem: infra
tags: [odoo, ai_debug, module-cleanup, manifest, owl, bus]

# Dependency graph
requires: []
provides:
  - "ai_debug module stripped of all v1.0 ORM models, views, security CSV, and static debug_panel assets"
  - "v1.1 manifest with ai_debug.assets custom bundle and web.assets_backend debug_menu_button entry"
  - "Root __init__.py ready to import controllers and models packages"
  - "models/__init__.py importing only ir_websocket"
affects: [04-02, 04-03, 04-04, 04-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standalone OWL app pattern: custom asset bundle (ai_debug.assets) that includes web.assets_backend then app/ globs"
    - "debug_menu_button.js registered in web.assets_backend to inject debug menu entry into the main backend"

key-files:
  created: []
  modified:
    - ai_debug/__manifest__.py
    - ai_debug/__init__.py
    - ai_debug/models/__init__.py

key-decisions:
  - "ai_debug.assets bundle uses ('include', 'web.assets_backend') first so the standalone OWL app has full Odoo backend environment"
  - "debug_menu_button.js goes in web.assets_backend (not the custom bundle) so it appears in every backend session even before the debug app is opened"
  - "views/ and static/src/ directories are preserved empty for Plan 02 to populate"

patterns-established:
  - "Custom Odoo asset bundle pattern: bundle includes backend base then app-specific globs"
  - "Separation between debug trigger (debug_menu_button.js in backend) and debug app (ai_debug.assets bundle)"

requirements-completed: [MIGR-02]

# Metrics
duration: 1min
completed: 2026-02-21
---

# Phase 4 Plan 01: Infrastructure - v1.0 Cleanup Summary

**ai_debug module stripped of all v1.0 ORM/view/security artifacts and manifest rewritten with v1.1 ai_debug.assets bundle and standalone-app structure**

## Performance

- **Duration:** ~1 min
- **Started:** 2026-02-21T08:16:49Z
- **Completed:** 2026-02-21T08:17:52Z
- **Tasks:** 2
- **Files modified:** 3 modified, 18 deleted

## Accomplishments
- Deleted all 4 v1.0 ORM model files (ai_debug_trace, ai_debug_iteration, ai_debug_tool_call, ai_session)
- Deleted all v1.0 backend view XML, menus XML, action XML, security CSV, and static debug_panel directory tree
- Rewrote manifest from v1.0 to v1.1 with custom ai_debug.assets bundle structure
- Updated root __init__.py to import both controllers and models packages
- Reduced models/__init__.py to single `from . import ir_websocket` import

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete all v1.0 ORM models, views, security, and static assets** - `abbf883` (feat)
2. **Task 2: Rewrite manifest and root init for v1.1** - `7de28fc` (feat)

## Files Created/Modified
- `ai_debug/__manifest__.py` - Rewritten for v1.1: version 1.1, ai_debug.assets bundle, web.assets_backend debug_menu_button entry, data references only views/ai_debug_index.xml
- `ai_debug/__init__.py` - Updated to import controllers and models packages
- `ai_debug/models/__init__.py` - Reduced to single ir_websocket import

## Decisions Made
- Custom asset bundle `ai_debug.assets` uses `('include', 'web.assets_backend')` as first entry so the standalone OWL app loads with the full Odoo backend environment (services, components, env)
- `debug_menu_button.js` is registered in `web.assets_backend` directly (not the custom bundle) so it loads for every backend session and can inject the debug menu entry regardless of whether the debug app has been opened
- `views/` and `static/src/` directories intentionally left in place (empty) for Plan 02 to populate

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Module is now a clean skeleton: `__init__.py`, `__manifest__.py`, `models/__init__.py`, `models/ir_websocket.py`
- Plan 02 can immediately add: `controllers/` package, `views/ai_debug_index.xml`, `static/src/debug_menu_button.js`, `static/src/app/`
- No blockers

---
*Phase: 04-infrastructure*
*Completed: 2026-02-21*
