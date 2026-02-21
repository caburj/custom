---
status: complete
phase: 05-bus-instrumentation
source: 05-01-SUMMARY.md
started: 2026-02-21T12:00:00Z
updated: 2026-02-21T12:24:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Bus Events Fire on AI Session
expected: Open the AI Debug app in one tab with DevTools console open. Trigger an AI chat in another tab. Bus notifications should arrive on the 'ai_debug' channel — at minimum new_trace, iteration(s), and loop_end events.
result: issue
reported: "I triggered a chat that successfully finished, but nothing was logged in the debugger page."
severity: major

### 2. new_trace Payload Contains Agent Context
expected: The new_trace event payload includes: agent_name (or null), model_name, instructions (system prompt text), tools (array of tool definitions with schemas), and state_snapshot (with uid, company_id, lang, etc.).
result: pass

### 3. iteration Events Contain Message History
expected: Each iteration event contains messages_sent (array of messages sent to the LLM) and raw_response (LLM metadata). The messages_sent should NOT contain raw base64 binary data — any image/file content should be replaced with {type, _binary_excluded: true} stubs.
result: pass

### 4. tool_call Events Emit Per Tool Execution
expected: If the AI uses tools during the session, each tool execution produces a separate tool_call event with tool_name, args, result, success boolean, and state_before/state_after snapshots.
result: pass

### 5. loop_end Event With Stats
expected: When the AI session completes, a loop_end event arrives with termination_reason "success", iteration_count matching the number of iteration events, tool_call_count matching tool_call events, and duration_ms as a positive integer.
result: issue
reported: "loop_end event never emitted. _add_user_message returns early on final_message, abandoning the generator before post-loop code runs."
severity: major

### 6. Events Arrive In Real-Time (Not Batched)
expected: Events should arrive in the browser one-by-one as the agentic loop executes — the new_trace event appears before the first iteration, iteration events appear before loop_end. They should NOT all arrive at once after the HTTP response completes.
result: pass

### 7. Instrumentation Does Not Break AI Chat
expected: The AI chat session completes normally — the user gets a response from the AI assistant. The instrumentation should be invisible to the end user (no errors, no slowdown).
result: pass

## Summary

total: 7
passed: 4
issues: 2
pending: 0
skipped: 0

## Gaps

- truth: "Bus events should be visible in the AI Debug app when triggered"
  status: failed
  reason: "User reported: I triggered a chat that successfully finished, but nothing was logged in the debugger page."
  severity: major
  test: 1
  root_cause: "Phase 4 OWL app (app.js) subscribes to 'ai_debug' bus channel via addChannel() but has no notification event listener. Events ARE created in bus_bus table (verified via DB query: 8 events with correct payloads). The app only handles BUS:WORKER_STATE_UPDATED for connection status — it never calls busService.addEventListener('notification', handler). Phase 6 (sidebar) is meant to add this, but the Phase 4 shell should at minimum log incoming events to console for debuggability."
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      issue: "Missing addEventListener('notification', handler) to process incoming bus events"
  missing:
    - "Add notification event listener in app.js that logs incoming ai_debug events to console"
  debug_session: ""

- truth: "loop_end event emitted when agentic loop completes"
  status: failed
  reason: "loop_end event never emitted. _add_user_message returns early on final_message, abandoning generator."
  severity: major
  test: 5
  root_cause: "In ai/models/ai_session.py _add_user_message (line 112), when final_message is received, the method does 'return' which abandons the generator. Our _run_agentic_loop override's post-loop code (loop_end emit) runs only when the generator is fully exhausted. Since the consumer returns early, the generator is garbage-collected without executing the success-path loop_end emit. Fix: use try/finally in the override to ensure loop_end always fires, or emit loop_end before the final yield."
  artifacts:
    - path: "ai_debug/models/ai_session.py"
      issue: "_run_agentic_loop success-path loop_end (line 210) never reached because generator abandoned by consumer"
  missing:
    - "Move loop_end emit into a try/finally or GeneratorExit handler so it fires regardless of consumer behavior"
  debug_session: ""
