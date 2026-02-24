---
status: complete
phase: 16-backend-token-extraction-and-per-iteration-timing
source: 16-01-SUMMARY.md
started: 2026-02-24T17:10:00Z
updated: 2026-02-24T17:18:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Module Loads Without Errors
expected: Start/restart the Odoo server with the ai_debug module installed. The server starts normally with no tracebacks or import errors related to ai_provider_patch.py or the monkey-patch on AIApiService._request.
result: pass

### 2. AI Conversation Works Normally
expected: Trigger an AI conversation (e.g. ask the AI assistant a question). The AI responds normally — the monkey-patch on _request does not disrupt or break LLM API calls.
result: pass

### 3. Iteration Bus Events Include Token Data
expected: During the AI conversation, server logs confirm iteration events include a `tokens` field with `{input, output, total}` keys, a `duration_ms` field (integer milliseconds), and provider detection (Google usageMetadata path confirmed).
result: pass

### 4. Tool Call Events Include Duration
expected: If the AI conversation involved tool calls, the `tool_call_completed` bus events should include a `duration_ms` field measuring how long the tool execution took.
result: pass

### 5. Token Fields Are Absent on Error Iterations
expected: If an error iteration occurs (or you can verify by code inspection), error iteration bus events should include `duration_ms` and `provider` but should NOT include a `tokens` field — absence of tokens signals failure per design.
result: skipped
reason: Hard to trigger naturally; verifiable by code inspection

## Summary

total: 5
passed: 4
issues: 0
pending: 0
skipped: 1

## Gaps

[none yet]
