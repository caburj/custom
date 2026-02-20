# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide deep visibility into every LLM call, tool execution, state change, and loop iteration. Delivered as a standard Odoo module — install it in any local master instance and it works immediately, storing persistent traces queryable via standard ORM tooling, viewable in backend history views, and monitorable in real time via a dedicated OWL debug panel.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Requirements

### Validated

- ✓ Instrument `ai.session._run_agentic_loop()` via model inheritance to capture every iteration — v1.0
- ✓ Instrument `ai.session._handle_tool_calls()` to capture tool execution details — v1.0
- ✓ Persistent debug models (trace, iteration, tool_call) that survive server restarts — v1.0
- ✓ Live debug panel in a separate browser tab/page, connected via `bus.bus` — v1.0
- ✓ Backend history views for post-mortem trace inspection — v1.0
- ✓ State diff tracking between loop iterations — v1.0
- ✓ Configuration parameters (enable/disable, retention, capture options) — v1.0

### Active

(None — define with `/gsd:new-milestone`)

### Out of Scope

- Modifying the `ai` module itself — instrumentation only via `_inherit`
- Proxying or intercepting LLM HTTP traffic — capture at the Odoo model layer
- Mobile or responsive UI — developer tool, desktop only
- Multi-instance / distributed tracing — single-process agentic loop, no value for local dev
- Real-time token streaming — Odoo uses line-delimited JSON, not per-token SSE; iteration-level timing suffices

## Context

**Shipped v1.0** with 2,906 LOC across Python, XML, JS, SCSS, and CSV.

**Tech stack:** Odoo OWL components, bus.bus WebSocket, standard Odoo backend views, fields.Json (JSONB), @api.autovacuum, generator yield passthrough for instrumentation.

**Module:** `ai_debug` — depends on `ai` (enterprise) and `bus`.

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**Known tech debt from v1.0:**
- Vestigial per-trace UUID channel subscriptions in debug_panel.js (dead code)
- Missing explicit standalone list views for iteration and tool_call models
- TODO: save stripped binaries to ir.attachment

**v2 candidates (from REQUIREMENTS):**
- RPLY-01: User can edit captured trace messages and re-run against the LLM
- EXPT-01: Traces exportable in OpenTelemetry (OTLP) format
- EVAL-01: Automated LLM-as-judge scoring of captured traces

## Constraints

- **Odoo version**: Master branch only
- **Dependency**: Requires enterprise `ai` module installed
- **Approach**: Model inheritance only (`_inherit = 'ai.session'`), no monkey-patching
- **Behavior**: Zero behavioral change to the underlying agentic loop (yield passthrough)
- **Stack**: OWL components + `bus.bus` for live updates, standard Odoo backend views for history

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Persistent Model (not TransientModel) for debug data | ai.session is transient — traces must survive session cleanup | ✓ Good — traces persist across sessions |
| Live panel as separate tab/page | Avoids patching the chat UI, keeps debug decoupled | ✓ Good — clean separation of concerns |
| Generator yield passthrough for instrumentation | Standard Odoo pattern, zero behavioral change | ✓ Good — confirmation flow, streaming all preserved |
| fields.Json (not fields.Text) for JSON payloads | Native JSONB, no double-serialization | ✓ Good — clean ORM reads, no parsing needed |
| Separate cursor writes for debug data | Debug records survive main-transaction rollbacks | ✓ Good — error traces captured even on rollback |
| Mutable dict via Odoo context for iteration_id sharing | Context values freeze on with_context(), mutable container required | ✓ Good — simple cross-method state sharing |
| Global bus.bus channel (not per-trace) | Eliminates race between channel subscription and first event | ✓ Good — reliable delivery, security maintained via IrWebsocket |
| Computed Text pretty-print fields as ace targets | json.dumps(indent=2) on each Json field; ace widget needs Text not Json | ✓ Good — syntax-highlighted JSON in backend |
| Summary-only bus payloads | Frontend RPC-fetches detail on demand; avoids large payloads over WebSocket | ✓ Good — fast bus delivery, lazy detail loading |
| Batch-level state snapshots (not per-tool) | Base _handle_tool_calls processes tools sequentially inside its own generator | ✓ Good — matches real execution boundaries |

---
*Last updated: 2026-02-20 after v1.0 milestone*
