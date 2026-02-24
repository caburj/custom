# Phase 13: Python Instrumentation and Bus Event Handling - Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Backend emits parent linkage in bus events so the frontend knows subagent causality. Frontend buffers out-of-order bus events and handles the split tool call lifecycle (started vs completed). Existing non-subagent sessions continue working with no behavioral change.

</domain>

<decisions>
## Implementation Decisions

### Bus event payload shape
- `new_trace` event includes `parent_trace_id` (UUID of parent agentic loop's trace) and `parent_tool_call_id` (ID of the tool call that spawned the subagent)
- For root sessions, both fields are present but set to `null` — consistent payload shape, no field-existence checks needed
- Agent name is NOT included in the event payload — derived from `agent_id` on the `ai.session` record
- No `parent_session_id` (ORM ID) needed — `parent_trace_id` is the direct pointer the frontend works with

### Tool call event splitting
- Current: tool calls emit a single event on completion (with args + result)
- New: two distinct events — `tool_call_started` (id, name, args) and `tool_call_completed` (id, result)
- This ensures the parent tool call node exists in the UI before the subagent trace arrives, minimizing the orphan buffer window

### Orphan trace handling
- If a child trace arrives before its parent tool call, buffer it (pending-child buffer)
- After 30 seconds timeout, promote orphaned traces to root level
- Retain parent references (`parent_trace_id`, `parent_tool_call_id`) even after root promotion
- If the parent tool call eventually arrives, silently re-attach the trace to the correct parent — no visual indicator

### Buffer strategy
- Uncapped buffer size — subagent traces per session are few, no need for a hard limit
- Buffer logic placement: Claude's discretion (inline in event handler or separate module)
- IDB hydration uses a separate two-pass process (first pass loads all traces, second pass links parents) — does NOT reuse the live buffer logic

### Context threading (Python backend)
- Use `env.context` to pass parent trace info to child sessions — Odoo's standard contextual data mechanism
- Two context keys: `ai_parent_trace_id` and `ai_parent_tool_call_id`
- Child session reads these keys and includes the values in its `new_trace` bus event
- Parent linkage is bus-event-only — no persistence on the `ai.session` ORM record
- Injection point: Claude's discretion (base `_handle_tool_calls` vs subagent-specific override)

### Claude's Discretion
- Buffer module architecture (inline vs dedicated module)
- Context injection point (base model vs subagent override)
- Exact `tool_call_started` / `tool_call_completed` event naming and structure (following existing bus event conventions)

</decisions>

<specifics>
## Specific Ideas

- Tool call splitting is motivated by the subagent arrival ordering problem — the user observed that tool_call events only fire on completion, meaning the subagent trace always arrives before the parent tool call exists in the UI
- Orphan re-attachment should be silent — no animations or indicators when a promoted trace slides back under its parent
- Two-pass IDB hydration is explicitly separate from live buffer logic — all data is available at hydration time, no timeout-based promotion needed

</specifics>

<deferred>
## Deferred Ideas

- Exact parent tool call matching via `parent_call_id` for parallel subagent disambiguation (NEST-02 in requirements — deferred to v1.4.1)
- Persisting parent linkage on `ai.session` ORM for server-side parent queries — not needed for current UI-only use case

</deferred>

---

*Phase: 13-python-instrumentation-and-bus-event-handling*
*Context gathered: 2026-02-23*
