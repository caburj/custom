# Phase 4: Infrastructure - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Delete all v1.0 DB-backed architecture (ORM models, backend views, menus, security CSV) and scaffold a standalone OWL app at `/ai-debug` with a sidebar/detail split layout, connected to bus_service on a single `ai_debug` channel. This phase delivers the empty shell — content and real-time data population come in Phases 5-7.

</domain>

<decisions>
## Implementation Decisions

### App shell skeleton
- Scaffold the sidebar + detail panel split layout from the start with placeholder content (later phases fill it in)
- Include a thin header/toolbar at the top for app title and connection status
- Stub sidebar shows empty state; stub detail panel shows "Listening for agentic loops..." with animated indicator (pulsing dot or similar)

### v1.0 cleanup scope
- Delete all v1.0 Python model files entirely — no refactoring to dataclasses, clean slate for Phase 5
- Delete all backend view XML, menu XML, and security CSV (ir.model.access) files
- Rewrite `__manifest__.py` from scratch — fresh manifest declaring only what v1.1 needs
- Keep `ai` module as a dependency (that's where the agentic loop lives)

### Instrumentation hooks
- Claude's discretion on whether to keep or delete v1.0 instrumentation hooks — assess what's reusable vs too coupled to ORM

### Access & discovery
- Add a button in the `debug_menu.js` component that opens `/ai-debug` in a new tab
- Debug menu is already gated behind debug mode — no extra gating needed on the button
- The `/ai-debug` route itself requires any internal user (`base.group_user`) — no debug mode check on the route

### Bus connection UX
- Subscribe to a single `ai_debug` bus channel — different event types (new_trace, iteration, tool_call, etc.) are distinguished by message type within the payload
- Always-visible connection status indicator in the header — green dot for connected, red for disconnected
- Auto-reconnect silently on connection drop — status dot goes red briefly, then green; no banner or user action needed
- Empty state: animated indicator (pulsing dot) + "Listening for agentic loops..." text

### Claude's Discretion
- Visual direction (dark/light theme) — pick what fits a developer debugging tool
- Loading skeleton and exact spacing/typography
- Error state handling
- Exact animated indicator design for the listening state
- How to structure the bus message type field within payloads

</decisions>

<specifics>
## Specific Ideas

- No specific reference app — just make it functional and clean
- The debug menu button should open `/ai-debug` in a new tab so the developer keeps their current Odoo session

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-infrastructure*
*Context gathered: 2026-02-21*
