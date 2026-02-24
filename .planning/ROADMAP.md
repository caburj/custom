# Roadmap: AI Debugger

## Milestones

- ✅ **v1.0 AI Debugger MVP** — Phases 1-3 (shipped 2026-02-20)
- ✅ **v1.1 Live Tracer Standalone App** — Phases 4-7 (shipped 2026-02-22)
- ✅ **v1.2 Native Theming** — Phases 8-9 (shipped 2026-02-22)
- ✅ **v1.3 Local Persistence** — Phases 10-12 (shipped 2026-02-22)
- 🚧 **v1.4 Subagent Support** — Phases 13-15 (in progress)

## Phases

<details>
<summary>✅ v1.0 AI Debugger MVP (Phases 1-3) — SHIPPED 2026-02-20</summary>

- [x] Phase 1: Data Models and Instrumentation (2/2 plans) — completed 2026-02-20
- [x] Phase 2: Backend Views (1/1 plan) — completed 2026-02-20
- [x] Phase 3: Live Panel and Polish (2/2 plans) — completed 2026-02-20

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

<details>
<summary>✅ v1.1 Live Tracer Standalone App (Phases 4-7) — SHIPPED 2026-02-22</summary>

- [x] Phase 4: Infrastructure (2/2 plans) — completed 2026-02-21
- [x] Phase 5: Bus Instrumentation (1/1 plan) — completed 2026-02-21
- [x] Phase 6: Sidebar Tree (5/5 plans) — completed 2026-02-21
- [x] Phase 7: Detail Panel (2/2 plans) — completed 2026-02-21

Full details: `.planning/milestones/v1.1-ROADMAP.md`

</details>

<details>
<summary>✅ v1.2 Native Theming (Phases 8-9) — SHIPPED 2026-02-22</summary>

- [x] Phase 8: Theme Infrastructure (1/1 plan) — completed 2026-02-22
- [x] Phase 9: SCSS Migration and Dark Accents (3/3 plans) — completed 2026-02-22

Full details: `.planning/milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>✅ v1.3 Local Persistence (Phases 10-12) — SHIPPED 2026-02-22</summary>

- [x] Phase 10: IDB Layer and Write-Through (1/1 plan) — completed 2026-02-22
- [x] Phase 11: Hydration and Trace Management (2/2 plans) — completed 2026-02-22
- [x] Phase 12: Export and Import (2/2 plans) — completed 2026-02-22

Full details: `.planning/milestones/v1.3-ROADMAP.md`

</details>

### 🚧 v1.4 Subagent Support (In Progress)

**Milestone Goal:** Visualize subagent hierarchies in the debugger — nest subagent traces under the tool call that spawned them, flatten the within-trace tree, and color-code agents.

- [x] **Phase 13: Python Instrumentation and Bus Event Handling** - Backend emits parent linkage in bus events; frontend buffers out-of-order child traces (completed 2026-02-23)
- [ ] **Phase 14: Agent Color Assignment and Display** - 8-color palette assignment per agent name; IDB persistence; colored sidebar borders, agent legend, and detail panel chip
- [x] **Phase 15: Sidebar Tree Nesting** - Computed sidebarNodes tree with flat within-trace layout, guide lines, and IDB parent linkage serialization (completed 2026-02-23)

## Phase Details

### Phase 13: Python Instrumentation and Bus Event Handling
**Goal**: Backend emits parent_trace_id and parent_tool_call_id so the frontend knows subagent causality; JS event handlers buffer out-of-order bus events without data loss
**Depends on**: Phase 12
**Requirements**: INST-01, INST-02, INST-03, TREE-05
**Success Criteria** (what must be TRUE):
  1. When a subagent session starts, the `new_trace` bus event payload includes a non-null `parent_session_id` (the ORM ID of the triggering session) and `session_id` (the subagent's own ORM ID)
  2. When a root session starts, the `new_trace` bus event payload includes `session_id` and `parent_session_id: null`
  3. A subagent `new_trace` event that arrives in the browser before its parent tool_call event is buffered and correctly attached to the parent trace once the parent tool_call event arrives — no trace is silently dropped or misplaced at root level
  4. Existing non-subagent sessions continue emitting events with no behavioral change
**Plans:** 2/2 plans complete
Plans:
- [x] 13-01-PLAN.md -- Python instrumentation: parent linkage in new_trace + tool call event splitting
- [x] 13-02-PLAN.md -- JS event handling: tool_call_started/completed migration + pending-child buffer

### Phase 14: Agent Color Assignment and Display
**Goal**: Each agent gets a deterministic palette color on first appearance, persisted to IDB; sidebar rows show colored left borders, an agent legend appears in the sidebar header, and a color chip identifies the agent in the detail panel
**Depends on**: Phase 13, Phase 15
**Requirements**: COLR-01, COLR-02, COLR-03, COLR-04, COLR-05
**Success Criteria** (what must be TRUE):
  1. Each distinct agent name is assigned one of 8 palette colors on its first `new_trace` event and retains that color for the lifetime of the session
  2. After a page refresh, each agent's assigned color is restored from IndexedDB — no color reassignment occurs
  3. Each trace row displays a 3px colored left border in the agent's assigned palette color
  4. A compact color legend showing agent names and color swatches is visible in the sidebar header; the detail panel header shows a colored chip identifying which agent owns the selected node
**Reconciliation note**: DATA-01 (flat Map with parent pointers), DATA-02 (export/import parent-child nesting), DATA-03 (IDB hydration with parent linking) were delivered by Phase 15 during its serializeTrace() fix and sidebarNodes getter implementation. COLR-03/04/05 were deferred from Phase 15 to here.
**Plans**: TBD

### Phase 15: Sidebar Tree Nesting
**Goal**: The sidebar tree displays subagent traces indented under their parent tool call with flat within-trace layout, guide lines, and IDB-persistent parent linkage
**Depends on**: Phase 13
**Requirements**: TREE-01, TREE-02, TREE-03, TREE-04, DATA-01, DATA-02, DATA-03
**Success Criteria** (what must be TRUE):
  1. Subagent traces appear indented under the tool call that spawned them in the sidebar; grandchild subagents indent further with no hardcoded depth limit
  2. Within a single trace, iterations and tool calls appear at the same indentation level — there is no separate iteration tier above tool calls
  3. Collapsing a parent trace hides all of its descendant traces, iterations, and tool calls
  4. serializeTrace() persists parent_trace_id, parent_tool_call_id, and session_id to IDB — parent-child nesting survives page refresh, export, and import
**Plans:** 1/1 plans complete
Plans:
- [x] 15-01-PLAN.md -- sidebarNodes getter, template rewrite to single t-foreach, SCSS guide lines, flat within-trace layout, serializeTrace() parent linkage fix

## Progress

**Execution Order:**
13 → 15 → 14 (Phase 15 executed before 14; Phase 14 narrowed to color work only)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Models and Instrumentation | v1.0 | 2/2 | Complete | 2026-02-20 |
| 2. Backend Views | v1.0 | 1/1 | Complete | 2026-02-20 |
| 3. Live Panel and Polish | v1.0 | 2/2 | Complete | 2026-02-20 |
| 4. Infrastructure | v1.1 | 2/2 | Complete | 2026-02-21 |
| 5. Bus Instrumentation | v1.1 | 1/1 | Complete | 2026-02-21 |
| 6. Sidebar Tree | v1.1 | 5/5 | Complete | 2026-02-21 |
| 7. Detail Panel | v1.1 | 2/2 | Complete | 2026-02-21 |
| 8. Theme Infrastructure | v1.2 | 1/1 | Complete | 2026-02-22 |
| 9. SCSS Migration and Dark Accents | v1.2 | 3/3 | Complete | 2026-02-22 |
| 10. IDB Layer and Write-Through | v1.3 | 1/1 | Complete | 2026-02-22 |
| 11. Hydration and Trace Management | v1.3 | 2/2 | Complete | 2026-02-22 |
| 12. Export and Import | v1.3 | 2/2 | Complete | 2026-02-22 |
| 13. Python Instrumentation and Bus Event Handling | v1.4 | 2/2 | Complete | 2026-02-23 |
| 15. Sidebar Tree Nesting | v1.4 | 1/1 | Complete | 2026-02-23 |
| 14. Agent Color Assignment and Display | v1.4 | 0/? | Not started | - |
