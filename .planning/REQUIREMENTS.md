# Requirements: AI Debugger

**Defined:** 2026-02-24
**Core Value:** Full observability of the AI agentic loop — every LLM request/response, tool call with args and results, state mutations, and loop termination reasons — without altering the loop's behavior.

## v1.5 Requirements

Requirements for v1.5 Live Metrics. Each maps to roadmap phases.

### Token Extraction

- [ ] **TOKN-01**: Backend extracts normalized token usage from OpenAI API responses (input, output, total, cached, reasoning)
- [ ] **TOKN-02**: Backend extracts normalized token usage from Google API responses (input, output, total, cached, reasoning)
- [ ] **TOKN-03**: Iteration bus events include a `tokens` field with the normalized schema `{input, output, total, cached, reasoning}`
- [ ] **TOKN-04**: Missing token fields default to 0 so JS rendering is provider-agnostic

### Timing

- [ ] **TIME-01**: Backend captures per-iteration duration via `time.monotonic()` and emits `duration_ms` on iteration bus events
- [ ] **TIME-02**: Trace-level total duration surfaced from existing `loop_end.duration_ms`

### Sidebar Display

- [ ] **SIDE-01**: Trace rows show compact metrics line with total time and total tokens (e.g. `"1.2s · 3,450 tok"`)
- [ ] **SIDE-02**: Sidebar token/time counters increment visually as new iteration events arrive (OWL reactive count-up)

### Detail Panel

- [ ] **DETL-01**: IterationDetail shows duration and token count chips in the header
- [ ] **DETL-02**: LoopDetail shows a Metrics tab with per-iteration token/timing table and trace-level totals row
- [ ] **DETL-03**: Detail panel shows live elapsed timer for running traces (updates at 1-second granularity)

### Persistence

- [ ] **PERS-01**: Token and timing data persists through IDB round-trip (serializeTrace/hydrateTrace updated symmetrically)
- [ ] **PERS-02**: IDB schema version remains unchanged (no DB_VERSION bump)

## Future Requirements

### Subagent Token Roll-up

- **ROLL-01**: Parent trace total includes aggregated token counts from all descendant subagent traces

### Cost Display

- **COST-01**: Token counts converted to estimated cost using provider pricing rates

### Export Enhancements

- **EXPT-01**: Traces exportable in OpenTelemetry (OTLP) format with token/duration attributes

## Out of Scope

| Feature | Reason |
|---------|--------|
| Cost-in-currency display | Provider pricing changes too frequently; per-tier rates vary; not reliable to maintain |
| Historical cost aggregation | Requires pricing data, aggregate IDB queries, currency handling — too complex for v1.5 |
| Subagent token roll-up | Cross-trace accounting adds complexity with marginal value; each trace shows own totals |
| Anthropic/Claude provider | Not present in enterprise ai module; add normalization branch when provider ships |
| JS-side raw_response parsing for tokens | raw_response contains output list not HTTP envelope; tokens already stripped |
| DB_VERSION bump | Additive JSON fields don't require schema migration; bumping destroys stored history |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| TOKN-01 | Phase 16 | Pending |
| TOKN-02 | Phase 16 | Pending |
| TOKN-03 | Phase 16 | Pending |
| TOKN-04 | Phase 16 | Pending |
| TIME-01 | Phase 16 | Pending |
| TIME-02 | Phase 16 | Pending |
| SIDE-01 | Phase 18 | Pending |
| SIDE-02 | Phase 17 | Pending |
| DETL-01 | Phase 18 | Pending |
| DETL-02 | Phase 18 | Pending |
| DETL-03 | Phase 18 | Pending |
| PERS-01 | Phase 17 | Pending |
| PERS-02 | Phase 17 | Pending |

**Coverage:**
- v1.5 requirements: 13 total
- Mapped to phases: 13
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-24*
*Last updated: 2026-02-24 — traceability mapped to phases 16-18*
