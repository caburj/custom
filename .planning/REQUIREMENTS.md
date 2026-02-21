# Requirements: AI Debugger v1.1

**Defined:** 2026-02-20
**Core Value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## v1.1 Requirements

Requirements for the Live Tracer Standalone App milestone. Each maps to roadmap phases.

### Standalone App Infrastructure

- [x] **INFRA-01**: User can access the live tracer at `/ai-debug` as a standalone OWL app (no Odoo navbar/chrome)
- [x] **INFRA-02**: Any internal user (`base.group_user`) can access the app
- [x] **INFRA-03**: App boots with full Odoo service registry (bus_service, session, etc.)

### Cleanup

- [x] **MIGR-02**: All v1.0 backend views, menus, security CSV, and ORM model files are deleted

### Bus Instrumentation

- [x] **BUS-01**: Instrumentation sends full iteration data (messages_sent, raw_response, state snapshots) over bus.bus
- [x] **BUS-02**: Instrumentation sends full tool call data (args, result, state snapshots) over bus.bus
- [x] **BUS-03**: Loop start event includes system prompt, RAG context, tools definition, agent name, and model name
- [x] **BUS-04**: All bus sends use separate cursors for real-time delivery (not batched at HTTP commit)
- [x] **BUS-05**: UUID keys replace DB autoincrement IDs for trace/iteration/tool_call identification

### Sidebar Tree

- [x] **SIDE-01**: Sidebar shows one entry per agentic loop, labeled by agent name
- [x] **SIDE-02**: Expanding a loop shows its iterations (latest on top)
- [x] **SIDE-03**: Expanding an iteration shows its tool calls
- [x] **SIDE-04**: Clicking any item in the tree selects it and updates the detail panel
- [x] **SIDE-05**: New loops appear in the sidebar without stealing focus from current selection

### Detail Panel

- [ ] **DETL-01**: Selecting a loop shows system prompt, RAG context, and tools definition
- [ ] **DETL-02**: Selecting an iteration shows messages sent, raw response, state diff, and final message (if present)
- [ ] **DETL-03**: Selecting a tool call shows arguments, result, state diff, and confirmation info

### Session Behavior

- [x] **SESS-01**: All trace data lives in frontend memory only (no database persistence)
- [x] **SESS-02**: Refreshing the browser clears all trace data
- [x] **SESS-03**: App shows "Listening for agentic loops..." when no traces exist yet

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Replay

- **RPLY-01**: User can edit captured trace messages and re-run against the LLM

### Export

- **EXPT-01**: Traces exportable in OpenTelemetry (OTLP) format

### Evaluation

- **EVAL-01**: Automated LLM-as-judge scoring of captured traces

### Subagent Nesting

- **NEST-01**: Sidebar tree supports nested loops (subagent loop under parent loop iteration)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Database persistence | v1.1 is ephemeral by design — developer tool, session-scoped |
| DB migration script | Fresh DB assumed — no pre-migrate needed for table cleanup |
| Backend list/form views | Replaced by standalone app |
| Subagent nesting implementation | Anticipated in data design, deferred until upstream `ai` module supports it |
| Keyboard navigation in sidebar | P2 polish, not blocking for v1.1 |
| Search/filter in sidebar | Bounded tree depth makes this low-priority |
| localStorage persistence | Stale data risk, privacy concerns |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 4 | Complete |
| INFRA-02 | Phase 4 | Complete |
| INFRA-03 | Phase 4 | Complete |
| MIGR-02 | Phase 4 | Complete |
| BUS-01 | Phase 5 | Complete |
| BUS-02 | Phase 5 | Complete |
| BUS-03 | Phase 5 | Complete |
| BUS-04 | Phase 5 | Complete |
| BUS-05 | Phase 5 | Complete |
| SIDE-01 | Phase 6 | Complete |
| SIDE-02 | Phase 6 | Complete |
| SIDE-03 | Phase 6 | Complete |
| SIDE-04 | Phase 6 | Complete |
| SIDE-05 | Phase 6 | Complete |
| DETL-01 | Phase 7 | Pending |
| DETL-02 | Phase 7 | Pending |
| DETL-03 | Phase 7 | Pending |
| SESS-01 | Phase 7 | Complete |
| SESS-02 | Phase 7 | Complete |
| SESS-03 | Phase 7 | Complete |

**Coverage:**
- v1.1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-02-20*
*Last updated: 2026-02-20 — traceability filled after roadmap creation*
