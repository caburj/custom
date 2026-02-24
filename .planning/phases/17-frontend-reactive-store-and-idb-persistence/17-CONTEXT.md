# Phase 17: Frontend Reactive Store and IDB Persistence - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Token and timing data flows from Phase 16 bus events into the OWL reactive store, survives page refresh via IDB persistence, and is accessible via computed getters for Phase 18 display components. This phase handles data plumbing and persistence only — visual display components and formatting are Phase 18.

</domain>

<decisions>
## Implementation Decisions

### Token granularity
- Full breakdown stored per iteration: input, output, cache_read, cache_write, reasoning, total
- Nested object shape: `iteration.tokens = { input, output, cache_read, cache_write, reasoning, total }`
- `duration_ms` stored as flat field on the iteration (server-measured value from Phase 16, stored as-is)
- `ai_provider` string stored on each iteration (e.g. 'openai', 'google') for Phase 18 metrics table

### Computed aggregations
- Trace-level computed getters for: total_input, total_output, total_cached, total_reasoning, total_tokens, total_duration_ms
- Computed from iteration list (OWL reactive sum on access), not incremental accumulator
- Per-iteration + per-trace aggregation levels only (no per-tool-call aggregation)
- Store exposes raw numbers only — formatting (abbreviation, locale, units) is Phase 18's concern

### Missing data handling
- Errored iterations: all token fields default to 0, duration_ms defaults to 0
- No separate hasTokenData flag — existing iteration error/status field is sufficient for Phase 18 to distinguish
- Hydration backfill: hydrateTrace fills missing token/timing fields with zero defaults for pre-Phase 17 IDB data
- Uniform shape guaranteed — no null checks needed downstream

### IDB persistence strategy
- In-memory reactive store updates instantly per bus event (OWL reactivity)
- IDB persist fires on loop_end only (not per-event write-through for token/timing data)
- Mid-trace refresh loses in-progress token data — acceptable since trace is interrupted anyway
- Extend existing serializeTrace to include tokens and duration_ms fields — no separate persist path

### Claude's Discretion
- Exact computed getter naming and implementation pattern
- How to wire bus event handler to update iteration tokens/timing fields
- serializeTrace/hydrateTrace field mapping details
- Any needed OWL reactive wrapper specifics

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. Follow existing OWL store patterns and Phase 10/11 IDB patterns in the codebase.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 17-frontend-reactive-store-and-idb-persistence*
*Context gathered: 2026-02-24*
