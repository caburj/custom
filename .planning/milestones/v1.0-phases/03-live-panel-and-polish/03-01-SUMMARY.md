---
phase: 03-live-panel-and-polish
plan: 01
subsystem: api
tags: [bus.bus, websocket, odoo, real-time, streaming, uuid]

# Dependency graph
requires:
  - phase: 01-data-models-and-instrumentation
    provides: ai.debug.trace, ai.debug.iteration, ai.debug.tool.call models and separate-cursor write helpers
  - phase: 02-backend-views
    provides: trace form view to add the Open Live Panel button to
provides:
  - bus_channel UUID field on ai.debug.trace for real-time channel identity
  - _debug_bus_send helper dispatching bus.bus._sendone on ai_debug:trace:{uuid} channel
  - _sendone calls in all three write helpers (iteration, tool_call, trace_update) inside cursor blocks
  - IrWebsocket._build_bus_channel_list override stripping ai_debug channels for non-system users
  - ir.actions.client record (tag=ai_debug.debug_panel, path=ai-debug) for Plan 02 frontend
  - action_open_live_panel method on ai.debug.trace returning act_url for new tab
  - Open Live Panel header button on trace form
  - web.assets_backend glob patterns for Plan 02 JS/XML/SCSS files
affects: [03-02-live-panel-and-polish, frontend debug panel OWL component]

# Tech tracking
tech-stack:
  added: [bus (odoo module dependency added)]
  patterns:
    - "Separate cursor + _sendone inside cursor block — pg_notify fires on cursor commit, not HTTP response"
    - "UUID bus channel per trace — frontend subscribes via unique channel, no cross-user leakage"
    - "IrWebsocket override strips channels for non-system users (spreadsheet_edition pattern)"
    - "Summary-only bus payloads — no messages_sent/raw_response; frontend RPC-fetches detail"
    - "_debug_bus_send reads bus_channel from self.env.context._debug_ctx, receives local env argument"

key-files:
  created:
    - ai_debug/models/ir_websocket.py
    - ai_debug/views/debug_panel_action.xml
  modified:
    - ai_debug/models/ai_debug_trace.py
    - ai_debug/models/ai_session.py
    - ai_debug/models/__init__.py
    - ai_debug/views/ai_debug_trace_views.xml
    - ai_debug/__manifest__.py

key-decisions:
  - "_sendone called via _debug_bus_send helper receiving local cursor env — avoids duplicating channel lookup in three places"
  - "bus_channel stored in debug_ctx mutable dict so _handle_tool_calls override can reach it via context without extra args"
  - "_debug_write_trace returns (trace_id, bus_channel) tuple — bus_channel needed in debug_ctx before loop starts"
  - "web.assets_backend glob added pre-emptively before JS files exist — harmless, enables Plan 02 to just drop files in place"

patterns-established:
  - "Pattern: bus_channel = str(uuid.uuid4()) in field default, not assigned in create — Odoo handles it atomically"
  - "Pattern: _debug_bus_send(env, event_type, payload) — env from cursor, payload is summary only"

requirements-completed: [LIVE-01]

# Metrics
duration: 2min
completed: 2026-02-20
---

# Phase 03 Plan 01: Backend Bus Pipeline Summary

**UUID-keyed bus.bus notification pipeline for real-time debug streaming: _sendone in all write helpers inside separate cursor blocks, IrWebsocket channel security, ir.actions.client action, and Open Live Panel button**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-20T11:42:23Z
- **Completed:** 2026-02-20T11:44:56Z
- **Tasks:** 2
- **Files modified:** 7 (5 modified, 2 created)

## Accomplishments

- Backend bus pipeline complete: every iteration, tool call, and trace state change fires a bus.bus notification on the trace's UUID channel inside a separate cursor block (pg_notify fires at cursor commit, not HTTP response)
- Channel security enforced via IrWebsocket._build_bus_channel_list override — non-system users cannot subscribe to ai_debug:trace: channels
- ir.actions.client record (tag=ai_debug.debug_panel, path=ai-debug) registered so Plan 02 OWL component can be wired in; Open Live Panel header button on trace form opens /odoo/ai-debug?trace_id=N in a new tab
- Manifest updated with 'bus' dependency and web.assets_backend glob patterns ready for Plan 02 frontend files

## Task Commits

Each task was committed atomically:

1. **Task 1: Add bus_channel field, IrWebsocket override, and _sendone in write helpers** - `0895456` (feat)
2. **Task 2: Create ir.actions.client XML, add Open Live Panel button, update manifest** - `911b78c` (feat)

## Files Created/Modified

- `ai_debug/models/ai_debug_trace.py` - Added `bus_channel` UUID field (readonly, copy=False, index) and `action_open_live_panel` method
- `ai_debug/models/ai_session.py` - `_debug_write_trace` now returns `(trace_id, bus_channel)` tuple; `debug_ctx` gains `bus_channel`; `_debug_bus_send` helper added; `_sendone` calls in all three cursor write helpers
- `ai_debug/models/ir_websocket.py` - New file: IrWebsocket override strips `ai_debug:trace:` channels for non-system users
- `ai_debug/models/__init__.py` - Added `from . import ir_websocket`
- `ai_debug/views/debug_panel_action.xml` - New file: `ir.actions.client` with tag=ai_debug.debug_panel and path=ai-debug
- `ai_debug/views/ai_debug_trace_views.xml` - Added `<header>` with Open Live Panel button (type=object, class=oe_highlight)
- `ai_debug/__manifest__.py` - Added 'bus' to depends, debug_panel_action.xml to data, web.assets_backend glob entry

## Decisions Made

- `_debug_write_trace` returns `(trace_id, bus_channel)` tuple rather than just `trace_id` — bus_channel must be available in `debug_ctx` from the start of the loop so all subsequent write helpers can reach it
- `_debug_bus_send` is a separate helper method receiving the local cursor `env` — avoids duplicating the channel lookup and try/except pattern in three write helpers
- `_debug_bus_send` reads `bus_channel` from `self.env.context._debug_ctx` (not from `env`) — `self` still carries the original context chain; the `env` arg is only used for `env['bus.bus']._sendone` to ensure notification fires on cursor commit
- Payloads are summary-only (no messages_sent, raw_response, state_before, state_after) — frontend RPC-fetches full detail on demand

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Backend bus pipeline fully complete; Plan 02 can implement the OWL DebugPanel component and subscribe to `ai_debug:trace:{bus_channel}` channels immediately
- The ir.actions.client tag `ai_debug.debug_panel` must match exactly what Plan 02 registers in the JS action registry
- web.assets_backend glob is in place so Plan 02 only needs to create files under `ai_debug/static/src/`

---
*Phase: 03-live-panel-and-polish*
*Completed: 2026-02-20*
