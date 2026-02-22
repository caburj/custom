# Phase 5: Bus Instrumentation - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Rewrite the instrumentation layer so a running agentic loop emits four structured bus event types (new_trace, iteration, tool_call, loop_end) with full payloads over bus.bus. Events use UUID identifiers, separate cursors for real-time delivery, and arrive one-by-one in the browser console. No frontend rendering — Phases 6 and 7 consume these events.

</domain>

<decisions>
## Implementation Decisions

### Event payload structure
- Tools definition in `new_trace` event: include full JSON schemas (name, description, parameters) — not just names
- Raw LLM response in iteration events: include the full API response object (content, usage stats, finish_reason, model info, token counts)
- All events go on a single `ai_debug` channel, differentiated by a `type` field in the payload (not per-type channels)

### Claude's Discretion: Payload structure details
- `messages_sent` in iteration events: Claude decides whether to send full conversation history or deltas, based on payload size tradeoffs and downstream complexity
- Field naming convention (snake_case vs camelCase): Claude decides based on Odoo conventions and bus layer patterns

### State snapshot scope
- Capture everything available: discuss context (partner, channel), environment (uid, company, lang), tool registry, model config — full picture
- Send full state snapshots each time; the OWL frontend computes diffs for display (not backend-computed diffs)
- State snapshots taken both before and after each tool call — detail panel shows exactly what a tool changed

### Claude's Discretion: Initial state in new_trace
- Whether the `new_trace` event includes a baseline state snapshot — research the `ai` module's agentic loop to determine what state is available at loop start and whether a baseline adds value

### Large payload handling
- No size limits or truncation — send everything. This is a dev tool, optimize later if needed
- Instrumentation pre-serializes all Python objects to JSON-safe dicts before sending (no relying on bus.bus serialization for complex objects)
- Exclude binary content from payloads; include metadata only (filename, size, mimetype). Binaries have corresponding ir.attachment records that can be leveraged in a future phase

### Loop lifecycle events
- Explicit `loop_end` event when the agentic loop finishes, carrying termination reason (success, max iterations, error, user cancel)
- `loop_end` includes summary stats: iteration_count, tool_call_count, duration_ms, termination_reason
- Tool call errors: emit normal tool_call event with an `error` field (verify serialization of tool errors in the `ai` module). Not a separate event type
- LLM API failures (network, rate limit, timeout): part of the iteration event with an error field instead of raw_response. Failed iteration still appears in the tree

</decisions>

<specifics>
## Specific Ideas

- "Each binary has a corresponding ir.attachment record, so later those can be utilized" — design the metadata exclusion to be forward-compatible with future binary inclusion via attachment IDs
- Verify how tool call errors are currently serialized in the `ai` module before deciding the error field structure

</specifics>

<deferred>
## Deferred Ideas

- Binary content inclusion in payloads via ir.attachment — future enhancement
- Subagent nesting in event hierarchy — deferred per REQUIREMENTS.md (NEST-01)

</deferred>

---

*Phase: 05-bus-instrumentation*
*Context gathered: 2026-02-21*
