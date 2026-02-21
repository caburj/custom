---
phase: 04-infrastructure
plan: 02
subsystem: infra
tags: [odoo, ai_debug, owl, bus, http-controller, qweb, scss]

# Dependency graph
requires:
  - phase: 04-01
    provides: "v1.1 manifest with ai_debug.assets bundle, cleaned module skeleton, models/__init__.py importing ir_websocket"
provides:
  - "/ai-debug HTTP route served by AiDebugController with auth='user' and is_user_internal gating"
  - "QWeb template ai_debug.index loading ai_debug.assets bundle via web.layout (no Odoo navbar)"
  - "OWL app booted via mountComponent, subscribing to ai_debug bus channel with connection status indicator"
  - "Three-zone layout: header (title + green/red connection dot), sidebar (empty state), detail panel (pulsing 'Listening for agentic loops...')"
  - "ir_websocket updated: gates ai_debug channel to internal users (_is_internal) instead of system-only (group_system)"
  - "debug_menu_button.js: Odoo debug menu item 'Open AI Debugger' opening /ai-debug in new tab"
affects: [04-03, 04-04, 04-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Standalone OWL app bootstrap: whenReady + mountComponent(AiDebugApp, document.body) with full service registry"
    - "Bus connection tracking via BUS:WORKER_STATE_UPDATED event on bus_service EventTarget"
    - "QWeb session injection: odoo.__session_info__ = json.dumps(session_info) in <script> before asset bundle"
    - "Portal redirect pattern: is_user_internal(request.session.uid) check returning 303 redirect to /web/login"

key-files:
  created:
    - ai_debug/controllers/__init__.py
    - ai_debug/controllers/main.py
    - ai_debug/views/ai_debug_index.xml
    - ai_debug/static/src/debug_menu_button.js
    - ai_debug/static/src/app/main.js
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
  modified:
    - ai_debug/models/ir_websocket.py

key-decisions:
  - "auth='user' on the route handles unauthenticated users automatically; is_user_internal() is the second gate for portal users"
  - "session_info() (not get_frontend_session_info) provides the full session needed by bus_service in a standalone context"
  - "BUS:WORKER_STATE_UPDATED event tracked via addEventListener on bus_service (EventTarget) not via bus_service.subscribe"
  - "deleteChannel (not removeChannel) is the correct OWL bus_service cleanup API"

patterns-established:
  - "Standalone OWL app pattern: mountComponent from @web/env + whenReady from @odoo/owl"
  - "Bus channel gating in ir_websocket._build_bus_channel_list: filter channels list before calling super()"
  - "Connection status reactive state: useState({connectionStatus}) updated by BUS:WORKER_STATE_UPDATED event handler"

requirements-completed: [INFRA-01, INFRA-02, INFRA-03]

# Metrics
duration: 2min
completed: 2026-02-21
---

# Phase 4 Plan 02: Infrastructure - Standalone OWL App Shell Summary

**Standalone /ai-debug OWL app served by HTTP controller with bus_service subscription, three-zone dark UI layout, and debug menu integration**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-21T08:20:14Z
- **Completed:** 2026-02-21T08:21:55Z
- **Tasks:** 2
- **Files modified:** 1 modified, 8 created

## Accomplishments
- HTTP controller at /ai-debug with auth='user' and is_user_internal portal gating, injecting full session_info
- QWeb template using web.layout base (no Odoo navbar) loading ai_debug.assets bundle via t-call-assets
- OWL root component subscribing to ai_debug bus channel on mount, tracking connection state via BUS:WORKER_STATE_UPDATED
- Three-zone dark UI: header with green/red connection dot, sidebar empty state, detail panel with pulsing "Listening for agentic loops..."
- ir_websocket updated from v1.0 (system-only + prefix matching) to v1.1 (internal users + exact channel name)
- Debug menu button registration in web.assets_backend opening /ai-debug in new tab

## Task Commits

Each task was committed atomically:

1. **Task 1: HTTP controller, QWeb template, ir_websocket update, debug menu button** - `a5ec44e` (feat)
2. **Task 2: OWL app entry point and root component with stub layout** - `230c0ed` (feat)

## Files Created/Modified
- `ai_debug/controllers/__init__.py` - Package init importing main
- `ai_debug/controllers/main.py` - AiDebugController serving /ai-debug with auth='user', is_user_internal check, session_info injection
- `ai_debug/views/ai_debug_index.xml` - QWeb template ai_debug.index using web.layout base, loads ai_debug.assets bundle
- `ai_debug/models/ir_websocket.py` - Updated to gate ai_debug channel by _is_internal() instead of group_system
- `ai_debug/static/src/debug_menu_button.js` - Registers 'Open AI Debugger' in Odoo debug menu (sequence 700, section tools)
- `ai_debug/static/src/app/main.js` - Entry point: whenReady + mountComponent(AiDebugApp, document.body)
- `ai_debug/static/src/app/app.js` - Root OWL component with bus_service subscription and connection status state
- `ai_debug/static/src/app/app.xml` - Three-zone template: header bar, 280px sidebar, flex detail panel
- `ai_debug/static/src/app/app.scss` - Dark theme (Catppuccin Mocha palette) with pulsing dot keyframe animation

## Decisions Made
- Used `auth='user'` (not `auth='public'`) so Odoo's auth mechanism handles unauthenticated redirect automatically before the controller body runs; `is_user_internal()` is only needed as the second gate for portal users
- Used `session_info()` (not `get_frontend_session_info()`) because the standalone app needs full session data for bus_service initialization
- Connection status is tracked via `addEventListener("BUS:WORKER_STATE_UPDATED", ...)` on the bus_service EventTarget, not via `bus_service.subscribe()` which is for bus message payloads

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Complete infrastructure layer in place: route, template, OWL bootstrap, bus subscription, debug menu
- Plan 03 can immediately build on the connected bus to receive and display real trace payloads
- No blockers

---
*Phase: 04-infrastructure*
*Completed: 2026-02-21*
