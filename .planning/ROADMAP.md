# Roadmap: AI Debugger

## Milestones

- ✅ **v1.0 AI Debugger MVP** — Phases 1-3 (shipped 2026-02-20)
- ✅ **v1.1 Live Tracer Standalone App** — Phases 4-7 (shipped 2026-02-22)
- ✅ **v1.2 Native Theming** — Phases 8-9 (shipped 2026-02-22)
- ✅ **v1.3 Local Persistence** — Phases 10-12 (shipped 2026-02-22)
- ✅ **v1.4 Subagent Support** — Phases 13-15 (shipped 2026-02-24)
- 🚧 **v1.5 Live Metrics** — Phases 16-18 (in progress)

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

<details>
<summary>✅ v1.4 Subagent Support (Phases 13-15) — SHIPPED 2026-02-24</summary>

- [x] Phase 13: Python Instrumentation and Bus Event Handling (2/2 plans) — completed 2026-02-23
- [x] Phase 14: Sidebar Tree Nesting (1/1 plan) — completed 2026-02-23
- [x] Phase 15: Data Integrity Fixes (1/1 plan) — completed 2026-02-24

Full details: `.planning/milestones/v1.4-ROADMAP.md`

</details>

### v1.5 Live Metrics (In Progress)

**Milestone Goal:** Add real-time animated time and token counters to trace rows and detail panels, with per-iteration breakdown and normalized cross-provider token schema.

- [x] **Phase 16: Backend Token Extraction and Per-Iteration Timing** — Instrument the provider layer to capture normalized token usage and per-iteration duration into bus events (completed 2026-02-24)
- [ ] **Phase 17: Frontend Reactive Store and IDB Persistence** — Wire new bus event fields into the reactive trace store with computed total getters and symmetric IDB serialization
- [ ] **Phase 18: Display Components and Animation** — Render compact sidebar metrics, IterationDetail chips, LoopDetail Metrics tab, and live elapsed ticker

## Phase Details

### Phase 16: Backend Token Extraction and Per-Iteration Timing
**Goal**: Every iteration bus event carries accurate token counts (both providers) and server-measured duration
**Depends on**: Phase 15
**Requirements**: TOKN-01, TOKN-02, TOKN-03, TOKN-04, TIME-01, TIME-02
**Success Criteria** (what must be TRUE):
  1. An OpenAI iteration event observed in DevTools has `tokens.input > 0`, `tokens.output > 0`, `tokens.total > 0`
  2. A Google iteration event observed in DevTools has `tokens.input > 0`, `tokens.output > 0`, `tokens.total > 0`
  3. Every iteration event has `duration_ms > 0` (server-measured, not JS receivedAt delta)
  4. Iterations with no token data have all token fields default to 0, not null or undefined
  5. Trace-level total duration is available from the existing `loop_end.duration_ms` field
**Plans:** 1/1 plans complete
Plans:
- [ ] 16-01-PLAN.md -- Provider patch, token extraction, and iteration timing

### Phase 17: Frontend Reactive Store and IDB Persistence
**Goal**: Token and timing data flows from bus events into the reactive store, survives page refresh, and is accessible via computed getters
**Depends on**: Phase 16
**Requirements**: SIDE-02, PERS-01, PERS-02
**Success Criteria** (what must be TRUE):
  1. After running a trace, the reactive iteration object has `tokens` and `duration_ms` fields with non-zero values
  2. After a page refresh, hydrated iterations still have `tokens` and `duration_ms` (IDB round-trip preserved the data)
  3. The sidebar token/time counters increment visually as each new iteration event arrives during a live run
  4. An errored iteration that returns no tokens shows a safe display value (no NaN or crash)
**Plans**: TBD

### Phase 18: Display Components and Animation
**Goal**: Developers can read time and token metrics at a glance in the sidebar and drill into per-iteration breakdowns in detail panels
**Depends on**: Phase 17
**Requirements**: SIDE-01, DETL-01, DETL-02, DETL-03
**Success Criteria** (what must be TRUE):
  1. Sidebar trace rows show a compact metrics line (e.g. `"1.2s · 3,450 tok"`) that updates as iterations complete
  2. IterationDetail header shows duration and token count chips for that iteration
  3. LoopDetail Metrics tab shows a per-iteration table (input, output, cached, reasoning tokens + duration) with a totals row
  4. While a trace is actively running, the detail panel header shows a live elapsed timer updating at 1-second intervals
**Plans**: TBD

## Progress

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
| 14. Sidebar Tree Nesting | v1.4 | 1/1 | Complete | 2026-02-23 |
| 15. Data Integrity Fixes | v1.4 | 1/1 | Complete | 2026-02-24 |
| 16. Backend Token Extraction and Per-Iteration Timing | 1/1 | Complete    | 2026-02-24 | - |
| 17. Frontend Reactive Store and IDB Persistence | v1.5 | 0/? | Not started | - |
| 18. Display Components and Animation | v1.5 | 0/? | Not started | - |
