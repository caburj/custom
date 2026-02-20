---
status: complete
phase: 02-backend-views
source: [02-01-SUMMARY.md]
started: 2026-02-20T10:50:00Z
updated: 2026-02-20T10:55:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Module upgrade succeeds
expected: Running `-u ai_debug` completes without errors or warnings about invalid views, missing fields, or duplicate labels.
result: pass

### 2. AI Debug menu appears under Settings > Technical
expected: Navigate to Settings app, enable Developer Mode if needed, go to Technical menu. An "AI Debug" section appears with three sub-items: Traces, Iterations, Tool Calls.
result: pass

### 3. Trace list view renders with correct columns
expected: Clicking Traces opens a list view showing columns: Agent, Model, State (as a colored badge), Iterations, Duration, and Date. State badges show colors (blue=running, green=done, red=error, yellow=paused). If no traces exist yet, the list is empty but columns are visible in the header.
result: skipped

### 4. Trace form view with tabbed layout
expected: Clicking a trace record (or creating one via instrumentation) opens a form with two column groups at top (agent, model, state badge, termination reason on left; start time, duration, iteration count on right) and a notebook with 3 tabs: "Iterations", "System Prompt & RAG", "Error Details". Error Details tab is hidden unless trace state is "error".
result: pass

### 5. Iteration form with ace JSON editors
expected: From a trace form, clicking an iteration row opens an iteration form with 4 tabs: "Messages Sent" (JSON in syntax-highlighted ace editor), "Raw Response" (ace editor), "State Snapshots" (ace editors for before/after), "Tool Calls" (embedded list of tool calls).
result: pass

### 6. Tool call form with arguments and result
expected: From an iteration form, clicking a tool call row opens a tool call form with 4 tabs: "Arguments" (ace JSON editor), "Result" (plain text, not ace), "Confirmation" (hidden unless triggered_confirmation is true), "State Snapshots" (ace editors).
result: pass

### 7. Trace search filters and group-by
expected: In the trace list, the search bar shows filter options for Agent, Model, State, and Error Message. Preset filters "Errors" and "Today" are available. Group By options include Agent, Model, and State. The "Today" filter is active by default (from action context).
result: pass

### 8. Tool call search with Confirmations filter
expected: In the tool call list (accessible via menu), the search bar has a tool_name filter and a preset "Confirmations" filter that shows only tool calls where confirmation was triggered.
result: pass

## Summary

total: 8
passed: 7
issues: 0
pending: 0
skipped: 1

## Gaps

[none yet]
