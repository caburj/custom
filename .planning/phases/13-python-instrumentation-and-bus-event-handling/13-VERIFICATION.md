---
phase: 13-python-instrumentation-and-bus-event-handling
verified: 2026-02-23T14:30:00Z
status: passed
score: 11/11 must-haves verified
---

# Phase 13: Python Instrumentation and Bus Event Handling Verification Report

**Phase Goal:** Backend emits parent_trace_id and parent_tool_call_id so the frontend knows subagent causality; JS event handlers buffer out-of-order bus events without data loss
**Verified:** 2026-02-23T14:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth                                                                                                    | Status     | Evidence                                                                                           |
|----|----------------------------------------------------------------------------------------------------------|------------|----------------------------------------------------------------------------------------------------|
| 1  | Root session new_trace payload includes session_id (ORM int) and parent_trace_id: null, parent_tool_call_id: null | VERIFIED | ai_session.py line 165-167: `'session_id': self.id`, `'parent_trace_id': parent_trace_id`, `'parent_tool_call_id': parent_tool_call_id`; roots read None from context |
| 2  | Subagent session new_trace payload includes session_id (ORM int) and non-null parent_trace_id (UUID hex) and non-null parent_tool_call_id (LLM call_id string) | VERIFIED | Context read at lines 159-160 from `ai_parent_trace_id` and `ai_parent_tool_call_id` injected by the context threading chain |
| 3  | tool_call_started event fires BEFORE super() delegation with tool name, args, call_id, and a stable tool_call_id UUID | VERIFIED | ai_session.py lines 314-323: `tool_call_started` loop fires before the `for item in super()._handle_tool_calls(...)` loop |
| 4  | tool_call_completed event fires AFTER super() yields tool_results with matching tool_call_id, result, success, error | VERIFIED | ai_session.py lines 343-353: `tool_call_completed` emitted inside the super() generator loop on `tool_results` branch |
| 5  | Existing non-subagent agentic loops emit events with no behavioral change (new fields are null) | VERIFIED | Root sessions read None from context (no keys set), payload shape is identical, new fields default to null |
| 6  | A child trace arriving before its parent tool_call_started event is buffered in _pendingChildren — NOT placed at root | VERIFIED | app.js lines 127-133: `setTimeout` + `_pendingChildren[parent_tool_call_id] = { payload, timer }` |
| 7  | When the parent tool_call_started event arrives, the buffered child is immediately attached under it | VERIFIED | app.js lines 188-194: `_onToolCallStarted` checks `_pendingChildren[payload.call_id]`, calls `_placeTrace(buffered.payload)` |
| 8  | If 30 seconds pass with no parent tool_call_started, the orphan child is promoted to root level | VERIFIED | app.js line 131: `}, 30000)` timeout calls `_placeTrace(payload)` and cleans up entry |
| 9  | Re-attachment clears the 30s timeout timer (no double-fire) | VERIFIED | app.js line 190: `clearTimeout(buffered.timer)` called before `delete _pendingChildren[payload.call_id]` |
| 10 | Existing root traces (parent_trace_id === null) continue to be placed directly with no buffer interaction | VERIFIED | app.js line 137: root path falls through to `this._placeTrace(payload)` with no buffer interaction |
| 11 | tool_call_started creates the tool call node with pending status; tool_call_completed fills in result | VERIFIED | app.js lines 171-186 (_onToolCallStarted: status "running", null result) and lines 224-231 (_onToolCallCompleted: updates in-place) |

**Score:** 11/11 truths verified

### Required Artifacts

| Artifact                              | Expected                                                  | Status    | Details                                                                 |
|---------------------------------------|-----------------------------------------------------------|-----------|-------------------------------------------------------------------------|
| `ai_debug/models/ai_session.py`       | Parent linkage in new_trace payload + tool call event splitting | VERIFIED | Contains `parent_trace_id`, `parent_tool_call_id`, `session_id`, `_tc_id_map`, `tool_call_started`, `tool_call_completed`. Syntax clean. |
| `ai_debug/models/ai_agent.py`         | Context threading of ai_parent_tool_call_id to subagent sessions | VERIFIED | Created. Contains `_ai_tool_request_sub_agent` override with `ai_parent_tool_call_id` injection. Syntax clean. |
| `ai_debug/models/__init__.py`         | Import of ai_agent module                                 | VERIFIED  | Line 3: `from . import ai_agent`                                        |
| `ai_debug/static/src/app/app.js`      | Pending-child buffer, split tool call handlers, updated bus subscriptions | VERIFIED | Contains `_pendingChildren`, `_placeTrace`, `_onToolCallStarted`, `_onToolCallCompleted`, updated subscribe/unsubscribe |

### Key Link Verification

| From                                              | To                                                        | Via                                                           | Status  | Details                                                                    |
|---------------------------------------------------|-----------------------------------------------------------|---------------------------------------------------------------|---------|----------------------------------------------------------------------------|
| `ai_session.py (_handle_tool_calls)`              | `ai_session.py (_run_agentic_loop child)`                 | `self.with_context(ai_parent_trace_id=_debug_ctx['trace_id'])` | WIRED  | Line 296: single-line form confirmed. 1 match.                             |
| `ai_agent.py (_ai_tool_request_sub_agent)`        | `ai_session.py (_run_agentic_loop child)`                 | `self.with_context(ai_parent_tool_call_id=...)` multi-line   | WIRED   | Lines 19-21: multi-line `with_context()` form confirmed via multiline regex. 1 match. |
| `ai_session.py tool_call_started`                 | `ai_session.py tool_call_completed`                       | `_tc_id_map` dict maps LLM call_id to stable UUID             | WIRED   | `_tc_id_map[tc['call_id']]` in started; `_tc_id_map.get(call_id, ...)` in completed. 3 uses. |
| `app.js (_onNewTrace)`                            | `app.js (_pendingChildren)`                               | Buffer check with 30s timer                                   | WIRED   | 5 references to `_pendingChildren[`. Buffer path and direct path both route through `_placeTrace`. |
| `app.js (_onToolCallStarted)`                     | `app.js (_pendingChildren)`                               | `clearTimeout` + re-attachment                                | WIRED   | Lines 188-194: `clearTimeout(buffered.timer)`, `delete`, `_placeTrace(buffered.payload)` |
| `app.js (onMounted subscriptions)`                | `app.js (_onToolCallStarted, _onToolCallCompleted)`       | `busService.subscribe` for both new event types               | WIRED   | Lines 291-292: both subscribe calls present; lines 300-301: both unsubscribe calls present |

### Requirements Coverage

| Requirement | Source Plan | Description                                                                                  | Status   | Evidence                                                                              |
|-------------|-------------|----------------------------------------------------------------------------------------------|----------|---------------------------------------------------------------------------------------|
| INST-01     | Plan 01     | Backend emits `session_id` (own ORM ID) in `new_trace` bus event payload                    | SATISFIED | `'session_id': self.id` in new_trace payload (ai_session.py line 165)                |
| INST-02     | Plan 01     | Backend emits parent linkage in `new_trace` bus event payload for subagent sessions         | SATISFIED | `parent_trace_id` (UUID hex) and `parent_tool_call_id` emitted. Note: REQUIREMENTS.md says `parent_session_id` but CONTEXT.md explicitly supersedes this with `parent_trace_id` (UUID). Intentional — documented in PLAN 01 key-decisions. |
| INST-03     | Plan 01     | Backend injects parent trace context via `env.context` before `super()` in `_handle_tool_calls` | SATISFIED | `self = self.with_context(ai_parent_trace_id=_debug_ctx['trace_id'])` at line 296, before `for item in super()._handle_tool_calls(...)` at line 325 |
| TREE-05     | Plan 02     | Frontend handles out-of-order bus events via pending-child buffer                           | SATISFIED | `_pendingChildren` buffer in app.js with 30s promotion, clearTimeout on re-attachment, cleanup in onWillUnmount |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps only INST-01, INST-02, INST-03, TREE-05 to Phase 13. No orphaned requirements.

### Anti-Patterns Found

| File                              | Line | Pattern               | Severity | Impact                                                                |
|-----------------------------------|------|-----------------------|----------|-----------------------------------------------------------------------|
| `ai_debug/models/ai_session.py`   | 50   | word "placeholder"    | Info     | In docstring describing binary content replacement. Not a stub.       |
| `ai_debug/models/ai_session.py`   | 73   | `return []`           | Info     | Early-exit guard `if not tools: return []`. Legitimate guard.        |
| `ai_debug/models/ai_session.py`   | 81   | `return []`           | Info     | Exception fallback in `_ai_debug_serialize_tools`. Legitimate.       |
| `ai_debug/static/src/app/app.js`  | 429+ | `return null`         | Info     | Pre-existing getter fallbacks (`getSelectedTrace`, etc.). Pre-phase.  |

No blockers or warnings. All flagged lines are legitimate guards or pre-existing code.

**False positive in Plan 01 Task 2 automated check:** The check for old `'tool_call'` event type flags `result_item.get('tool_call', {})` at line 333. This is a data dict key accessor into Odoo's `tool_results` structure — not a bus event emission. All three bus event emissions of the old `tool_call` type were correctly replaced. This was noted in the SUMMARY as a known false positive.

### Human Verification Required

#### 1. End-to-end subagent causality flow

**Test:** Trigger an agentic session that spawns a subagent via a subagent tool call. Observe the bus event log.
**Expected:** The child session's `new_trace` event includes non-null `parent_trace_id` (matching the parent trace UUID) and non-null `parent_tool_call_id` (matching the LLM call_id of the tool call that spawned it).
**Why human:** Requires a live Odoo instance, a configured agent with a subagent tool, and bus event inspection. Cannot be verified statically.

#### 2. Out-of-order buffering behavior

**Test:** Simulate (or observe naturally) a child trace arriving before its parent `tool_call_started` event. Verify the child does not appear at root level until the parent event arrives.
**Expected:** Child trace is held in `_pendingChildren`, not rendered. When `tool_call_started` fires, child appears attached to the correct parent tool call node.
**Why human:** Requires live bus event ordering control or timing manipulation. Cannot be verified statically.

#### 3. 30-second timeout promotion

**Test:** Buffer a child trace (by suppressing the parent `tool_call_started` event) and wait 30 seconds.
**Expected:** Child trace is promoted to root level after exactly 30 seconds, retaining its `parent_trace_id` and `parent_tool_call_id` fields.
**Why human:** Requires controlled timing in a live browser session.

### Gaps Summary

No gaps found. All 11 observable truths verified. All 4 artifacts substantive and wired. All 6 key links confirmed. All 4 requirement IDs (INST-01, INST-02, INST-03, TREE-05) satisfied. 5 task commits (a6e5758, 6ee9f01, 9159bfc, 3266b1f, 1f201e3) verified in git history.

One documentation note: REQUIREMENTS.md describes INST-02 as `parent_session_id (parent ORM ID)` but the implementation emits `parent_trace_id (UUID hex)` per CONTEXT.md decision. This is an intentional supersession documented in CONTEXT.md line 20 and PLAN 01 key-decisions. The implementation satisfies the intent of INST-02 (parent linkage for subagent sessions) with the correct field type for the frontend use case.

---

_Verified: 2026-02-23T14:30:00Z_
_Verifier: Claude (gsd-verifier)_
