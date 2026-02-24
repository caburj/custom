# Phase 16: Backend Token Extraction and Per-Iteration Timing - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Instrument the provider layer to capture normalized token usage and per-iteration duration into bus events. Every iteration bus event carries accurate token counts (both providers) and server-measured duration. Tool call bus events also get duration_ms. No frontend changes — this phase is pure backend instrumentation.

</domain>

<decisions>
## Implementation Decisions

### Token field semantics
- Schema: `{input, output, total, cached, reasoning}` — five fields
- `total` uses the raw value from the provider API (not computed from input + output)
- `cached` and `reasoning` are sparse — omitted when 0, only present when non-zero
- `input`, `output`, `total` are always present on successful iterations
- No additional token categories beyond these five — keep it minimal

### Duration scope
- Three timing values per iteration: total duration, LLM API call duration, tool execution aggregate duration
- Total = LLM call + tool execution
- Tool execution duration is a single aggregate number at the iteration level (not per-tool-call)
- Individual tool call bus events also get their own `duration_ms` — captured in this phase
- Per-tool-call timing is already visible via tool call rows; iteration-level is the aggregate

### Provider-specific handling
- Per-provider extractor functions (separate logic for OpenAI and Google)
- Degrade gracefully on unexpected/missing token data: log warning, default missing fields to 0
- Extract tokens from the final stream chunk only (not accumulated across chunks)
- On errored iterations (network timeout, 500, etc.): skip the tokens field entirely — absence signals failure
- Duration is still captured up to the failure point even on errors

### Bus event structure
- Tokens as nested object: `tokens: {input: 150, output: 80, total: 230}` (cached/reasoning only when non-zero)
- Tokens field only on iteration events, not on tool call events
- Tool call events get `duration_ms` only
- Provider name included per iteration event (e.g. `provider: "openai"` or `provider: "google"`)

### Claude's Discretion
- Naming convention for timing fields (duration_ms, llm_ms, tools_ms or nested — Claude picks based on existing bus event conventions)
- Exact placement of timing hooks in the provider call stack
- How to handle the final stream chunk token extraction per provider
- Logging format for degraded token extraction warnings

</decisions>

<specifics>
## Specific Ideas

- "I want to see the full iteration duration which is broken down into (1) duration of the LLM API call and (2) total duration of tool calls"
- "Each tool call has its own row so duration per call will be in the tool call row" — aggregate only at iteration level
- Provider name per iteration enables showing which provider was used (useful for mixed-provider debugging)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 16-backend-token-extraction-and-per-iteration-timing*
*Context gathered: 2026-02-24*
