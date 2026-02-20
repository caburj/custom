---
phase: 03-live-panel-and-polish
plan: 02
subsystem: frontend
tags: [owl, bus.bus, websocket, real-time, debug-panel, json-tree, state-diff]

# Dependency graph
requires:
  - phase: 03-live-panel-and-polish
    plan: 01
    provides: bus_channel UUID, _sendone in write helpers, ir.actions.client, global ai_debug:traces channel
provides:
  - DebugPanel OWL component registered as ir.actions.client (tag=ai_debug.debug_panel)
  - JsonTree recursive collapsible JSON renderer with syntax highlighting and copy-to-clipboard
  - StateDiff side-by-side before/after diff viewer with change highlighting
  - Listen mode — panel auto-attaches to new traces via global ai_debug:traces channel
  - Standalone mode — hides Odoo navbar and chat widget for dedicated debug experience
  - Vertical timeline with latest-first ordering, nested tool calls, auto-scroll
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Listen mode: subscribe to global ai_debug:traces channel, auto-attach on new_trace event — no trace_id needed"
    - "All bus events on global channel with trace_id filtering — eliminates race between channel subscription and event dispatch"
    - "Lazy detail fetch: iteration/tool_call detail loaded via orm.read only when user expands"
    - "Standalone body class: document.body.classList.add/remove toggles Odoo chrome visibility"
    - "column-reverse CSS for latest-first iteration ordering without JS array reversal"

key-files:
  created:
    - ai_debug/static/src/debug_panel/json_tree/json_tree.js
    - ai_debug/static/src/debug_panel/json_tree/json_tree.xml
    - ai_debug/static/src/debug_panel/state_diff/state_diff.js
    - ai_debug/static/src/debug_panel/state_diff/state_diff.xml
    - ai_debug/static/src/debug_panel/debug_panel.js
    - ai_debug/static/src/debug_panel/debug_panel.xml
    - ai_debug/static/src/debug_panel/debug_panel.scss
  modified:
    - ai_debug/models/ai_session.py
    - ai_debug/models/ir_websocket.py

key-decisions:
  - "Global channel for all events: _debug_bus_send sends on ai_debug:traces (not per-trace channels) to avoid subscription race conditions"
  - "trace_id passed explicitly to _debug_bus_send — fixes context bug where self.env.context != debug_self.env.context"
  - "orm service instead of rpc service — rpc was removed in Odoo 17+"
  - "StateDiff props untyped (accept false/null from ORM) — computeDiff handles coercion internally"
  - "Standalone mode via CSS body class rather than separate controller — preserves bus_service and orm availability"

patterns-established:
  - "Pattern: listen mode with global bus channel + per-event trace_id filtering"
  - "Pattern: standalone body class for hiding web client chrome in dedicated tools"

requirements-completed: [LIVE-01, LIVE-02, LIVE-03]

# Metrics
duration: ~15min (including verification fixes)
completed: 2026-02-20
---

# Phase 03 Plan 02: Frontend OWL Debug Panel Summary

**Real-time OWL debug panel with bus subscription, collapsible JSON tree, state diff viewer, listen mode, and standalone presentation**

## Performance

- **Duration:** ~15 min (including human verification and iterative fixes)
- **Completed:** 2026-02-20
- **Tasks:** 3 (2 auto + 1 human-verify checkpoint)
- **Files:** 9 (7 created, 2 modified)

## Accomplishments

- **DebugPanel** OWL component registered as ir.actions.client, subscribes to global ai_debug:traces channel for listen mode — auto-attaches to new traces without needing trace_id in URL
- **JsonTree** recursive collapsible component with syntax highlighting (strings green, numbers blue, booleans orange, null gray, keys purple), copy-to-clipboard on hover, configurable maxDepth
- **StateDiff** side-by-side before/after viewer with added=green, removed=red, changed=yellow, unchanged collapsed with expandable summary
- **Listen mode**: open /odoo/ai-debug with no params → panel shows "Listening..." → auto-switches to new trace when agentic loop starts
- **Standalone mode**: body class hides navbar and chat widget for distraction-free debugging
- **Vertical timeline**: latest iteration at top (CSS column-reverse), detail tabs directly below iteration header, tool calls nested underneath
- **Auto-scroll**: follows latest event, pauses when user scrolls up, resumes when scrolled to bottom
- **Lazy detail fetch**: full iteration/tool_call data loaded via orm.read only on expand

## Task Commits

1. **Task 1: JsonTree and StateDiff subcomponents** — `3ee8a48` (feat)
2. **Task 2: DebugPanel main component with bus, timeline, styling** — `80f1eaf` (feat)
3. **Verification fixes** — `82e2ffa` (fix): bus context bug, standalone mode, listen mode, UX improvements
4. **Task 3: Human verification** — approved (all 11 steps pass after fixes)

## Deviations from Plan

- **Global bus channel instead of per-trace**: Plan specified per-trace channels (`ai_debug:trace:{uuid}`), but race conditions between channel subscription and event dispatch required switching to a single global `ai_debug:traces` channel with trace_id filtering
- **_debug_bus_send refactored**: trace_id passed explicitly instead of read from self.env.context — original context flow was broken (self vs debug_self)
- **Listen mode added**: Plan assumed trace_id always in URL; UX feedback led to auto-listen mode on the global channel
- **Standalone mode via CSS**: Plan didn't specify standalone presentation; added body class approach during verification
- **Iteration order reversed**: Latest iteration now at top per UX feedback
- **orm service instead of rpc**: Plan referenced rpc service which doesn't exist in Odoo 17+

## Issues Encountered

- `useService("rpc")` fails in Odoo 17+ — replaced with `useService("orm")` and `orm.read()`/`orm.searchRead()`
- Template arrow functions lost `this` context — bound interactive methods in setup()
- `_debug_bus_send` silently skipped all notifications — `self.env.context` didn't have `_debug_ctx` because methods were called on `self` not `debug_self`
- StateDiff OWL props validation rejected `false` from ORM Json fields — removed type constraint

---
*Phase: 03-live-panel-and-polish*
*Completed: 2026-02-20*
