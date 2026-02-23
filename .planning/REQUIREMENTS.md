# Requirements: AI Debugger v1.4

**Defined:** 2026-02-23
**Core Value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## v1.4 Requirements

### Instrumentation

- [x] **INST-01**: Backend emits `session_id` (own ORM ID) in `new_trace` bus event payload
- [x] **INST-02**: Backend emits `parent_session_id` (parent ORM ID or null) in `new_trace` bus event payload for subagent sessions
- [x] **INST-03**: Backend injects parent trace context via `env.context` before `super()` in `_handle_tool_calls` so child session's `_run_agentic_loop` can read it

### Tree Nesting

- [ ] **TREE-01**: Subagent traces nest visually under the parent tool call that spawned them in the sidebar
- [ ] **TREE-02**: Tree supports arbitrary recursive nesting depth (subagents of subagents render correctly)
- [ ] **TREE-03**: Within a single trace, iterations and tool calls render at the same indentation level (flat within trace)
- [ ] **TREE-04**: Collapsing a parent trace hides all descendant traces, iterations, and tool calls
- [x] **TREE-05**: Frontend handles out-of-order bus events via pending-child buffer (child trace arriving before parent tool call is buffered and attached when parent arrives)

### Color Coding

- [ ] **COLR-01**: Each distinct agent is assigned a color from an 8-slot curated palette on first appearance
- [ ] **COLR-02**: Agent-to-color mapping is persisted to IndexedDB and survives page refresh
- [ ] **COLR-03**: Trace rows in the sidebar display a colored left border strip matching their agent's assigned color
- [ ] **COLR-04**: Compact color legend (agent name + color swatch) is displayed in the sidebar header area
- [ ] **COLR-05**: Detail panel header shows a colored agent name chip identifying which agent owns the selected node

### Data Integrity

- [ ] **DATA-01**: `serializeTrace()` and `hydrateTrace()` preserve parent linkage fields (`parent_trace_id`, `parent_tool_call_id`) across IDB roundtrip
- [ ] **DATA-02**: JSON export/import preserves subagent hierarchy — imported traces reconstruct parent-child nesting correctly
- [ ] **DATA-03**: Two-pass IDB hydration: first pass loads all traces, second pass validates parent pointers (handles random IDB record ordering)

## Future Requirements

### v1.4.1 Candidates

- **NEST-02**: Exact parent tool call matching via `parent_call_id` for parallel subagent disambiguation (currently deferred — `tools_context['tool_call_id']` not threaded to child session)
- **COLR-06**: Depth indicator (numeric label or vertical guide line) on deeply nested trace rows

## Out of Scope

| Feature | Reason |
|---------|--------|
| Timeline/Gantt view of concurrent agents | Agentic loop is synchronous — no concurrency to visualize |
| Sidebar filter by agent | Destroys multi-agent context that nesting is designed to show |
| Custom color picker per agent | Hash-based deterministic assignment is sufficient; same agent always gets same color |
| Inline diff between parent and child state | Would require backend payload changes; manual comparison via detail panel is sufficient |
| Auto-expand tree to selected item | Breaks user's intentional collapse state |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INST-01 | Phase 13 | Complete |
| INST-02 | Phase 13 | Complete |
| INST-03 | Phase 13 | Complete |
| TREE-05 | Phase 13 | Complete |
| COLR-01 | Phase 14 | Pending |
| COLR-02 | Phase 14 | Pending |
| DATA-01 | Phase 14 | Pending |
| DATA-02 | Phase 14 | Pending |
| DATA-03 | Phase 14 | Pending |
| TREE-01 | Phase 15 | Pending |
| TREE-02 | Phase 15 | Pending |
| TREE-03 | Phase 15 | Pending |
| TREE-04 | Phase 15 | Pending |
| COLR-03 | Phase 15 | Pending |
| COLR-04 | Phase 15 | Pending |
| COLR-05 | Phase 15 | Pending |

**Coverage:**
- v1.4 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-02-23*
*Last updated: 2026-02-23 after roadmap creation*
