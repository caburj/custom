---
phase: 01-data-models-and-instrumentation
verified: 2026-02-20T10:15:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 1: Data Models and Instrumentation Verification Report

**Phase Goal:** Every agentic loop run produces a queryable trace with full iteration and tool call detail
**Verified:** 2026-02-20T10:15:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

All five success criteria from ROADMAP.md are verified:

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running an agentic loop creates one ai.debug.trace, one ai.debug.iteration per LLM call, one ai.debug.tool.call per tool execution | VERIFIED | `_run_agentic_loop` override writes trace on entry; writes iteration at each `tool_calls`/`final_message` yield; `_handle_tool_calls` writes tool.call at each `tool_results` yield. All via separate cursor ORM creates. |
| 2 | Each iteration record contains the full messages array sent and the raw provider response JSON verbatim | VERIFIED | `messages_sent = fields.Json` on ai.debug.iteration; captured with `_debug_strip_binaries(list(messages))` at yield point; `raw_response` captured from `item.get('metadata')` (CAPT-04, CAPT-05) |
| 3 | A trace record shows why the loop terminated and carries ms-level timing at trace, iteration, and tool call levels | VERIFIED | `termination_reason` Char field; three termination paths coded (`final_message`, `confirmation_pause`, `max_iterations`); `time.perf_counter()` used at all three levels (CAPT-06, CAPT-07) |
| 4 | An exception sets state='error' and stores the message; loop streaming behavior is completely unchanged | VERIFIED | `except Exception as e: _debug_update_trace(trace_id, {'state': 'error', ...}); raise` — re-raise preserves behavior. Every `for item in super()...` loop ends with unconditional `yield item` (CAPT-08) |
| 5 | ai_debugger.enabled gates all capture; disabling produces no records and no overhead | VERIFIED | `_is_debug_enabled()` called at entry of all three overrides; disabled path is `yield from super()...; return` — zero debug writes (CONF-01) |

**Score:** 9/9 must-haves verified (5 success criteria truths + 4 structural truths from Plan 01)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `ai_debug/__manifest__.py` | Module declaration with depends=['ai'] | VERIFIED | `'depends': ['ai']`, `application=False`, `license='LGPL-3'`, data includes security CSV. Python syntax valid. |
| `ai_debug/__init__.py` | Imports models subpackage | VERIFIED | `from . import models` — single line, correct. |
| `ai_debug/models/__init__.py` | Imports all four model modules | VERIFIED | Imports `ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call`, `ai_session` — all four present. |
| `ai_debug/models/ai_debug_trace.py` | Trace model with all capture fields and autovacuum | VERIFIED | `class AiDebugTrace(models.Model)`, 12 field definitions. `@api.autovacuum` method reads `ai_debugger.retention_days`. Python syntax valid. |
| `ai_debug/models/ai_debug_iteration.py` | Iteration model with messages_sent, raw_response Json fields | VERIFIED | `class AiDebugIteration(models.Model)`, 9 field definitions. `messages_sent = fields.Json`, `raw_response = fields.Json`. Python syntax valid. |
| `ai_debug/models/ai_debug_tool_call.py` | Tool call model with args, result, state snapshot fields | VERIFIED | `class AiDebugToolCall(models.Model)`, 11 field definitions. `args = fields.Json`, `result = fields.Text`. Python syntax valid. |
| `ai_debug/security/ir.model.access.csv` | Admin-only access rules for all three models | VERIFIED | 3 data rows: `access_ai_debug_trace_system`, `access_ai_debug_iteration_system`, `access_ai_debug_tool_call_system`. All use `base.group_system`, all perm_read/write/create/unlink = 1. |
| `ai_debug/models/ai_session.py` | AiSessionDebug with generator yield passthrough instrumentation | VERIFIED | 457 lines (exceeds 150 min). `_inherit = 'ai.session'`, `models.TransientModel`. Three overrides present: `_run_agentic_loop` (@api.model), `_handle_tool_calls` (instance), `_generate_next_response` (instance). Python syntax valid. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `ai_debug_iteration.py` | `ai_debug_trace.py` | `trace_id Many2one ondelete='cascade'` | VERIFIED | Line 9-10: `fields.Many2one('ai.debug.trace', ..., ondelete='cascade', index=True)` |
| `ai_debug_tool_call.py` | `ai_debug_iteration.py` | `iteration_id Many2one ondelete='cascade'` | VERIFIED | Line 9-10: `fields.Many2one('ai.debug.iteration', ..., ondelete='cascade', index=True)` |
| `ai_debug_trace.py` | `ir.config_parameter` | `@api.autovacuum reading ai_debugger.retention_days` | VERIFIED | Lines 38-44: `@api.autovacuum` decorator; `get_param("ai_debugger.retention_days", "7")` |
| `ai_session.py` | `ai.session._run_agentic_loop` | `for item in super(AiSessionDebug, debug_self)._run_agentic_loop(...)` | VERIFIED | Line 223: explicit super with debug_self context; unconditional `yield item` at line 283 |
| `ai_session.py` | `ai.session._handle_tool_calls` | `for item in super()._handle_tool_calls(...)` | VERIFIED | Line 346: `for item in super()._handle_tool_calls(...)`; yield item at lines 380, 402, 405 |
| `ai_session.py` | `ai.debug.trace` | `separate cursor ORM create via registry.cursor()` | VERIFIED | Line 111: `with self.env.registry.cursor() as cr:` then line 113: `env['ai.debug.trace'].create(vals)` |
| `ai_session.py` | `ir.config_parameter` | `get_param('ai_debugger.enabled')` | VERIFIED | Line 37: `.get_param('ai_debugger.enabled', 'True')` in `_is_debug_enabled()` |

### Requirements Coverage

All 13 requirement IDs from the PLAN frontmatter are accounted for:

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| CAPT-01 | 01-01, 01-02 | One ai.debug.trace per loop run with agent, model, duration, iteration count, state | SATISFIED | `iteration_count` Integer field; written at `final_message`, `max_iterations`, error paths |
| CAPT-02 | 01-01, 01-02 | One ai.debug.iteration per LLM call with messages, response, timing | SATISFIED | Iteration written at every `tool_calls` and `final_message` yield with `messages_sent`, `raw_response`, `duration_ms` |
| CAPT-03 | 01-01, 01-02 | One ai.debug.tool.call per tool execution with name, args, result, success, timing | SATISFIED | `_debug_write_tool_call` called at `tool_results` yield; all fields present |
| CAPT-04 | 01-01, 01-02 | Iteration stores exact messages array sent to LLM | SATISFIED | `messages_sent = fields.Json`; captured as `_debug_strip_binaries(list(messages))` at yield point |
| CAPT-05 | 01-01, 01-02 | Iteration stores raw provider response JSON verbatim | SATISFIED | `raw_response = fields.Json`; captured as `item.get('metadata')` |
| CAPT-06 | 01-01, 01-02 | Trace records why loop terminated | SATISFIED | `termination_reason` Char field; three coded values: `final_message`, `confirmation_pause`, `max_iterations` |
| CAPT-07 | 01-01, 01-02 | Duration in ms at trace, iteration, tool call levels | SATISFIED | `time.perf_counter()` used at trace start, iteration start, and tool start; all compute `round(elapsed * 1000)` |
| CAPT-08 | 01-02 | Exceptions captured with state='error' and message stored | SATISFIED | `except Exception as e: _debug_update_trace({'state': 'error', 'error_message': str(e), ...}); raise` |
| CAPT-09 | 01-02 | Full system prompt and RAG context captured at _generate_next_response level | SATISFIED | `_generate_next_response` calls `self._get_instructions()` and `self._get_context_input(text)`; injects via `_debug_instructions`/`_debug_rag_context` context keys; read in `_run_agentic_loop` at trace create |
| CAPT-10 | 01-01, 01-02 | Tool calls that trigger confirmation are flagged with message | SATISFIED | `triggered_confirmation = fields.Boolean`, `confirmation_message = fields.Text` on tool.call model; set at `tool_confirmation_request` yield |
| CAPT-11 | 01-01, 01-02 | Iteration records tools_context['state'] snapshots before and after tool execution | SATISFIED | `copy.deepcopy(tools_context.get('state', {}))` before and after super() in `_handle_tool_calls`; written to `state_before`/`state_after` on tool.call records |
| CONF-01 | 01-02 | ir.config_parameter master switch gates all capture | SATISFIED | `_is_debug_enabled()` checks `ai_debugger.enabled`; called first in all three overrides; disabled = `yield from super(); return` |
| CONF-02 | 01-01 | Auto-delete traces older than configurable retention period | SATISFIED | `@api.autovacuum _gc_ai_debug_traces` reads `ai_debugger.retention_days` (default 7), computes cutoff, calls `unlink()` |

**Orphaned requirements check:** REQUIREMENTS.md traceability table maps CAPT-01 through CAPT-11, CONF-01, CONF-02 to Phase 1 — all 13 are covered by Plan 01 and/or Plan 02. No orphans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `ai_debug/models/ai_session.py` | 51 | `# TODO: future enhancement — save stripped binaries to ir.attachment` | Info | Enhancement note only; binary stripping itself IS implemented. No functional gap. |

No blockers. No stubs. No empty implementations. No placeholder returns.

### Human Verification Required

All automated checks pass. The following behaviors require a running Odoo instance to confirm:

#### 1. Module installs cleanly on Odoo 17+ with enterprise ai module

**Test:** In a dev Odoo instance with the `ai` enterprise module, place `ai_debug/` in the addons path, run `odoo -u ai_debug` or install via Apps UI.
**Expected:** Module installs without errors; three tables (`ai_debug_trace`, `ai_debug_iteration`, `ai_debug_tool_call`) appear in the database; ir.model.access rules for `base.group_system` are active.
**Why human:** Cannot run Odoo's module install mechanism in static analysis.

#### 2. Live loop produces populated records

**Test:** With `ai_debugger.enabled = True` (default), trigger any agentic loop through the AI module (e.g., via ai.session). After completion, query: `env['ai.debug.trace'].search([])`, `env['ai.debug.iteration'].search([])`, `env['ai.debug.tool.call'].search([])` in Odoo shell.
**Expected:** One trace record, N iteration records (one per LLM call), M tool.call records (one per tool execution). All with non-null timing fields.
**Why human:** Requires live LLM provider call and full Odoo runtime.

#### 3. Disabling the config param produces zero records

**Test:** Set `ir.config_parameter` key `ai_debugger.enabled = False`. Trigger an agentic loop. Query the debug tables.
**Expected:** Zero new records created. No errors in Odoo logs.
**Why human:** Requires live runtime.

#### 4. Exception during loop sets state='error'

**Test:** Introduce a deliberate error in a tool or patch the LLM provider to raise. Observe the trace record after failure.
**Expected:** `ai.debug.trace.state = 'error'`, `error_message` contains the exception string. The loop exception still propagates to the caller normally.
**Why human:** Requires live runtime and deliberate failure injection.

#### 5. _generate_next_response context flow (CAPT-09)

**Test:** After a loop run, inspect `ai.debug.trace.instructions` and `ai.debug.trace.rag_context`. Compare against the actual system prompt and RAG context used.
**Expected:** `instructions` matches `self._get_instructions()` output; `rag_context` matches `self._get_context_input(text)` output.
**Why human:** Requires knowing the actual method return values in a live ai.session instance. Note: `_get_context_input` is called with extracted text from the first text part of the message; if the method signature differs in the enterprise ai module, this capture may return empty string rather than fail.

### Gaps Summary

No gaps. All automated checks pass.

---

## Verification Detail: Key Design Decisions Confirmed

**Separate cursor writes** (4 uses in `ai_session.py`): Each of `_debug_write_trace`, `_debug_write_iteration`, `_debug_update_trace`, `_debug_write_tool_call` uses `with self.env.registry.cursor() as cr` — debug data commits independently and survives main-transaction rollbacks.

**Mutable context dict pattern**: `debug_ctx = {'trace_id': trace_id, 'iteration_id': None}` passed via `self.with_context(_debug_ctx=debug_ctx)`. Since Odoo context values are frozen on `with_context()`, the dict object reference persists across the call chain, allowing `_run_agentic_loop` to update `debug_ctx['iteration_id']` after each iteration write for `_handle_tool_calls` to read.

**TransientModel inheritance**: `AiSessionDebug(models.TransientModel)` with `_inherit = 'ai.session'` — matches the base class type. Using `models.Model` would cause Odoo ORM errors.

**`@api.model` on `_run_agentic_loop`**: Matches the base method's decorator, ensuring the override is registered correctly in the MRO.

**No XML files**: Confirmed — no menu items, no views in Phase 1. The module directory contains only Python files and the security CSV. Phase 2 scope.

---

_Verified: 2026-02-20T10:15:00Z_
_Verifier: Claude (gsd-verifier)_
