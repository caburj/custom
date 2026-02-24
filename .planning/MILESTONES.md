# Milestones

## v1.0 AI Debugger MVP (Shipped: 2026-02-20)

**Phases completed:** 3 phases, 5 plans, 0 tasks

**Key accomplishments:**
- Persistent data models (trace/iteration/tool_call) with cascade delete, admin-only access, and configurable autovacuum retention
- Generator yield passthrough instrumentation capturing every LLM call, tool execution, state mutation, and confirmation event — zero behavioral change
- Backend views with searchable/filterable trace history, ace editor JSON display, and drill-down from trace to iteration to tool call
- Real-time bus.bus streaming pipeline with security-gated WebSocket channels (system users only)
- OWL debug panel with live timeline, collapsible JSON tree renderer, and state diff viewer

**Known tech debt:**
- Vestigial per-trace UUID channel subscriptions in debug_panel.js (harmless dead code)
- Missing explicit standalone list views for iteration and tool_call (auto-generated fallback works)
- TODO: save stripped binaries to ir.attachment (future enhancement)

---


## v1.1 Live Tracer Standalone App (Shipped: 2026-02-22)

**Phases completed:** 4 phases, 10 plans, 24 tasks (17 plan + 7 quick)
**Commits:** 110 (24 feat, 15 fix)
**LOC:** 2,061 (JS/XML/SCSS/Python)
**Timeline:** 2 days (2026-02-20 → 2026-02-21)

**Key accomplishments:**
- Deleted all v1.0 backend architecture (ORM models, views, security CSV) and scaffolded standalone OWL app at `/ai-debug` with bus_service connection and dark Catppuccin Mocha theme
- Instrumented ai.session agentic loop to emit 4 bus event types (new_trace, iteration, tool_call, loop_end) with UUID identifiers and separate cursors for real-time delivery
- Built reactive 3-level sidebar tree (Loop > Iteration > Tool Call) with stable selection under concurrent updates, reverse chronological ordering, slide-in animations, and scroll behavior
- Built type-aware detail panel with JsonTree, StateDiff, and TextPopupDialog shared components; tabbed Notebook views for loops (system prompt/RAG/tools), iterations (messages/response/state), and tool calls (args/result/state)
- Polished 7 quick-fix items covering cosmetic gaps, JSON tree indentation, dialog integration, mail widget hiding, and result styling

**Key decisions:**
- No DB persistence — ephemeral session-scoped data; bus.bus carries full payloads
- Standalone OWL app pattern (like POS self-order) — mountComponent from @web/env
- useState(new Map()) for reactive trace store (reactive() without callback doesn't register OWL render observer)
- Batch-level state granularity for tool calls (per-tool deferred to v1.2)

**Known tech debt:**
- Payload size for RAG-enabled sessions unknown — needs empirical baseline before meta/detail split
- Confirmation Info tab in ToolCallDetail is a placeholder (awaiting upstream ai module confirmation events)
- Per-tool state granularity deferred to v1.2 (currently batch-level before/after)

---


## v1.2 Native Theming (Shipped: 2026-02-22)

**Phases completed:** 2 phases, 4 plans, 7 tasks
**Commits:** 22 (507cbd6 → d45d4a3)
**Code changes:** 117 insertions, 165 deletions across 7 files (net -48 lines)
**Timeline:** 1 day (2026-02-22)

**Delivered:** Replaced hardcoded Catppuccin Mocha colors with Odoo's native SCSS variable system so the app respects the user's light/dark theme preference automatically.

**Key accomplishments:**
- Wired controller, manifest, and template for Odoo native dark mode via `webclient_rendering_context()` + split `t-call-assets` pattern
- Replaced all 231 hardcoded Catppuccin hex/rgba values in app.scss with 66 Odoo `$o-*` variable references
- Removed five dead component override blocks (Notebook colors, Dialog incl. filter:invert hack, CopyButton, error banner, popup content colors)
- Created `app.dark.scss` with `$o-*` syntax highlighting, excluded from light bundle and loaded after `web.dark_mode_variables` in dark bundle
- Migrated error banners from custom CSS to Bootstrap `alert-danger` for automatic dark-mode adaptation
- Browser visual verification confirmed both light and dark modes render correctly with zero regressions

**Key decisions:**
- `webclient_rendering_context()` over raw cookie reading — handles user settings, public user guard, Odoo-standard approach
- Dark bundle includes `ai_debug.assets` (not `web.assets_backend`) — avoids stripping dark variables
- JSON numbers use `$o-gray-700` light / `$o-warning` dark — warm amber contrast on dark background
- Bootstrap `alert-danger` replaces custom error banner — automatic dark-mode adaptation without custom CSS
- All panels use same `$o-webclient-background-color` — borders define separation, not background depth

**Known tech debt:**
- CSS visual correctness requires browser verification (inherent to CSS work, not a code gap)
- Per-tool state granularity still deferred (batch-level before/after from v1.1)

---


## v1.3 Local Persistence (Shipped: 2026-02-22)

**Phases completed:** 3 phases, 5 plans, 10 tasks
**Commits:** 35 (fb5ed05 → abbd5f5)
**Code changes:** 531 insertions, 18 deletions across 6 files
**Timeline:** 2 days (2026-02-20 → 2026-02-22)

**Delivered:** Traces persist across page refresh via IndexedDB with fire-and-forget writes, full hydration before first render, checkbox-based bulk delete, and JSON export/import with validation.

**Key accomplishments:**
- Created db.js IDB persistence module with fire-and-forget trace writes via Odoo's IndexedDB utility and ephemeral mode detection with amber badge indicator
- Bulk hydration from IDB via getAll() with reactive Map reconstruction in hydrateTrace() — traces appear before first render, no flash of empty state
- Checkbox multi-select sidebar with select-all/indeterminate state and bulk delete wired to both reactive Map and IDB
- Export checked traces as timestamped JSON file download via Blob URL pattern (createObjectURL → click → revokeObjectURL)
- Import traces with all-or-nothing JSON validation, ImportPreviewDialog showing trace/duplicate counts, and merge into reactive store + IDB

**Key decisions:**
- Write-through cache pattern: reactive Map is UI source of truth; IDB writes are fire-and-forget
- hydrateTrace() explicitly reconstructs reactive(new Map()) for nested Maps — plain IDB objects break reactivity
- All-or-nothing import validation: first invalid element rejects entire file
- Raw JSON array format for export (no metadata envelope)
- deleteCheckedTraces replaces clearAll — dual reactive Map + IDB delete in same operation

**Known tech debt:**
- Minor UX: if selected item is a child of a deleted trace, detail panel shows fallback state rather than proactively clearing selection (no crash)
- Degraded standalone mode: if dialog service unavailable in non-standard context, import error dialogs are silently suppressed (normal Odoo production path fully wired)

---


## v1.4 Subagent Support (Shipped: 2026-02-24)

**Phases completed:** 3 phases, 4 plans, 9 tasks
**Commits:** 8 feat commits (a6e5758 → 1132803)
**Code changes:** 837 insertions, 176 deletions across 14 files
**Timeline:** 4 days (2026-02-20 → 2026-02-24)

**Delivered:** Subagent hierarchy nesting in the sidebar — subagent traces nest under the tool call that spawned them with arbitrary depth, flat within-trace layout, and full data integrity across export/import and page refresh.

**Key accomplishments:**
- Python parent linkage: new_trace includes session_id, parent_trace_id, parent_tool_call_id for subagent causality chain
- Split tool_call events into tool_call_started/completed with stable UUID correlation via pre-generated _tc_id_map
- Pending-child buffer with 30s timeout prevents out-of-order bus events from misplacing child traces at root
- Sidebar tree rewrite: single flat t-foreach over computed sidebarNodes getter with arbitrary-depth nesting and VS Code guide lines
- Export cascade via _collectDescendantIds() includes all subagent descendant traces in JSON export
- Two-pass IDB hydration with orphan promotion and root-only auto-select on page refresh

**Key decisions:**
- Flat Map with parent pointers (not nested trace objects) — preserves all existing lookup, serialize, and selection functions
- sidebarNodes computed getter (flat array) + single t-foreach — avoids recursive OWL component anti-pattern
- _pendingChildren buffer keyed by LLM call_id — child traces arriving before parent tool call are buffered and attached when parent arrives
- Checkboxes only on depth===0 trace rows — subagent traces excluded from bulk select/delete
- COLR-01-05 descoped to v1.5 after initial audit identified scope gap

**Known tech debt:**
- TREE-01/TREE-02: visual nesting verified in code but needs human browser confirmation
- DATA-02/DATA-03: export/import and orphan promotion need human browser confirmation
- _applyImport does not run orphan-promotion pass (unreachable via normal export flow)
- CSS depth tint caps at 4 levels while JS tracks exact depth
- ai_parent_tool_call_id depends on base enterprise class setting tools_context['tool_call_id'] — fragile coupling

---


## v1.5 Live Metrics (Shipped: 2026-02-24)

**Phases completed:** 3 phases, 4 plans, 8 tasks + 7 quick tasks (28-34)
**Commits:** 9 feat commits (1b85695 → 576ebb7)
**Code changes:** 573 insertions, 8 deletions across 12 files
**Total LOC:** ~5,409 (JS/XML/SCSS/Python)
**Timeline:** 1 day (2026-02-24)

**Delivered:** Real-time token and timing metrics across the full stack — backend monkey-patch extracts normalized token usage from both OpenAI and Google, frontend reactive store aggregates totals, sidebar shows live counting metrics, and detail panels provide per-iteration breakdown with a pulsing elapsed timer.

**Key accomplishments:**
- `threading.local()` monkey-patch on `AIApiService._request` captures OpenAI and Google token usage with normalized `{input, output, total, cached, reasoning}` schema
- Server-measured per-iteration `duration_ms` via `time.monotonic()` on every iteration and tool call bus event
- `normalizeTokens()` + `getTraceTotals()` feed sidebar and detail panels through OWL reactive proxy chain with IDB round-trip persistence
- Sidebar compact metrics line with directional arrows (`350↑ 1.2k↓ tok`) updates live as iterations complete
- LoopDetail Metrics tab with per-iteration token/timing table and accounting-style totals row
- Pulsing live elapsed timer using `setInterval` + DOM mutation (not reactive state) with instant freeze on trace completion

**Key decisions:**
- Token data stripped at provider service layer — must patch `AIApiService._request` via `threading.local()`
- DB_VERSION not bumped — additive JSON fields on iteration blob require no IDB schema migration
- Count-up animation via OWL reactive re-render at LLM-call frequency (1-30s) — no rAF infrastructure needed
- DOM mutation timer via useRef+setInterval avoids OWL re-render overhead at 1Hz
- Token total uses raw provider value (not computed from input+output)

**Known tech debt:**
- `ai_provider` field stored in reactive store and IDB but not rendered (reserved for future provider-display feature)
- Sidebar shows "0ms" if thread-local timing stash fails but tokens succeed (requires unlikely partial failure; cosmetic only)

---

