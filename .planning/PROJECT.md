# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide live visibility into every LLM call, tool execution, state change, and loop iteration. Delivered as a standalone OWL app at `/ai-debug` — open it in a browser tab and it streams agentic loop events in real time via `bus.bus`. No database persistence; all data lives in the frontend for the duration of the browser session.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Current Milestone: v1.1 Live Tracer Standalone App

**Goal:** Replace the v1.0 backend-views-plus-panel architecture with a pure live tracer — a standalone OWL app with a sidebar/detail layout, no database models, full payloads streamed over bus.bus.

**Target features:**
- Standalone OWL app at `/ai-debug` (like `point_of_sale.index`)
- Sidebar tree: Loop (labeled by agent) > Iteration > Tool Call (3 levels)
- Detail panel: context for selected item (system prompt/tools for loops, messages/response for iterations, args/result for tool calls)
- Full bus.bus payloads (no lazy ORM reads)
- Session-scoped (refresh clears)
- Subagent-ready data design (nested loops anticipated, not yet implemented)

## Requirements

### Validated

- ✓ Instrument `ai.session._run_agentic_loop()` via model inheritance to capture every iteration — v1.0
- ✓ Instrument `ai.session._handle_tool_calls()` to capture tool execution details — v1.0
- ✓ Live debug panel connected via `bus.bus` — v1.0
- ✓ State diff tracking between loop iterations — v1.0

### Active

(Defined in REQUIREMENTS.md for v1.1)

### Out of Scope

- Modifying the `ai` module itself — instrumentation only via `_inherit`
- Proxying or intercepting LLM HTTP traffic — capture at the Odoo model layer
- Mobile or responsive UI — developer tool, desktop only
- Multi-instance / distributed tracing — single-process agentic loop, no value for local dev
- Database persistence of traces — v1.1 is ephemeral by design
- Backend list/form views for traces — replaced by the standalone app
- Subagent nesting implementation — anticipated in data design but deferred

## Context

**Shipped v1.0** with persistent models, backend views, and a live panel. v1.1 strips persistence and backend views in favor of a pure live tracer.

**Tech stack:** Odoo OWL standalone app, bus.bus WebSocket, generator yield passthrough for instrumentation.

**Module:** `ai_debug` — depends on `ai_app` and `bus`.

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**Subagent anticipation:** The enterprise `ai` module is expected to support subagents (an agentic loop spawned inside a parent agentic loop). The tracer's data model and sidebar tree should anticipate parent/child loop relationships even though the feature isn't implemented upstream yet.

**v2+ candidates:**
- RPLY-01: User can edit captured trace messages and re-run against the LLM
- EXPT-01: Traces exportable in OpenTelemetry (OTLP) format
- EVAL-01: Automated LLM-as-judge scoring of captured traces

## Constraints

- **Odoo version**: Master branch only
- **Dependency**: Requires enterprise `ai_app` module installed
- **Approach**: Model inheritance only (`_inherit = 'ai.session'`), no monkey-patching
- **Behavior**: Zero behavioral change to the underlying agentic loop (yield passthrough)
- **Stack**: Standalone OWL app + `bus.bus` for live updates, no Odoo backend views
- **Access**: Any internal user (`base.group_user`)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Generator yield passthrough for instrumentation | Standard Odoo pattern, zero behavioral change | ✓ Good — confirmation flow, streaming all preserved |
| Mutable dict via Odoo context for state sharing | Context values freeze on with_context(), mutable container required | ✓ Good — simple cross-method state sharing |
| Global bus.bus channel (not per-trace) | Eliminates race between channel subscription and first event | ✓ Good — reliable delivery |
| No database persistence (v1.1) | Developer tool, ephemeral by nature; DB models added unnecessary complexity | — Pending |
| Full payloads over bus.bus (v1.1) | No DB means no lazy ORM reads; bus must carry all data | — Pending |
| Standalone OWL app (like POS) | Clean separation from Odoo backend, no navbar/chrome interference | — Pending |
| Sidebar + detail panel layout (v1.1) | Master/detail pattern suits hierarchical data (loop > iteration > tool) | — Pending |

---
*Last updated: 2026-02-20 after v1.1 milestone start*
