---
phase: 01-data-models-and-instrumentation
plan: 02
subsystem: instrumentation
tags: [odoo, orm, generator, yield, passthrough, TransientModel, registry.cursor, ir.config_parameter]

# Dependency graph
requires:
  - phase: 01-01
    provides: "ai.debug.trace, ai.debug.iteration, ai.debug.tool.call persistent models"
provides:
  - "AiSessionDebug(TransientModel) inheriting ai.session with three generator yield passthrough overrides"
  - "Full agentic loop observability: every LLM call, tool execution, state snapshot, confirmation event captured"
  - "Config-gated instrumentation: ai_debugger.enabled=False produces zero overhead and no debug records"
  - "Separate cursor writes ensuring debug data survives main-transaction rollbacks"
  - "Binary content stripping (base64 replaced with placeholder) before Json storage"
affects:
  - 02 (backend views will display trace/iteration/tool_call records now populated)
  - 03 (live panel reads iteration/tool_call records via bus.bus)

# Tech tracking
tech-stack:
  added:
    - "time.perf_counter() for sub-millisecond timing on trace, iteration, and tool call records"
    - "copy.deepcopy() for state snapshot isolation before/after each tool call"
  patterns:
    - "Generator yield passthrough: for item in super()._method(...): yield item — preserves streaming semantics"
    - "Separate cursor via self.env.registry.cursor() for writes that must survive rollback"
    - "Mutable dict _debug_ctx passed via Odoo context to share iteration_id between _run_agentic_loop and _handle_tool_calls"
    - "Config gate: _is_debug_enabled() checked at entry point of every override; disabled = zero overhead"
    - "_debug_safe_context() strips BaseModel instances before use in separate cursor environment"

key-files:
  created:
    - ai_debug/models/ai_session.py
  modified:
    - ai_debug/models/__init__.py

key-decisions:
  - "Mutable dict _debug_ctx via Odoo context (not immutable context value) to share iteration_id — context values freeze on with_context() so a dict object reference is passed instead"
  - "_generate_next_response captures RAG context before super() call — after super() the context_input is already merged into the message parts and cannot be separated"
  - "_handle_tool_calls tool capture wraps the entire batch: state_before is captured before the super() loop, state_after after 'tool_results' yield — matches the base method's sequential execution model"
  - "exception in _run_agentic_loop sets state='error' via _debug_update_trace then re-raises — loop failure behavior unchanged"

patterns-established:
  - "Pattern: Generator yield passthrough preserves streaming: yield item after every item from super() generator"
  - "Pattern: Separate registry cursor with _debug_safe_context() for writes that must survive transaction rollback"
  - "Pattern: Mutable dict via Odoo context for sharing state between parent/child generator calls"
  - "Pattern: _is_debug_enabled() gate at every override entry — disabled path has zero DB reads (after config cache hit)"

requirements-completed: [CAPT-01, CAPT-02, CAPT-03, CAPT-04, CAPT-05, CAPT-06, CAPT-07, CAPT-08, CAPT-09, CAPT-10, CAPT-11, CONF-01]

# Metrics
duration: 2min
completed: 2026-02-20
---

# Phase 1 Plan 02: AI Session Instrumentation Summary

**AiSessionDebug TransientModel with three generator yield passthrough overrides that populate ai.debug.* models on every agentic loop event without altering streaming behavior or confirmation flow**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-20T09:20:23Z
- **Completed:** 2026-02-20T09:22:54Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `ai_debug/models/ai_session.py` (457 lines) with `AiSessionDebug` class inheriting `ai.session` as a `TransientModel` — all three agentic loop methods overridden with generator yield passthrough instrumentation
- `_run_agentic_loop` override captures: one `ai.debug.trace` per invocation (with LLM model, instructions, RAG context, state, timing), one `ai.debug.iteration` per LLM response (with messages snapshot, raw provider response, termination data, duration), exception handling that sets `state='error'` then re-raises
- `_handle_tool_calls` override captures: one `ai.debug.tool.call` per executed tool (with args, result, success flag, state_before/after snapshots, duration, confirmation trigger and message)
- `_generate_next_response` override captures system instructions and RAG context before calling super(), injects via Odoo context so the trace record is populated with `CAPT-09` data
- All writes use separate `registry.cursor()` — debug data survives main-transaction rollbacks
- `_is_debug_enabled()` gates all capture; disabled path hits config param cache then yields directly from super() — zero overhead

## Task Commits

Each task was committed atomically:

1. **Task 1: _run_agentic_loop override + all helper methods** - `9be56a9` (feat)
2. **Task 2: _handle_tool_calls, _generate_next_response overrides + __init__.py** - `bcde64b` (feat)

**Plan metadata:** (docs commit — see below)

## Files Created/Modified

- `ai_debug/models/ai_session.py` — `AiSessionDebug` class: `_is_debug_enabled`, `_debug_strip_binaries`, `_debug_safe_context`, `_debug_write_trace`, `_debug_write_iteration`, `_debug_update_trace`, `_debug_write_tool_call`, `_run_agentic_loop`, `_handle_tool_calls`, `_generate_next_response`
- `ai_debug/models/__init__.py` — Added `from . import ai_session`

## Decisions Made

- `_debug_ctx` mutable dict via Odoo context: `with_context(_debug_ctx=debug_ctx)` passes a dict object whose `.iteration_id` key is mutated after each iteration write. Since Odoo context values are frozen on `with_context()`, a plain `int` value cannot be updated — only a mutable container works. This is idiomatic for sharing transient state across an override call chain.
- `_generate_next_response` captures RAG context before calling super(): after `super()` returns, the context_input string has been merged into `message['parts']` and cannot be separated from the user message. Capturing before super() is the only clean point.
- `_handle_tool_calls` captures state_before the entire super() call and state_after at the `tool_results` yield: the base method processes tool calls sequentially inside its own generator, so we cannot capture per-tool state without reimplementing the loop. Batch-level snapshots are sufficient for the current requirements (CAPT-11).

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. The module instrumentation activates automatically when the `ai_debug` module is installed. Debug capture is enabled by default; disable via `ir.config_parameter` key `ai_debugger.enabled = False`.

## Next Phase Readiness

- Instrumentation layer is complete — the three debug models from Plan 01 are now populated on every agentic loop run
- Phase 2 (backend views) can now implement tree/form views for `ai.debug.trace`, `ai.debug.iteration`, and `ai.debug.tool.call` — there will be live data to view after any AI interaction with `ai_debugger.enabled = True`
- No blockers. The module is installable and the instrumentation is non-invasive to the base `ai` module.

---
*Phase: 01-data-models-and-instrumentation*
*Completed: 2026-02-20*
