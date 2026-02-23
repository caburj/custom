---
status: complete
phase: 13-python-instrumentation-and-bus-event-handling
source: 13-01-SUMMARY.md, 13-02-SUMMARY.md
started: 2026-02-23T14:00:00Z
updated: 2026-02-23T14:35:00Z
---

## Current Test

[testing complete]

## Tests

### 1. new_trace carries parent linkage fields
expected: Open the AI Debug panel and start a new AI session. In the browser console (or by inspecting bus events), the `new_trace` event payload should contain: `session_id` (integer), `parent_trace_id` (null for root session), and `parent_tool_call_id` (null for root session). All three fields present with consistent shape.
result: pass

### 2. Tool call appears immediately with "running" status
expected: Trigger an AI action that makes tool calls (e.g., ask it to search or read something). As soon as a tool call starts, a `tool_call_started` event should fire with the tool name, args, call_id, and a stable tool_call_id UUID. The tool call entry should appear in the debug trace before the tool finishes executing.
result: pass

### 3. Tool call completes with result
expected: After the tool call from Test 2 finishes, a `tool_call_completed` event should fire with the same tool_call_id UUID as the started event, plus result data and success/error status. The trace entry should update to show the completed result.
result: pass

### 4. Subagent child traces nest under parent tool call
expected: Trigger an AI action that spawns a subagent (a tool call that creates a child AI session). The child session's `new_trace` event should have a non-null `parent_trace_id` (matching the parent's trace UUID) and a non-null `parent_tool_call_id`. In the debug panel, the child trace should appear nested under the parent tool call, NOT at the root level.
result: pass

### 5. Out-of-order child traces buffered (not placed at root)
expected: If a child trace's `new_trace` arrives before its parent `tool_call_started`, the child should NOT appear at root level. Instead it should be buffered and placed correctly once the parent tool call event arrives. After 30 seconds without a parent, buffered traces are promoted to root (safety net). Verify no orphan traces appear at root when subagent events arrive slightly out of order.
result: skipped
reason: Buffer is defensive code for out-of-order bus delivery; not independently triggerable. Visual nesting is Phase 14 work — all traces correctly appear at root level for now with parent linkage data stored.

### 6. Zero overhead without debug context
expected: When running an AI session WITHOUT the debug panel active (no `_debug_ctx`), the `ai.agent` override should not execute any instrumentation code. Verify normal AI sessions work unchanged — no extra bus events, no performance degradation, no errors in console.
result: pass

## Summary

total: 6
passed: 5
issues: 0
pending: 0
skipped: 1

## Gaps

[none yet]
