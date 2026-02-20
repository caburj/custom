# Phase 2: Backend Views - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Searchable, filterable Odoo backend views for the three debug models (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`). Users can browse trace history, drill into iterations and tool calls, and filter by key dimensions. No custom JS, no live updates — standard Odoo XML views only. Live panel is Phase 3.

</domain>

<decisions>
## Implementation Decisions

### Trace list columns
- Compact essentials: agent, model, state, iteration count, duration, date — 6 columns max
- State column uses badge widget with color coding (no row-level decoration-*)
- Default sort: newest first (create_date desc — matches model `_order`)
- Duration displayed as human-friendly format ("1.2s", "3m 42s") via computed field

### Drill-down flow
- Trace → Iteration: One2many summary table on trace form; clicking opens iteration in its own form view
- Iteration → Tool Call: Same pattern — summary table; clicking opens tool call in its own form view
- Iteration summary table columns: index, duration, tool call count (minimal — just enough to pick which to open)
- Trace form uses tabbed notebook layout:
  - Tab 1: Iterations list
  - Tab 2: System prompt + RAG context
  - Tab 3: Error details (conditionally visible when state=error)

### JSON field display
- Use Odoo's ace editor widget (`widget='ace'`) in JSON mode, read-only, for all JSON fields
- Add computed Text fields that `json.dumps(indent=2)` the raw Json fields for pretty-printed display
- Iteration form uses separate tabs: messages sent, raw response, state snapshots, tool calls
- Tool call form: args use ace/JSON widget; result uses plain text widget (result can be any string)

### Search & grouping
- Search bar fields: agent, model, state, error_message (free-text)
- Default filters: "Errors" (state=error), "Today" (create_date=today)
- Group-by options: agent, model, state
- Tool call model gets its own search view with tool_name filter

### Claude's Discretion
- Exact field widths and form spacing
- Whether to add optional="hide" on any list columns
- Menu placement and naming within the Odoo backend
- Iteration and tool call list view column choices (beyond the decisions above)
- Ace editor height and configuration

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard Odoo view approaches. Keep it developer-focused and functional.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 02-backend-views*
*Context gathered: 2026-02-20*
