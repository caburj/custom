# Phase 7: Detail Panel - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire the type-aware detail panel so clicking any sidebar node (loop, iteration, tool call) shows its payload data in the right pane. Implement ephemeral session behavior: data lives in frontend memory only, browser refresh clears everything, and the app shows appropriate empty states. No database persistence, no new bus events, no new sidebar behavior.

</domain>

<decisions>
## Implementation Decisions

### Payload rendering
- Long text content (system prompts, RAG context, long string values in JSON) renders as a truncated preview; clicking opens a popup/dialog showing the full content with markdown/syntax highlighting
- Structured data (tool args, tool results, tools definitions, raw LLM responses) renders as a collapsible tree viewer (like browser DevTools JSON viewer)
- Within tree viewers, long text leaf values get the same truncated + popup treatment as standalone long text
- Every data section has a copy-to-clipboard button on the section header (copies raw content)

### Panel layout per node type
- **Loop detail:** Tabbed layout — System Prompt | RAG Context | Tools Definition
- **Iteration detail:** Tabbed layout — Messages Sent | Raw Response | State Diff
- **Tool call detail:** Args and Result stacked at the top (the core pair), then State Diff and Confirmation Info available as tabs below
- Each detail view has a header showing node type + name (e.g., "Loop: ai_session", "Tool Call: execute_kw")

### State diff visualization
- Side-by-side diff layout: Before column | After column
- Color-coded: green backgrounds for additions, red for removals, yellow/amber for changes
- When no state changes exist, show full state snapshot with no diff highlights (still inspectable)
- State diffs render inline in their tab — no popup treatment (typically compact enough)

### Empty & session states
- When no traces exist: sidebar shows "No traces yet", detail panel shows "Listening for agentic loops..."
- When traces exist but nothing selected: auto-select the most recent trace so the detail panel is never empty once data arrives
- New traces arriving never steal focus from current selection (consistent with SIDE-05)
- No ephemeral data indicator — developers understand session scope

### Claude's Discretion
- Exact popup/dialog component implementation
- Tab component choice and styling
- Tree viewer implementation approach
- Truncation thresholds for long text previews
- Exact color values for diff highlights
- Loading/transition states between selections

</decisions>

<specifics>
## Specific Ideas

- "I'm imagining a truncated/collapsed version, such that when clicked, a popup/custom dialog appears containing/rendering the full content. Most likely it's markdown so syntax highlight is appreciated."
- "JSON are rendered as tree (I believe there is already a tree component), can be folded and collapsed"
- Tool call detail should feel like a natural pair: args on top, result below, with supporting info (state diff, confirmation) in tabs underneath

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-detail-panel*
*Context gathered: 2026-02-21*
