# Phase 15: Sidebar Rendering — Context

**Gathered:** 2026-02-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Display subagent traces nested under their parent tool call in the sidebar tree. Support arbitrary recursive depth. Flatten the within-trace hierarchy so iterations and tool calls share an indent level. Add vertical guide lines for depth tracking.

**Scope reduction:** Phase 14 (color assignment + IDB persistence) was temporarily skipped. All color requirements (COLR-03, COLR-04, COLR-05) are deferred until Phase 14 is complete. This phase delivers TREE-01, TREE-02, TREE-03, TREE-04 only.

</domain>

<decisions>
## Implementation Decisions

### Nesting visual treatment (TREE-01, TREE-02)
- Subagent traces use the full two-line trace format (query title + agent·model meta line) at all nesting depths — identical to root traces, just indented
- Fixed ~20px left-padding increment per nesting level (no diminishing or capping)
- Thin vertical guide lines (VS Code / file-explorer style) connect parents to children — helps track depth at a glance
- Text truncation happens naturally via CSS ellipsis; users widen the resizable sidebar if needed at deep nesting — no special handling

### Flat-within-trace layout (TREE-03)
- Iterations remain collapsible groups with chevrons (expand/collapse hides or shows their tool calls)
- Tool calls render at the **same indent** as their parent iteration — not further indented. This saves horizontal space while keeping the grouping logic intact
- Iteration rows use icon-based distinction from tool call rows (e.g., different prefix icon) so users can tell them apart at the same indent level
- Iteration rows show aggregate status: "Iteration N · X calls · Xs" (call count + timing)

### Subagent trace placement
- Subagent traces appear at the same indent level as tool calls within the parent trace (not indented further under the spawning tool call)
- Visually distinguished by being full two-line trace rows among single-line tool call rows
- The spawning tool call has no special treatment — tree nesting conveys the parent-child relationship

### Collapse behavior (TREE-04)
- Collapsing a trace hides all of its descendants: iterations, tool calls, and any nested subagent traces recursively
- Collapse state is per-row via the existing chevron mechanism

### Claude's Discretion
- Exact guide line styling (color, opacity, dash vs solid)
- Icon choices for iteration vs tool call distinction
- Chevron animation and transition details
- How aggregate call count is computed for running iterations

</decisions>

<specifics>
## Specific Ideas

- "Iterations are still collapsible groups, but tool calls shouldn't be indented further to save space"
- Subagent traces at same indent as tool calls — distinguished by two-line format, not extra indentation
- VS Code tree-view style guide lines for depth tracking

</specifics>

<deferred>
## Deferred Ideas

- COLR-03 (colored left border on trace rows) — blocked on Phase 14 color assignment
- COLR-04 (color legend in sidebar header) — blocked on Phase 14 color assignment
- COLR-05 (colored agent chip in detail panel header) — blocked on Phase 14 color assignment
- All three will be implemented as a follow-up after Phase 14 ships

</deferred>

---

*Phase: 15-sidebar-rendering*
*Context gathered: 2026-02-23*
