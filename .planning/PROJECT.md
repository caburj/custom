# AI Debugger — Custom Odoo Module

## What This Is

A custom Odoo module that instruments the enterprise `ai` module's agentic loop to provide live visibility into every LLM call, tool execution, state change, and loop iteration — including nested subagent hierarchies and real-time token/timing metrics. Delivered as a standalone OWL app at `/ai-debug` that respects the user's Odoo light/dark theme preference. Traces persist locally via IndexedDB across page refresh, with checkbox-based bulk delete, JSON export/import (with subagent cascade), and automatic ephemeral mode fallback when IDB is unavailable. Subagent traces nest under the tool call that spawned them with arbitrary depth and VS Code-style guide lines. Per-iteration token counts and duration are extracted from both OpenAI and Google providers, displayed as live counters in the sidebar and detailed breakdowns in the Metrics tab.

## Core Value

Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## Current State

**Shipped v1.5** (2026-02-24) — Live Metrics

The module is a fully functional developer tool with:
- Standalone OWL app at `/ai-debug` with Odoo-native light/dark theme support
- Real-time bus.bus streaming with separate cursors for immediate event delivery
- Subagent hierarchy nesting: child traces indent under parent tool call with arbitrary depth, flat within-trace layout, VS Code guide lines
- Pending-child buffer handles out-of-order bus events (30s timeout with orphan promotion)
- Split tool_call_started/completed events with stable UUID correlation
- 3-level sidebar tree with expand/collapse, stable selection, reverse chronological ordering, animations
- Type-aware detail panels with tabbed Notebook views, JSON tree rendering, state diff visualization
- IndexedDB persistence with fire-and-forget writes — traces survive page refresh
- Two-pass IDB hydration: first pass loads all traces, second pass promotes orphans to root
- Root-only auto-select on page load (newest root trace by created_ts)
- Checkbox multi-select (root traces only) with select-all/indeterminate for bulk delete (cascades to descendants)
- JSON export of selected traces (cascades to subagent descendants) and import with all-or-nothing validation + preview dialog
- Ephemeral mode degradation when IDB unavailable (amber badge indicator)
- Conditional CSS bundle loading via `webclient_rendering_context()` — automatically adapts to user's theme preference
- All SCSS uses Odoo `$o-*` variables — zero hardcoded colors
- **Normalized token extraction** from OpenAI and Google providers via `threading.local()` monkey-patch on `AIApiService._request`
- **Per-iteration timing** via server-measured `time.monotonic()` duration on every iteration bus event
- **Sidebar live counters** showing total time and directional token split (input/output) that update as iterations complete
- **IterationDetail header chips** displaying duration and token count per iteration
- **LoopDetail Metrics tab** with per-iteration token/timing table (input, output, cached, reasoning, duration) and accounting-style totals row
- **Live elapsed timer** with pulsing chip animation using setInterval DOM mutation, instant freeze on trace completion

**Tech stack:** Odoo OWL standalone app, bus.bus WebSocket, generator yield passthrough instrumentation, IndexedDB via `@web/core/utils/indexed_db`.
**LOC:** ~5,409 (JS/XML/SCSS/Python)
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
- ✓ Backend instrumentation emits parent_trace_id and parent_tool_call_id for subagent sessions — v1.4
- ✓ Sidebar tree flattened within a trace (iterations/tool calls at same level) — v1.4
- ✓ Subagent traces nest under parent tool call with recursive depth — v1.4
- ✓ Export/import cascades to subagent descendants preserving hierarchy — v1.4
- ✓ Two-pass IDB hydration with orphan promotion — v1.4
- ✓ Root-only auto-select on page load — v1.4
- ✓ Extract and normalize token usage from LLM API responses into explicit fields on iteration bus events — v1.5
- ✓ Per-iteration timing (duration_ms per iteration) — v1.5
- ✓ Sidebar trace rows show compact live counters: total time, total tokens (animated counting up) — v1.5
- ✓ Detail panel shows full per-iteration token and timing breakdown with trace-level totals — v1.5
- ✓ Animated counter effect that ticks up from 0 as new iteration events arrive in real time — v1.5

### Active

## Current Milestone: v1.6 Per-DB IndexedDB Isolation

**Goal:** Scope IndexedDB instances by the Odoo database name so traces from different databases are completely isolated.

**Target features:**
- IndexedDB database name includes current Odoo DB name (e.g. `ai_debug_aaa` for DB `aaa`)
- App reads current Odoo DB name at load and opens the correct IDB instance
- No UI changes — traces naturally belong to the current DB

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
- Timeline/Gantt view of concurrent agents — agentic loop is synchronous
- Sidebar filter by agent — destroys multi-agent context nesting is designed to show
- Custom color picker per agent — hash-based deterministic assignment is sufficient
- Auto-expand tree to selected item — breaks user's intentional collapse state
- Cost-in-currency display — provider pricing changes too frequently; per-tier rates vary
- Historical cost aggregation — requires pricing data, aggregate IDB queries, currency handling
- Subagent token roll-up — cross-trace accounting adds complexity with marginal value
- Anthropic/Claude provider — not present in enterprise ai module yet
- JS-side raw_response parsing for tokens — raw_response contains output list not HTTP envelope
- DB_VERSION bump for token fields — additive JSON fields don't require schema migration

## Context

**Source locations:**
- Enterprise: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/`
- Core: `/Users/joseph/clones/odoo/odoo/.worktrees/master/`

**v2+ candidates:**
- RPLY-01: User can edit captured trace messages and re-run against the LLM
- EXPT-01: Traces exportable in OpenTelemetry (OTLP) format
- EVAL-01: Automated LLM-as-judge scoring of captured traces
- TSEL-01: User can select specific traces for export (currently exports all checked)
- NEST-02: Exact parent tool call matching via parent_call_id for parallel subagent disambiguation
- ROLL-01: Parent trace total includes aggregated token counts from all descendant subagent traces
- COST-01: Token counts converted to estimated cost using provider pricing rates

**Known tech debt:**
- Payload size for RAG-enabled sessions unknown (needs empirical baseline)
- Confirmation Info tab in ToolCallDetail is a placeholder
- Per-tool state granularity deferred (currently batch-level before/after)
- Minor UX: if selected item is a child of a deleted trace, detail panel shows fallback state rather than clearing selection
- Degraded standalone mode: dialog service unavailable suppresses import error dialogs silently
- _applyImport does not run orphan-promotion pass (unreachable via normal export flow)
- CSS depth tint caps at 4 levels while JS tracks exact depth
- ai_parent_tool_call_id depends on base enterprise class setting tools_context['tool_call_id'] — fragile coupling
- ai_provider field stored in reactive store and IDB but not rendered (reserved for future provider-display feature)
- Sidebar shows "0ms" if thread-local timing stash fails but tokens succeed (cosmetic only)

## Constraints

- **Odoo version**: Master branch only
- **Dependency**: Requires enterprise `ai_app` module installed
- **Approach**: Model inheritance only (`_inherit = 'ai.session'`), no monkey-patching (except provider service layer for token extraction)
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
| Flat Map with parent pointers (v1.4) | Preserves all existing lookup, serialize, and selection functions | ✓ Good — no refactor needed |
| sidebarNodes computed getter (v1.4) | Flat array + single t-foreach avoids recursive OWL component anti-pattern | ✓ Good — simple rendering |
| _pendingChildren buffer (v1.4) | Prevents out-of-order child traces silently landing at root | ✓ Good — reliable hierarchy construction |
| Split tool_call events (v1.4) | tool_call_started/completed enables live progress display | ✓ Good — immediate tool call visibility |
| _tc_id_map pre-generated UUIDs (v1.4) | Guarantees started/completed events share stable UUID | ✓ Good — reliable event correlation |
| Context threading via with_context() (v1.4) | env lineage propagates to all ORM calls within same env | ✓ Good — parent linkage crosses model boundaries |
| Checkboxes only on root traces (v1.4) | Subagent traces are conceptually part of parent — separate selection confusing | ✓ Good — clean UX |
| COLR descoped from v1.4 to v1.5 (v1.4) | Audit revealed scope gap; color-coding is additive, not core hierarchy work | ✓ Good — shipped on time |
| Two-pass IDB hydration (v1.4) | Random IDB record ordering requires post-load validation of parent pointers | ✓ Good — orphans promoted correctly |
| Export cascade via _collectDescendantIds (v1.4) | Same pattern as delete cascade — consistent, proven | ✓ Good — full hierarchy exported |
| threading.local() monkey-patch for token capture (v1.5) | Token data stripped at provider service layer before instrumentation can see it | ✓ Good — reliable cross-provider capture |
| Token total uses raw provider value (v1.5) | Not computed from input+output — preserves any provider-internal discrepancy | ✓ Good — accurate reporting |
| Tokens field absent on errored iterations (v1.5) | Absence signals failure; null/undefined would require explicit null checks | ✓ Good — clean error signaling |
| No DB_VERSION bump for token fields (v1.5) | Additive JSON fields on iteration blob require no IDB schema migration | ✓ Good — no data loss on upgrade |
| normalizeTokens maps cached→cache_read (v1.5) | Locked schema decision; cache_write always 0 until backend field exists | ✓ Good — consistent schema |
| getTraceTotals reads reactive proxy chain (v1.5) | OWL re-renders sidebar as new iterations arrive — SIDE-02 satisfied | ✓ Good — live counting effect |
| DOM mutation timer via useRef+setInterval (v1.5) | Avoids OWL re-rendering entire LoopDetail at 1Hz | ✓ Good — smooth timer with no jank |
| Timer chip swap via t-if/t-elif (v1.5) | Instant freeze on trace completion — no CSS transition needed | ✓ Good — clean lifecycle |
| Monochrome ai-metric-chip (v1.5) | Gray-200/700, no color-coding — clean developer-tool aesthetic | ✓ Good — consistent look |

---
*Last updated: 2026-02-26 after v1.6 milestone start*
