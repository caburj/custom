---
status: complete
phase: 01-data-models-and-instrumentation
source: [01-01-SUMMARY.md, 01-02-SUMMARY.md]
started: 2026-02-20T10:00:00Z
updated: 2026-02-20T10:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Module Installation
expected: The `ai_debug` module appears in the Apps list (with "Apps" filter removed). Installing it succeeds without errors. It depends on the `ai` module.
result: pass

### 2. Debug Trace Created on AI Interaction
expected: After using the AI assistant (e.g., sending a message in the AI panel), an `ai.debug.trace` record is created. You can verify via Settings > Technical > Database Structure > Models, or via shell: `self.env['ai.debug.trace'].search([])`. The record should have fields like `model_id`, `state`, `start_time`, `end_time`.
result: pass
note: Initial attempt crashed with `AttributeError: 'ir.config_parameter' object has no attribute 'get_param'`. Fixed by migrating to new typed API: `get_bool` for enabled flag, `get_int` for retention days. Passed on retry.

### 3. Iteration Records Captured
expected: Each LLM call within an AI interaction creates an `ai.debug.iteration` record linked to the trace. The iteration contains `messages_sent` (JSON of what was sent to the LLM) and `raw_response` (the LLM's response). Check via shell: `self.env['ai.debug.iteration'].search([])`.
result: pass

### 4. Tool Call Records Captured
expected: If the AI assistant executes any tools during the interaction, `ai.debug.tool.call` records are created linked to the iteration. Each contains `tool_name`, `args` (JSON), and `result`. Check via shell: `self.env['ai.debug.tool.call'].search([])`.
result: pass

### 5. Config Toggle Disables Capture
expected: Setting system parameter `ai_debugger.enabled` to `False` (Settings > Technical > Parameters > System Parameters) disables all debug capture. After toggling off and running another AI interaction, no new debug records are created.
result: skipped

### 6. Admin-Only Access
expected: Only users with Administration/Settings access (base.group_system) can read/write debug records. A non-admin user accessing these models via shell or RPC should get an AccessError.
result: skipped

### 7. Cascade Delete
expected: Deleting an `ai.debug.trace` record also deletes all its linked iterations and tool calls. Verify via shell: delete a trace, then confirm its iterations and tool calls no longer exist.
result: skipped

## Summary

total: 7
passed: 4
issues: 0
pending: 0
skipped: 3

## Gaps

[none yet]
