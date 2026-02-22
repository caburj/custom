# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide live visibility into every LLM call, tool execution, state change, and loop iteration. Delivered as a standalone OWL app at `/ai-debug` that respects the user's Odoo light/dark theme preference. Traces persist locally via IndexedDB across page refresh, with checkbox-based bulk delete, JSON export/import, and automatic ephemeral mode fallback when IDB is unavailable.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Current State

**Shipped v1.3** (2026-02-22) — Local Persistence

The module is a fully functional developer tool with:
- Standalone OWL app at `/ai-debug` with Odoo-native light/dark theme support
- Real-time bus.bus streaming with separate cursors for immediate event delivery
- 3-level sidebar tree with expand/collapse, stable selection, reverse chronological ordering, animations
- Type-aware detail panels with tabbed Notebook views, JSON tree rendering, state diff visualization
- IndexedDB persistence with fire-and-forget writes — traces survive page refresh
- Bulk hydration from IDB before first render (no flash of empty state)
- Checkbox multi-select with select-all/indeterminate for bulk delete (UI + IDB)
- JSON export of selected traces and import with all-or-nothing validation + preview dialog
- Ephemeral mode degradation when IDB unavailable (amber badge indicator)
- Conditional CSS bundle loading via `webclient_rendering_context()` — automatically adapts to user's theme preference
- All SCSS uses Odoo `$o-*` variables — zero hardcoded colors

**Tech stack:** Odoo OWL standalone app, bus.bus WebSocket, generator yield passthrough instrumentation, IndexedDB via `@web/core/utils/indexed_db`.
**LOC:** ~2,500 (JS/XML/SCSS/Python)
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
- ✓ Auto-persist all traces to IndexedDB as bus events arrive (fire-and-forget, non-blocking) — v1.3
- ✓ Hydrate reactive store from IndexedDB on page load (traces survive refresh, no flash of empty state) — v1.3
- ✓ Live bus events continue to update UI in real time after hydration without regression — v1.3
- ✓ App degrades gracefully to ephemeral mode if IndexedDB unavailable — v1.3
- ✓ Delete individual traces from IndexedDB and reactive store — v1.3
- ✓ Clear all traces (select-all + bulk delete) — v1.3
- ✓ Export selected traces as JSON file download — v1.3
- ✓ Import previously exported JSON file to restore traces with validation — v1.3
- ✓ Invalid imports rejected with user-facing error notification — v1.3

### Active

(None — next milestone not yet planned)

### Out of Scope

- Modifying the `ai` module itself — instrumentation only via `_inherit`
- Proxying or intercepting LLM HTTP traffic — capture at the Odoo model layer
- Mobile or responsive UI — developer tool, desktop only
- Multi-instance / distributed tracing — single-process agentic loop, no value for local dev
- Keyboard navigation in sidebar — P2 polish
- Search/filter in sidebar — bounded tree depth makes this low-priority
- localStorage persistence — replaced by IndexedDB in v1.3
- Auto-expiry / TTL — would delete traces the developer still needs
- Server-side sync — export/import covers cross-machine sharing
- Per-event normalized IDB schema — one denormalized record per trace is correct
- Selective import picker — import all + delete unwanted is sufficient

## Context

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**v2+ candidates:**
- RPLY-01: User can edit captured trace messages and re-run against the LLM
- EXPT-01: Traces exportable in OpenTelemetry (OTLP) format
- EVAL-01: Automated LLM-as-judge scoring of captured traces
- NEST-01: Sidebar tree supports nested loops (subagent loop under parent loop iteration)
- TSEL-01: User can select specific traces for export (currently exports all checked)

**Known tech debt:**
- Payload size for RAG-enabled sessions unknown (needs empirical baseline)
- Confirmation Info tab in ToolCallDetail is a placeholder
- Per-tool state granularity deferred (currently batch-level before/after)
- Minor UX: if selected item is a child of a deleted trace, detail panel shows fallback state rather than clearing selection
- Degraded standalone mode: dialog service unavailable suppresses import error dialogs silently

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
| Write-through cache pattern for IDB (v1.3) | Reactive Map is UI source of truth; IDB writes fire-and-forget | ✓ Good — no UI jitter, reliable persistence |
| Hydration in onWillStart (v1.3) | Prevents flash of empty state — traces loaded before first render | ✓ Good — seamless page refresh experience |
| hydrateTrace() reconstructs reactive(new Map()) (v1.3) | Plain objects from IDB break live-event reactivity; explicit wrapping required | ✓ Good — bus events work after hydration |
| Dual delete: reactive Map + IDB (v1.3) | Delete must be consistent across both stores in same operation | ✓ Good — no zombie traces on refresh |
| Raw JSON array export format (v1.3) | No metadata envelope — simple, importable by any tool | ✓ Good — clean round-trip |
| All-or-nothing import validation (v1.3) | First invalid element rejects entire file — no partial corrupted imports | ✓ Good — safe import behavior |

---
*Last updated: 2026-02-22 after v1.3 milestone*
