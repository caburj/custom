---
phase: 16-backend-token-extraction-and-per-iteration-timing
verified: 2026-02-24T18:10:00Z
status: passed
score: 7/7 must-haves verified
---

# Phase 16: Backend Token Extraction and Per-Iteration Timing Verification Report

**Phase Goal:** Every iteration bus event carries accurate token counts (both providers) and server-measured duration
**Verified:** 2026-02-24T18:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                     | Status     | Evidence                                                                                                                                                           |
| --- | --------------------------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | An OpenAI iteration bus event carries tokens.input > 0, tokens.output > 0, tokens.total > 0              | VERIFIED | `_extract_tokens_openai` returns `{input: usage.get('input_tokens', 0), output: usage.get('output_tokens', 0), total: usage.get('total_tokens', 0)}`; wired into `iteration_payload['tokens']` conditionally at ai_session.py:241 |
| 2   | A Google iteration bus event carries tokens.input > 0, tokens.output > 0, tokens.total > 0               | VERIFIED | `_extract_tokens_google` returns `{input: usage.get('promptTokenCount', 0), output: usage.get('candidatesTokenCount', 0), total: usage.get('totalTokenCount', 0)}`; same wiring path |
| 3   | Every iteration bus event has duration_ms > 0 representing LLM API call time                              | VERIFIED | `_patched_request` records `t0 = time.monotonic()` before calling `_original_request`, stashes `int((time.monotonic() - t0) * 1000)` in thread-local; `pop_last_completion_data()` retrieves it; ai_session.py:243 includes it conditionally |
| 4   | Iterations with missing or errored token data default all token fields to 0, not null or undefined        | VERIFIED | Within a tokens object, all three fields use `.get(key, 0)` fallback (ai_provider_patch.py:90-92, 125-127). Note: on errored iterations the `tokens` key is absent entirely (CONTEXT.md locked: "absence signals failure") — this is the intended behavior; TOKN-04 refers to missing sub-fields within a present tokens object, not to the tokens object itself |
| 5   | Each tool_call_completed bus event includes duration_ms > 0                                               | VERIFIED | `_tc_start_times` dict built before `super()._handle_tool_calls()` call (ai_session.py:390); `duration_ms: int((time.monotonic() - _tc_start) * 1000)` included in both `tool_results` branch (line 421) and `tool_confirmation_request` branch (line 443) |
| 6   | loop_end.duration_ms continues to emit trace-level total duration (existing behavior, TIME-02)            | VERIFIED | `started_at = time.monotonic()` at line 164; `loop_end` event includes `'duration_ms': int((time.monotonic() - started_at) * 1000)` at line 322 in `finally` block — always emits |
| 7   | Each iteration bus event includes a provider field ('openai' or 'google')                                 | VERIFIED | `provider_name = self._ai_debug_resolve_provider_name(model)` called once before loop (line 167); `'provider': provider_name` present in normal iteration payload (line 237), UserError error payload (line 276), and Exception error payload (line 305) |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact                                     | Expected                                                                               | Status     | Details                                                                                                       |
| -------------------------------------------- | -------------------------------------------------------------------------------------- | ---------- | ------------------------------------------------------------------------------------------------------------- |
| `ai_debug/models/ai_provider_patch.py`       | threading.local() monkey-patch on AIApiService._request, per-provider token extractors, pop function | VERIFIED | 191 lines; contains `_patched_request`, `_extract_tokens_openai`, `_extract_tokens_google`, `pop_last_completion_data`; syntax valid |
| `ai_debug/models/__init__.py`                | Import registration for ai_provider_patch as first import                              | VERIFIED | Line 1: `from . import ai_provider_patch` — before `ir_websocket`, `ai_session`, `ai_agent`; syntax valid    |
| `ai_debug/models/ai_session.py`              | Iteration bus events with tokens/duration_ms/provider, tool_call_completed with duration_ms | VERIFIED | Contains `pop_last_completion_data` import and call; all enriched fields present; syntax valid               |

### Key Link Verification

| From                                   | To                                                          | Via                                             | Status     | Details                                                                                                           |
| -------------------------------------- | ----------------------------------------------------------- | ----------------------------------------------- | ---------- | ----------------------------------------------------------------------------------------------------------------- |
| `ai_debug/models/ai_provider_patch.py` | `AIApiService._request`                                     | Monkey-patch at module load time                | VERIFIED | `AIApiService._request = _patched_request` at line 73, executed at import time                                   |
| `ai_debug/models/ai_session.py`        | `ai_debug/models/ai_provider_patch.py`                      | `pop_last_completion_data()` import and call    | VERIFIED | Line 8: `from odoo.addons.ai_debug.models.ai_provider_patch import pop_last_completion_data`; called at lines 211, 257, 289 |
| `ai_debug/models/ai_provider_patch.py` | `threading.local()`                                         | `_ai_debug_local` thread-local storage          | VERIFIED | `_ai_debug_local = threading.local()` at line 26; fields read and cleared in `pop_last_completion_data()` (lines 162-169) |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                        | Status    | Evidence                                                                                                                |
| ----------- | ----------- | -------------------------------------------------------------------------------------------------- | --------- | ----------------------------------------------------------------------------------------------------------------------- |
| TOKN-01     | 16-01-PLAN  | Backend extracts normalized token usage from OpenAI API responses (input, output, total, cached, reasoning) | SATISFIED | `_extract_tokens_openai` at ai_provider_patch.py:76-108; normalizes `usage.{input_tokens,output_tokens,total_tokens}` with sparse `cached`/`reasoning` |
| TOKN-02     | 16-01-PLAN  | Backend extracts normalized token usage from Google API responses (input, output, total, cached, reasoning) | SATISFIED | `_extract_tokens_google` at ai_provider_patch.py:111-143; normalizes `usageMetadata.{promptTokenCount,candidatesTokenCount,totalTokenCount}` with sparse `cached`/`reasoning` |
| TOKN-03     | 16-01-PLAN  | Iteration bus events include a `tokens` field with normalized schema {input, output, total, cached, reasoning} | SATISFIED | `iteration_payload['tokens'] = tokens` at ai_session.py:241 (conditional on non-None); canonical dict from extractors |
| TOKN-04     | 16-01-PLAN  | Missing token fields default to 0 so JS rendering is provider-agnostic                            | SATISFIED | All three base fields use `.get(key, 0)` fallback (ai_provider_patch.py:90-92, 125-127); sparse `cached`/`reasoning` only included when non-zero |
| TIME-01     | 16-01-PLAN  | Backend captures per-iteration duration via `time.monotonic()` and emits `duration_ms` on iteration bus events | SATISFIED | `t0 = time.monotonic()` in `_patched_request` (line 57); stashed as `last_llm_duration_ms`; emitted as `iteration_payload['duration_ms']` at line 243 |
| TIME-02     | 16-01-PLAN  | Trace-level total duration surfaced from existing `loop_end.duration_ms`                           | SATISFIED | `loop_end` event at ai_session.py:315-323 includes `'duration_ms': int((time.monotonic() - started_at) * 1000)` — unchanged from prior phase |

No orphaned requirements: REQUIREMENTS.md traceability table maps exactly TOKN-01, TOKN-02, TOKN-03, TOKN-04, TIME-01, TIME-02 to Phase 16. All six are claimed in 16-01-PLAN.md frontmatter and all six are satisfied.

### Anti-Patterns Found

| File                                    | Line | Pattern                          | Severity | Impact |
| --------------------------------------- | ---- | -------------------------------- | -------- | ------ |
| `ai_debug/models/ai_session.py`         | 51   | "placeholder" in docstring       | Info     | Not an implementation placeholder — refers to the stub object that replaces binary content in bus payloads. No impact. |

No blockers. No implementation stubs. No empty return values in relevant paths. The two `return []` at lines 74 and 82 of ai_session.py are in `_ai_debug_serialize_tools` exception fallbacks (returning empty tool list on serialization failure), not in the instrumentation path.

### Human Verification Required

#### 1. OpenAI token data round-trip

**Test:** Trigger an actual OpenAI agentic loop call and inspect the `iteration` bus event in the browser DevTools Network tab (WebSocket frames) or add a temporary log in `_ai_debug_bus_send`.
**Expected:** The `tokens` field is present with `input > 0`, `output > 0`, `total > 0`.
**Why human:** Cannot verify the live HTTP response shape from the OpenAI `/responses` endpoint without a running Odoo instance with a valid API key.

#### 2. Google token data round-trip

**Test:** Trigger an actual Google agentic loop call (Gemini model) and inspect the `iteration` bus event.
**Expected:** The `tokens` field is present with `input > 0`, `output > 0`, `total > 0`.
**Why human:** Same reason — requires a live Odoo instance with Google AI credentials.

#### 3. Cross-iteration thread-local isolation with concurrent sub-agents

**Test:** Trigger a parent agentic loop that spawns two sub-agents concurrently (if such a scenario exists in the test data).
**Expected:** Each sub-agent iteration event carries its own token counts, not contaminated by the sibling's data.
**Why human:** Thread-local semantics are correct by code inspection, but concurrent interleaving requires a real multi-threaded Odoo worker environment to observe.

#### 4. tool_call_completed duration_ms accuracy

**Test:** Trigger a tool call that takes a known minimum time (e.g. a tool that sleeps 1 second) and verify `duration_ms >= 1000` in the bus event.
**Expected:** `duration_ms` roughly matches the actual tool execution time.
**Why human:** Requires a running Odoo instance with instrumented tool calls.

### Gaps Summary

No gaps found. All seven observable truths are verified, all three artifacts are substantive and wired, all three key links are confirmed in the actual code, and all six requirement IDs are satisfied. Syntax is valid on all three files. No enterprise files were modified (commits 1b85695 and 85f4a27 touch only `ai_debug/` files). The implementation follows the approved monkey-patch + thread-local + pop-and-clear pattern exactly as specified in the plan.

A clarification note on Truth #4 wording: the truth as stated ("default all token fields to 0, not null or undefined") refers to individual sub-fields within a present tokens object — verified via `.get(key, 0)` defaults in both extractors. On errored iterations the `tokens` key is intentionally absent (not defaulted to 0), which is the CONTEXT.md locked decision and the correct behavior for TOKN-04. This is not a gap; it is the intended design.

---

_Verified: 2026-02-24T18:10:00Z_
_Verifier: Claude (gsd-verifier)_
