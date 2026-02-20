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

