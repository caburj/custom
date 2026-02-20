# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide deep visibility into every LLM call, tool execution, state change, and loop iteration. Delivered as a standard Odoo module — install it in any local master instance and it works immediately, storing persistent traces queryable via standard ORM tooling and viewable in a real-time debug UI.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Instrument `ai.session._run_agentic_loop()` via model inheritance to capture every iteration
- [ ] Instrument `ai.session._handle_tool_calls()` to capture tool execution details
- [ ] Persistent debug models (trace, iteration, tool_call) that survive server restarts
- [ ] Live debug panel in a separate browser tab/page, connected via `bus.bus`
- [ ] Backend history views for post-mortem trace inspection
- [ ] State diff tracking between loop iterations
- [ ] Configuration parameters (enable/disable, retention, capture options)

### Out of Scope

- Modifying the `ai` module itself — instrumentation only via `_inherit`
- Proxying or intercepting LLM HTTP traffic — capture at the Odoo model layer
- Mobile or responsive UI — developer tool, desktop only
- Multi-instance / distributed tracing

## Context

**Target:** Odoo master branch, enterprise `ai` module.

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**AI module architecture (verified against source):**

Entry points:
- `POST /ai/generate_response` — HTTP streaming (line-delimited JSON, not true SSE), auth=public
- `POST /ai/get_direct_response` — JSON-RPC, auth=user
- `POST /ai/close_ai_chat` — JSON-RPC, auth=public
- `POST /ai/transcription/session` — JSON-RPC, auth=user

Core models:
- `ai.session` (TransientModel) — owns the agentic loop; ephemeral, cleaned up on logout
- `ai.session.event` (TransientModel) — stores raw provider responses as history
- `ai.agent` (Model) — agent config: model, system prompt, temperature, topics
- `ai.topic` (Model) — groups tools + instructions; assigned to agents
- `ai.composer` (Model) — maps interface keys to agents and default prompts
- `ir.actions.server` — `use_in_ai = True` makes it a tool

Agentic loop flow:
```
User message → _add_user_message()
  → _generate_next_response()
    ├── _get_context_input()      # RAG, date, user info, record data
    ├── _get_instructions()       # system prompt + topic instructions
    └── _run_agentic_loop()       # core loop
          for api_request_idx in range(max_successive_calls):  # default 20
              provider.get_completions(...)
              provider._format_from_llm(response)
              if tool_calls:
                  yield tool_calls
                  _handle_tool_calls()  # generator, yields thought/confirmation/results
                  continue
              else:
                  yield final_message
                  return
```

Key `tools_context` keys (initial + dynamically added):
- `llm_model`, `state`, `res_model`, `res_id`
- `tool_request_confirmed`, `tool_request_message`, `final_message`
- `tool_call_id` (added per tool execution)
- `result` (added by tools to return values)

Confirmation flow:
- `pending_tool_call_id` / `pending_tools_results` on `ai.session`
- `_handle_remaining_tool_calls()` resumes after user confirms

Provider abstraction:
- `AIProvider` (formatting) / `AIApiService` (HTTP transport)
- Concrete: OpenAI + Google

Config params:
- `ai.max_successive_calls` — default 20 (loop iterations)
- `ai.max_tool_calls_per_call` — default 20 (tools per single call)

**Design implication:** Since `ai.session` is TransientModel, debug models must be persistent (`Model`) to retain traces after sessions are cleaned up.

## Constraints

- **Odoo version**: Master branch only
- **Dependency**: Requires enterprise `ai` module installed
- **Approach**: Model inheritance only (`_inherit = 'ai.session'`), no monkey-patching
- **Behavior**: Zero behavioral change to the underlying agentic loop (yield passthrough)
- **Stack**: OWL components + `bus.bus` for live updates, standard Odoo backend views for history

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Persistent Model (not TransientModel) for debug data | ai.session is transient — traces must survive session cleanup | — Pending |
| Live panel as separate tab/page | Avoids patching the chat UI, keeps debug decoupled | — Pending |
| Models + Live panel before Backend views | Live visibility during testing is the priority | — Pending |
| Generator yield passthrough for instrumentation | Standard Odoo pattern, zero behavioral change | — Pending |

---
*Last updated: 2026-02-20 after initialization*
