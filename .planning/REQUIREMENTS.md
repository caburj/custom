# Requirements: AI Debugger

**Defined:** 2026-02-20
**Core Value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Data Capture

- [x] **CAPT-01**: Module captures one `ai.debug.trace` record per agentic loop run with agent, model, total duration, iteration count, and termination state
- [x] **CAPT-02**: Module captures one `ai.debug.iteration` record per LLM call within a loop with full messages sent, raw response, and timing
- [x] **CAPT-03**: Module captures one `ai.debug.tool.call` record per tool execution with name, args, result, success, and timing
- [x] **CAPT-04**: Each iteration record stores the exact messages array sent to the LLM provider
- [x] **CAPT-05**: Each iteration record stores the raw provider response JSON verbatim
- [x] **CAPT-06**: Each trace records why the loop terminated (final message, max iterations, or confirmation pause)
- [x] **CAPT-07**: Duration in milliseconds is captured at trace, iteration, and tool call levels
- [x] **CAPT-08**: Exceptions during the loop are captured with `state = 'error'` and the exception message stored
- [x] **CAPT-09**: Each trace captures the full system prompt and RAG context injected at `_generate_next_response()` level
- [x] **CAPT-10**: Tool calls that trigger user confirmation are flagged with the confirmation message stored
- [x] **CAPT-11**: Each iteration records `tools_context['state']` snapshots before and after tool execution

### Configuration

- [x] **CONF-01**: `ir.config_parameter` master switch (`ai_debugger.enabled`) checked before any capture fires
- [x] **CONF-02**: Scheduled action auto-deletes traces older than configurable retention period (default 7 days)

### Backend Views

- [ ] **VIEW-01**: Backend list and form views for `ai.debug.trace` with search/filter
- [ ] **VIEW-02**: Backend list and form views for `ai.debug.iteration` accessible from trace
- [ ] **VIEW-03**: Backend list and form views for `ai.debug.tool.call` accessible from iteration
- [ ] **VIEW-04**: Traces filterable by agent, model, date range, and error state

### Live UI

- [ ] **LIVE-01**: OWL debug panel accessible as a separate browser tab/page, receiving real-time updates via `bus.bus` as the agentic loop runs
- [ ] **LIVE-02**: State diff viewer showing what changed in `tools_context['state']` between iterations
- [ ] **LIVE-03**: Collapsible JSON tree renderer for messages, raw responses, and state data

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Replay & Export

- **RPLY-01**: User can edit captured trace messages and re-run against the LLM
- **EXPT-01**: Traces exportable in OpenTelemetry (OTLP) format for external tools

### Evaluation

- **EVAL-01**: Automated LLM-as-judge scoring of captured traces

## Out of Scope

| Feature | Reason |
|---------|--------|
| HTTP-level LLM traffic interception | Fragile monkey-patching; model-layer capture provides everything needed |
| Mobile / responsive live panel UI | Developer tool, desktop only; data density doesn't suit small screens |
| Multi-instance / distributed tracing | Agentic loop is single-process; no value for local dev target |
| Real-time token streaming | Odoo uses line-delimited JSON, not per-token SSE; iteration-level timing suffices |
| Modifying the `ai` module | Instrumentation only via `_inherit`; zero changes to enterprise code |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| CAPT-01 | Phase 1 | Complete |
| CAPT-02 | Phase 1 | Complete |
| CAPT-03 | Phase 1 | Complete |
| CAPT-04 | Phase 1 | Complete |
| CAPT-05 | Phase 1 | Complete |
| CAPT-06 | Phase 1 | Complete |
| CAPT-07 | Phase 1 | Complete |
| CAPT-08 | Phase 1 | Complete |
| CAPT-09 | Phase 1 | Complete |
| CAPT-10 | Phase 1 | Complete |
| CAPT-11 | Phase 1 | Complete |
| CONF-01 | Phase 1 | Complete |
| CONF-02 | Phase 1 | Complete |
| VIEW-01 | Phase 2 | Pending |
| VIEW-02 | Phase 2 | Pending |
| VIEW-03 | Phase 2 | Pending |
| VIEW-04 | Phase 2 | Pending |
| LIVE-01 | Phase 3 | Pending |
| LIVE-02 | Phase 3 | Pending |
| LIVE-03 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-20*
*Last updated: 2026-02-20 after roadmap creation*
