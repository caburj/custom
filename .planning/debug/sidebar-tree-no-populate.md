---
status: diagnosed
trigger: "The AI Debugger sidebar tree does not populate when an AI chat is triggered"
created: 2026-02-21T12:00:00Z
updated: 2026-02-21T12:00:00Z
---

## Current Focus

hypothesis: reactive(new Map()) without callback does not integrate with OWL component rendering
test: traced OWL source code for reactive(), useState(), observeTargetKey(), delegateAndNotify()
expecting: confirmed that NO_CALLBACK sentinel causes observeTargetKey to skip registration
next_action: return diagnosis — fix is to use useState(new Map()) instead of reactive(new Map())

## Symptoms

expected: When an AI agent loop runs, the sidebar should receive bus events and populate a three-level tree
actual: UI shows "Waiting for traces..." and "Listening for agentic loops..." permanently — no tree entries appear
errors: None visible (no console errors reported)
reproduction: Open /ai-debug, trigger an AI action in Odoo
started: Since phase 06-sidebar-tree was built

## Eliminated

- hypothesis: Bus event name mismatch between Python backend and JS frontend
  evidence: Python sends 'new_trace', 'iteration', 'tool_call', 'loop_end'; JS subscribes to exactly the same names. Verified in ai_session.py _ai_debug_bus_send calls and app.js busService.subscribe calls.
  timestamp: 2026-02-21T12:00:00Z

- hypothesis: Bus subscription mechanism broken (subscribe/notificationBus wiring)
  evidence: Traced bus_service.js handleMessage -> notificationBus.trigger(type, {id, payload}) -> subscribe wrapper -> callback(payload). The type from Python _sendone notification_type matches the subscribe notificationType. Wiring is correct.
  timestamp: 2026-02-21T12:00:00Z

- hypothesis: Channel gating (ir_websocket) blocks ai_debug channel for internal users
  evidence: The override only filters for non-internal users. Internal users pass all channels through unchanged.
  timestamp: 2026-02-21T12:00:00Z

- hypothesis: Standalone app doesn't bootstrap bus_service properly
  evidence: mountComponent() in main.js calls makeEnv() + startServices(), which starts all services including bus_service. The ai_debug.assets bundle includes web.assets_backend which provides all bus dependencies.
  timestamp: 2026-02-21T12:00:00Z

- hypothesis: Bus service not connecting (websocket not established)
  evidence: session_info includes websocket_worker_version from bus/models/ir_http.py. Worker service starts, initializes websocket. addChannel("ai_debug") triggers BUS:START.
  timestamp: 2026-02-21T12:00:00Z

## Evidence

- timestamp: 2026-02-21T12:00:00Z
  checked: OWL reactive() function signature and NO_CALLBACK sentinel
  found: reactive(target, callback = NO_CALLBACK) — when no callback provided, NO_CALLBACK is used
  implication: NO_CALLBACK is a sentinel that causes observeTargetKey() to return early without registering

- timestamp: 2026-02-21T12:00:00Z
  checked: OWL observeTargetKey() with NO_CALLBACK
  found: "if (callback === NO_CALLBACK) { return; }" — reads from a reactive with NO_CALLBACK never subscribe
  implication: No component render function is registered as observer for this.traces

- timestamp: 2026-02-21T12:00:00Z
  checked: OWL useState() implementation
  found: "function useState(state) { ... return reactive(state, render); }" — useState passes the component's batched render function as the callback
  implication: Only useState-wrapped state integrates with component rendering

- timestamp: 2026-02-21T12:00:00Z
  checked: OWL delegateAndNotify for Map.set()
  found: Calls notifyReactives(target, KEYCHANGES) when new key added, but no callbacks registered because observeTargetKey was never called with a real callback
  implication: Map.set() on a no-callback reactive notifies zero observers — no re-render

- timestamp: 2026-02-21T12:00:00Z
  checked: How mail module uses reactive(new Map()) successfully
  found: recordByLocalId in make_store.js is stored as property of a reactive store object. When accessed through the parent reactive proxy (which has a callback), possiblyReactive() wraps it with the same callback.
  implication: reactive(new Map()) works ONLY when accessed through a parent reactive that has a callback. Direct property access on component bypasses this.

- timestamp: 2026-02-21T12:00:00Z
  checked: app.js event handlers for side effects on this.state
  found: _onNewTrace, _onIteration, _onToolCall, _onLoopEnd never touch this.state — only this.traces and plain instance properties
  implication: No accidental re-render trigger exists — the UI truly never updates

## Resolution

root_cause: this.traces = reactive(new Map()) creates a reactive proxy with NO_CALLBACK, which means OWL's rendering system never subscribes to changes. Map mutations (set/delete/clear) notify zero observers. The tree template reads traces.size and traces.keys() but these reads do not register the component's render function. Result: bus events arrive and populate the Map in memory, but the DOM is never updated.
fix: Replace reactive(new Map()) with useState(new Map()) so the component's render function is registered as observer
verification: pending
files_changed: []
