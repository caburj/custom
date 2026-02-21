# Phase 6: Sidebar Tree - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement the 3-level reactive sidebar tree (Loop > Iteration > Tool Call) that populates in real time from bus events. Selection state drives the detail panel area (detail content is Phase 7). Multiple concurrent loops appear as siblings. Selection is stable under concurrent updates.

</domain>

<decisions>
## Implementation Decisions

### Tree visual style
- Comfortable density (~32-36px rows), like VS Code file explorer
- Distinct icons per level type (loop, iteration, tool call) for visual hierarchy
- Expand/collapse via chevron icon only — clicking the row text selects the item
- New loops appear expanded by default, showing iterations as they arrive

### Real-time update behavior
- Running loops/iterations show an animated indicator (pulsing dot or spinner) that stops on completion
- Completed loops show a checkmark icon; failed loops show an error icon (replaces spinner)
- New items animate in with a subtle slide-in or fade-in effect
- Sidebar always auto-scrolls to show the latest arriving item

### Selection & highlighting
- Clicking a loop node selects it AND expands it (single action to drill in)
- Selected item gets both a background fill and a left border accent for maximum visibility
- Ancestor nodes of the selected item show a faint background tint (breadcrumb trail)
- When a new loop arrives during an active selection, the new entry briefly flashes to draw attention, then settles
- Selection is never stolen by incoming events (SIDE-05)

### Loop entry labeling
- Loop entries: agent name + model name (e.g. "AccountMove Agent · claude-3.5")
- Iteration entries: iteration number + duration (e.g. "Iteration 3 · 2.1s")
- Tool call entries: tool name + success/failure status icon (e.g. "execute_kw ✔")
- Sidebar has a "Traces" header bar with a clear/trash button to wipe all traces and reset

### Claude's Discretion
- Exact icon choices for each level type
- Animation timing and easing curves
- Exact color values for selection highlight, ancestor tint, and flash effect
- How to compute iteration duration from available bus payload data
- Sidebar width and resize behavior

</decisions>

<specifics>
## Specific Ideas

- VS Code file explorer is the density/interaction reference — comfortable rows, chevron expand, click-to-select
- Completion state should be visually clear: spinner while running, checkmark/X when done
- The flash effect on new arrivals should be noticeable but not distracting

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-sidebar-tree*
*Context gathered: 2026-02-21*
