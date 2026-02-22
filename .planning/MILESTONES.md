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

