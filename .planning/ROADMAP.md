# Roadmap: AI Debugger

## Milestones

- ✅ **v1.0 AI Debugger MVP** — Phases 1-3 (shipped 2026-02-20)
- ✅ **v1.1 Live Tracer Standalone App** — Phases 4-7 (shipped 2026-02-22)
- ✅ **v1.2 Native Theming** — Phases 8-9 (shipped 2026-02-22)
- 🚧 **v1.3 Local Persistence** — Phases 10-12 (in progress)

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

### 🚧 v1.3 Local Persistence (In Progress)

**Milestone Goal:** Persist traces locally via IndexedDB so they survive page refresh, with delete/clear and export/import capabilities.

- [x] **Phase 10: IDB Layer and Write-Through** - Create db.js, define schema, wire fire-and-forget writes into bus event handlers (completed 2026-02-22)
- [x] **Phase 11: Hydration and Trace Management** - Load traces from IDB on startup, implement delete and clear-all controls (completed 2026-02-22)
- [x] **Phase 12: Export and Import** - Download all traces as JSON file, import from previously exported file with validation (completed 2026-02-22)

## Phase Details

### Phase 10: IDB Layer and Write-Through
**Goal**: Traces are durably written to IndexedDB as they arrive, providing the foundation all persistence features depend on
**Depends on**: Phase 9 (existing reactive store and bus event handlers in app.js)
**Requirements**: PERS-01, PERS-04
**Success Criteria** (what must be TRUE):
  1. After an agentic loop runs, closing and reopening DevTools confirms trace records exist in the ai_debug_traces IndexedDB store
  2. The UI never pauses or jitters during a fast agentic loop — bus events render without delay regardless of IDB write activity
  3. In a private browsing window where IndexedDB is blocked, the app opens and captures traces normally (ephemeral mode, no crash)
  4. Reloading the page while an agentic loop is still running does not corrupt any in-flight IDB record
**Plans:** 1/1 plans complete
Plans:
- [ ] 10-01-PLAN.md — Create db.js IDB persistence module + wire write-through and ephemeral mode into app

### Phase 11: Hydration and Trace Management
**Goal**: Traces from previous sessions are visible immediately on page load, and the user can remove individual traces or wipe all of them
**Depends on**: Phase 10
**Requirements**: PERS-02, PERS-03, MGMT-01, MGMT-02
**Success Criteria** (what must be TRUE):
  1. After capturing traces and refreshing the page, all previous traces appear in the sidebar before any new bus events arrive — no flash of empty state
  2. New bus events from a running agentic loop continue to populate the sidebar normally after hydration, with no regression in real-time updates
  3. Clicking delete on an individual trace removes it from the sidebar immediately and it does not reappear on the next page refresh
  4. Using select-all checkbox and delete button removes all traces from both the sidebar and IndexedDB — they are gone on next refresh
**Plans:** 2/2 plans complete
Plans:
- [ ] 11-01-PLAN.md — Hydrate all stored traces from IDB on page load with reactive Map reconstruction
- [ ] 11-02-PLAN.md — Checkbox-based multi-select sidebar with header action bar for bulk delete

### Phase 12: Export and Import
**Goal**: Users can save all traces to a JSON file and restore them later, enabling cross-session archival and sharing
**Depends on**: Phase 11
**Requirements**: XPRT-01, XPRT-02, XPRT-03
**Success Criteria** (what must be TRUE):
  1. Clicking "Export" triggers a browser file download of a JSON file containing all current traces in a versioned format
  2. Clicking "Import" and selecting that file restores all traces into the sidebar and into IndexedDB so they persist across subsequent refreshes
  3. Importing a malformed or incompatible JSON file shows a visible error notification and leaves existing traces untouched
**Plans:** 2/2 plans complete
Plans:
- [ ] 12-01-PLAN.md — Export selected traces as JSON file download
- [ ] 12-02-PLAN.md — Import traces from JSON file with preview dialog and validation

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
| 10. IDB Layer and Write-Through | 1/1 | Complete    | 2026-02-22 | - |
| 11. Hydration and Trace Management | 2/2 | Complete    | 2026-02-22 | - |
| 12. Export and Import | 2/2 | Complete   | 2026-02-22 | - |
