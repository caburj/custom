# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide live visibility into every LLM call, tool execution, state change, and loop iteration. Delivered as a standalone OWL app at `/ai-debug` that respects the user's Odoo light/dark theme preference. Open it in a browser tab and it streams agentic loop events in real time via `bus.bus`. Features a 3-level sidebar tree (Loop > Iteration > Tool Call) with type-aware detail panels showing system prompts, messages, raw responses, tool args/results, and state diffs. No database persistence; all data lives in the frontend for the duration of the browser session.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Current State

**Shipped v1.2** (2026-02-22) — Native Theming

The module is a fully functional developer tool with:
- Standalone OWL app at `/ai-debug` with Odoo-native light/dark theme support
- Real-time bus.bus streaming with separate cursors for immediate event delivery
- 3-level sidebar tree with expand/collapse, stable selection, reverse chronological ordering, animations
- Type-aware detail panels with tabbed Notebook views, JSON tree rendering, state diff visualization
- Session-scoped ephemeral data (refresh clears all traces)
- Conditional CSS bundle loading via `webclient_rendering_context()` — automatically adapts to user's theme preference
- All SCSS uses Odoo `$o-*` variables — zero hardcoded colors

**Tech stack:** Odoo OWL standalone app, bus.bus WebSocket, generator yield passthrough instrumentation.
**LOC:** ~2,013 (JS/XML/SCSS/Python) — net reduction from v1.1 via dead code removal
**Module:** `ai_debug` — depends on `ai_app` and `bus`.

## Requirements

### Validated

- ✓ Instrument `ai.session._run_agentic_loop()` via model inheritance to capture every iteration — v1.0
- ✓ Instrument `ai.session._handle_tool_calls()` to capture tool execution details — v1.0
- ✓ Live debug panel connected via `bus.bus` — v1.0
- ✓ State diff tracking between loop iterations — v1.0
- ✓ Standalone OWL app at `/ai-debug` with bus_service connection — v1.1
- ✓ Full bus.bus payloads with UUID identifiers and separate cursors — v1.1
- ✓ 3-level sidebar tree (Loop > Iteration > Tool Call) with stable selection — v1.1
- ✓ Type-aware detail panels (system prompt, messages, raw response, args/result, state diff) — v1.1
- ✓ Session-scoped ephemeral data (no database persistence) — v1.1
- ✓ Controller reads `color_scheme` via `webclient_rendering_context()` for theme-aware rendering — v1.2
- ✓ QWeb template conditionally loads dark or light CSS bundle — v1.2
- ✓ Manifest defines `ai_debug.assets_dark` bundle with `web.dark_mode_variables` — v1.2
- ✓ All hardcoded colors replaced with Odoo `$o-*` SCSS variables (231 hex/rgba → 66 variable refs) — v1.2
- ✓ Dead component override blocks removed (Notebook, Dialog, CopyButton, error banner, popup) — v1.2
- ✓ Dark-specific `app.dark.scss` with syntax highlighting overrides — v1.2
- ✓ Status badge colors use semantic `$o-success`/`$o-danger`/`$o-warning` — v1.2

### Active

(No active milestone — use `/gsd:new-milestone` to start next)

### Out of Scope

- Modifying the `ai` module itself — instrumentation only via `_inherit`
- Proxying or intercepting LLM HTTP traffic — capture at the Odoo model layer
- Mobile or responsive UI — developer tool, desktop only
- Multi-instance / distributed tracing — single-process agentic loop, no value for local dev
- Keyboard navigation in sidebar — P2 polish
- Search/filter in sidebar — bounded tree depth makes this low-priority
- localStorage persistence — stale data risk, privacy concerns

## Context

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**Subagent anticipation:** The enterprise `ai` module is expected to support subagents (an agentic loop spawned inside a parent agentic loop). The tracer's data model and sidebar tree should anticipate parent/child loop relationships even though the feature isn't implemented upstream yet.

**v2+ candidates:**
- RPLY-01: User can edit captured trace messages and re-run against the LLM
- EXPT-01: Traces exportable in OpenTelemetry (OTLP) format
- EVAL-01: Automated LLM-as-judge scoring of captured traces
- NEST-01: Sidebar tree supports nested loops (subagent loop under parent loop iteration)

**Known tech debt:**
- Payload size for RAG-enabled sessions unknown (needs empirical baseline)
- Confirmation Info tab in ToolCallDetail is a placeholder
- Per-tool state granularity deferred (currently batch-level before/after)

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
| No database persistence (v1.1) | Developer tool, ephemeral by nature; DB models added unnecessary complexity | ✓ Good — simpler architecture, no migration needed |
| Full payloads over bus.bus (v1.1) | No DB means no lazy ORM reads; bus must carry all data | ✓ Good — self-contained events, no backend round-trips |
| Standalone OWL app (like POS) | Clean separation from Odoo backend, no navbar/chrome interference | ✓ Good — clean dark theme, no UI conflicts |
| Sidebar + detail panel layout (v1.1) | Master/detail pattern suits hierarchical data (loop > iteration > tool) | ✓ Good — natural tree navigation |
| useState(new Map()) for trace store | reactive() without callback uses NO_CALLBACK sentinel, blocking OWL render | ✓ Good — fixed via 06-03 gap closure |
| Batch-level state granularity | Per-tool would require re-implementing upstream method body | ⚠️ Revisit — still deferred |
| Full conversation history per iteration | Downstream simplicity over payload efficiency | ✓ Good — simple detail rendering |
| webclient_rendering_context() for theme | Handles user settings, public user guard, Odoo-standard approach | ✓ Good — correct dark/light detection |
| Dark bundle includes ai_debug.assets not web.assets_backend | Avoids re-including bundle that strips *.dark.scss files | ✓ Good — dark variables preserved |
| $o-warning for JSON numbers in dark mode | Warm amber contrast on dark background vs neutral gray in light | ✓ Good — legible in both modes |
| Bootstrap alert-danger for error banners | Automatic dark-mode adaptation without custom CSS | ✓ Good — zero custom dark styling needed |
| All panels use same $o-webclient-background-color | Borders define visual separation, not background depth | ✓ Good — consistent with Odoo patterns |

---
*Last updated: 2026-02-22 after v1.2 milestone*
