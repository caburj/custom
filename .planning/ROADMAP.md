# Roadmap: AI Debugger

## Milestones

- ✅ **v1.0 AI Debugger MVP** — Phases 1-3 (shipped 2026-02-20)
- 🚧 **v1.1 Live Tracer Standalone App** — Phases 4-7 (in progress)

## Phases

<details>
<summary>✅ v1.0 AI Debugger MVP (Phases 1-3) — SHIPPED 2026-02-20</summary>

- [x] Phase 1: Data Models and Instrumentation (2/2 plans) — completed 2026-02-20
- [x] Phase 2: Backend Views (1/1 plan) — completed 2026-02-20
- [x] Phase 3: Live Panel and Polish (2/2 plans) — completed 2026-02-20

Full details: `.planning/milestones/v1.0-ROADMAP.md`

</details>

### 🚧 v1.1 Live Tracer Standalone App (In Progress)

**Milestone Goal:** Replace the v1.0 backend-views-plus-panel architecture with a pure live tracer — a standalone OWL app at `/ai-debug` with a sidebar/detail layout, no database models, full payloads streamed over bus.bus.

- [x] **Phase 4: Infrastructure** - Delete v1.0 DB models and scaffold the standalone OWL app at `/ai-debug` (completed 2026-02-21)
- [ ] **Phase 5: Bus Instrumentation** - Rewrite instrumentation to emit full payloads over bus.bus with separate cursors and UUID keys
- [ ] **Phase 6: Sidebar Tree** - Implement the 3-level reactive sidebar (Loop > Iteration > Tool Call) with selection state
- [ ] **Phase 7: Detail Panel** - Wire the type-aware detail panel and complete session behavior

## Phase Details

### Phase 4: Infrastructure
**Goal**: A navigable `/ai-debug` URL that mounts a stub OWL app connected to bus_service, with all v1.0 backend views and ORM model files removed from the codebase
**Depends on**: Nothing (first phase of v1.1)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, MIGR-02
**Success Criteria** (what must be TRUE):
  1. Navigating to `/ai-debug` loads a standalone page (no Odoo navbar) for any internal user
  2. The browser console shows bus_service connected and receiving on the `ai_debug:*` channel
  3. No v1.0 backend view, menu, or ORM model files remain in the codebase
**Plans:** 2/2 plans complete
Plans:
- [ ] 04-01-PLAN.md — Delete v1.0 backend architecture and rewrite manifest for v1.1
- [ ] 04-02-PLAN.md — Scaffold standalone OWL app at /ai-debug with bus_service connection

### Phase 5: Bus Instrumentation
**Goal**: A running agentic loop emits four well-structured bus events with full payloads arriving one-by-one in the browser console, with UUID identifiers and payload size discipline enforced
**Depends on**: Phase 4
**Requirements**: BUS-01, BUS-02, BUS-03, BUS-04, BUS-05
**Success Criteria** (what must be TRUE):
  1. Triggering an agentic loop produces one `ai_debug/new_trace` event in the browser console before the first iteration begins, including agent name, model name, system prompt, and tools definition
  2. Each iteration produces an `ai_debug/iteration` event carrying messages_sent and raw_response while the loop is still running (not batched at request end)
  3. Each tool call produces an `ai_debug/tool_call` event with args, result, and state snapshots
  4. All trace, iteration, and tool call identifiers in bus payloads are UUIDs (no integer autoincrement IDs)
**Plans:** 1 plan
Plans:
- [ ] 05-01-PLAN.md — Instrument ai.session agentic loop with four bus event types and UUID identifiers

### Phase 6: Sidebar Tree
**Goal**: A working sidebar that populates in real time as bus events arrive, with Loop > Iteration > Tool Call hierarchy, stable selection under concurrent updates, and multiple loops shown as siblings
**Depends on**: Phase 5
**Requirements**: SIDE-01, SIDE-02, SIDE-03, SIDE-04, SIDE-05
**Success Criteria** (what must be TRUE):
  1. Each completed or running agentic loop appears as a top-level sidebar entry labeled by agent name
  2. Expanding a loop entry reveals its iterations in reverse chronological order (latest on top); expanding an iteration reveals its tool calls
  3. Clicking any sidebar item highlights it and the detail panel area reflects the selection (even if detail content is a placeholder)
  4. Triggering a second agentic loop while viewing iteration #1 of the first loop leaves the current selection and detail view unchanged
**Plans**: TBD

### Phase 7: Detail Panel
**Goal**: Clicking any sidebar node shows type-appropriate detail content drawn from the bus payload, with session ephemeral behavior and empty-state copy in place
**Depends on**: Phase 6
**Requirements**: DETL-01, DETL-02, DETL-03, SESS-01, SESS-02, SESS-03
**Success Criteria** (what must be TRUE):
  1. Selecting a loop in the sidebar shows its system prompt, RAG context, and tools definition rendered in the detail panel
  2. Selecting an iteration shows messages sent, raw LLM response, and state diff in the detail panel
  3. Selecting a tool call shows its arguments, result, and state diff in the detail panel
  4. Refreshing the browser clears all trace data and the app displays "Listening for agentic loops..." with no traces shown
**Plans**: TBD

## Progress

**Execution Order:** 4 → 5 → 6 → 7

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Data Models and Instrumentation | v1.0 | 2/2 | Complete | 2026-02-20 |
| 2. Backend Views | v1.0 | 1/1 | Complete | 2026-02-20 |
| 3. Live Panel and Polish | v1.0 | 2/2 | Complete | 2026-02-20 |
| 4. Infrastructure | 2/2 | Complete    | 2026-02-21 | - |
| 5. Bus Instrumentation | v1.1 | 0/1 | Not started | - |
| 6. Sidebar Tree | v1.1 | 0/? | Not started | - |
| 7. Detail Panel | v1.1 | 0/? | Not started | - |
