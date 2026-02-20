# Phase 3: Live Panel and Polish - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Real-time OWL debug panel accessible as a separate browser tab via `ir.actions.client`, receiving live iteration and tool call events via `bus.bus` as the agentic loop runs. Includes a collapsible JSON tree renderer for messages/responses and a side-by-side state diff viewer. Replay, export, and evaluation features are out of scope (v2).

</domain>

<decisions>
## Implementation Decisions

### Panel layout
- Vertical timeline with a rail connecting iterations top-to-bottom
- Tool calls nested under their parent iteration in the timeline
- Medium density on collapsed iteration nodes: iteration number, duration, tool count, message count, and status indicator
- Clicking an iteration or tool call expands to show detail (JSON tree for messages, response, etc.)
- Active/streaming iteration shown at the bottom with animation

### Real-time behavior
- Always auto-scroll to follow the latest event as iterations and tool calls arrive
- Live only — opening the panel mid-loop shows only events arriving after open, no historical backfill
- Always-visible connection status indicator (connected/disconnected/reconnecting badge/dot)
- Loop completion signaled by trace status change in header only — no banner or overlay

### State diff presentation
- Side-by-side layout: before state on left, after state on right, changes highlighted
- Displayed inside the iteration expand area (a tab/section alongside messages and response)
- Unchanged keys collapsed by default (e.g., "... 5 unchanged keys") with click to expand
- Deep diff vs top-level diff: Claude's discretion based on what state data typically looks like

### JSON tree interaction
- Default expansion: 1-2 levels deep (top-level keys expanded, nested objects collapsed)
- Syntax highlighting by type: strings green, numbers blue, booleans orange, nulls gray
- No search/filter — just expand/collapse navigation
- Copy-to-clipboard icon on hover for any node — copies that subtree as JSON

### Claude's Discretion
- Header/toolbar design (trace selector vs minimal header)
- Deep diff algorithm choice for state comparison
- Exact color palette and spacing for the timeline
- Loading/skeleton states
- Error state handling and display

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-live-panel-and-polish*
*Context gathered: 2026-02-20*
