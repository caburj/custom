# Requirements: AI Debugger

**Defined:** 2026-02-22
**Core Value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## v1.3 Requirements

Requirements for local persistence milestone. Each maps to roadmap phases.

### Persistence

- [ ] **PERS-01**: Traces auto-persist to IndexedDB as bus events arrive (fire-and-forget, non-blocking)
- [ ] **PERS-02**: All traces hydrate from IndexedDB on page load before first render (no flash of empty state)
- [ ] **PERS-03**: Live bus events continue to update the UI in real time after hydration without regression
- [ ] **PERS-04**: App degrades gracefully to ephemeral mode if IndexedDB is unavailable (e.g. private browsing)

### Trace Management

- [ ] **MGMT-01**: User can delete an individual trace (removed from both UI and IndexedDB)
- [ ] **MGMT-02**: User can clear all traces with a confirmation dialog before execution

### Export/Import

- [ ] **XPRT-01**: User can export all traces as a JSON file download
- [ ] **XPRT-02**: User can import a previously exported JSON file to restore traces
- [ ] **XPRT-03**: Invalid import files are rejected with a user-facing error notification

## Future Requirements

Deferred to future release. Tracked but not in current roadmap.

### Trace Selection

- **TSEL-01**: User can select specific traces for export (currently exports all)

### Advanced Export

- **EXPT-01**: Traces exportable in OpenTelemetry (OTLP) format

### Replay

- **RPLY-01**: User can edit captured trace messages and re-run against the LLM

### Subagent Support

- **NEST-01**: Sidebar tree supports nested loops (subagent loop under parent loop iteration)

### Evaluation

- **EVAL-01**: Automated LLM-as-judge scoring of captured traces

## Out of Scope

| Feature | Reason |
|---------|--------|
| Auto-expiry / TTL | Would delete traces the developer still needs; storage quota not a practical constraint |
| Server-side sync | Explicit design decision: no database persistence; export/import covers cross-machine sharing |
| Per-event normalized IDB schema | Wrong persistence unit; one denormalized record per trace is correct for this use case |
| Search/filter in sidebar | Bounded tree depth makes this low-priority (deferred from v1.1) |
| Selective import picker | Import all + delete unwanted is sufficient |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PERS-01 | — | Pending |
| PERS-02 | — | Pending |
| PERS-03 | — | Pending |
| PERS-04 | — | Pending |
| MGMT-01 | — | Pending |
| MGMT-02 | — | Pending |
| XPRT-01 | — | Pending |
| XPRT-02 | — | Pending |
| XPRT-03 | — | Pending |

**Coverage:**
- v1.3 requirements: 9 total
- Mapped to phases: 0
- Unmapped: 9

---
*Requirements defined: 2026-02-22*
*Last updated: 2026-02-22 after initial definition*
