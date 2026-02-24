# Feature Research

**Domain:** Live metrics display for AI agentic loop developer tool (animated counters, token usage, per-iteration timing)
**Researched:** 2026-02-24
**Confidence:** HIGH — grounded in direct inspection of the existing codebase and provider API responses

---

## Scope Note

This milestone adds live time/token metrics to an existing, fully-functional tool. The features below are scoped only to what v1.5 introduces. Everything in v1.4 and earlier is shipped and not reconsidered here.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Developer tools that show LLM cost/performance universally display token counts and latency. Missing either makes the tool feel unfinished for its stated purpose.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Token counts per iteration (input + output) | Any LLM observability tool shows token usage — it drives cost and debugging | LOW | Data already in `raw_response`. OpenAI: `usage.input_tokens` / `usage.output_tokens`. Google: `usageMetadata.promptTokenCount` / `usageMetadata.candidatesTokenCount`. Extraction is the only work. |
| Trace-level token totals | Developers want total cost of a full agentic run, not just individual iterations | LOW | Sum across iterations after extraction; update on each iteration event as a computed getter. |
| Per-iteration wall-clock duration | How long did each LLM call take? Critical for performance debugging | LOW | `receivedAt` timestamps already exist on iteration objects in JS. `getIterationDuration()` already computes inter-iteration deltas (app.js line 729). Nothing displays it in the sidebar yet. |
| Trace-level total duration | Already captured: `loop_end` emits `duration_ms`. Not yet surfaced in sidebar row. | LOW | `trace.duration_ms` already populated by `_onLoopEnd` handler. Display only. |
| Compact sidebar row counters | Sidebar rows show time + tokens inline without requiring click-into detail panel | MEDIUM | Requires layout fitting within 34px/44px row height. Values update as events arrive during live run. |
| Detail panel token breakdown | Full per-iteration breakdown (input, output, cached, reasoning) in IterationDetail | LOW | Display extracted fields. Existing Notebook/tab structure in IterationDetail can add a Metrics tab. |

### Differentiators (What Makes This Display Useful Beyond Static Numbers)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Animated counting-up effect | Makes live updates visually obvious — developer sees new data arriving without scanning the UI | MEDIUM | Animation from 0 to target value on each update. Cap at ~300ms so it does not lag behind fast loops. Key constraint: animation must stop and hold when loop ends, not keep ticking. |
| Cached-token annotation | Shows how much of the input hit the prompt cache — directly informs cost optimization decisions | LOW | OpenAI: `usage.input_tokens_details.cached_tokens`. Google: `usageMetadata.cachedContentTokenCount`. Already logged by the provider layer — just needs surfacing in the normalized schema. |
| Reasoning-token annotation | Shows thinking/reasoning token cost separate from output — relevant for o-series and Gemini 2.5+ models | LOW | OpenAI: `usage.output_tokens_details.reasoning_tokens`. Google: `usageMetadata.thoughtsTokenCount`. Data is free once extraction is done. |
| Normalized token schema on the bus event | Provider-agnostic `tokens` field in the iteration bus payload — JS never needs to know OpenAI vs Google format | LOW-MEDIUM | Extract in Python at emit time. Schema: `{input, output, cached, reasoning, total}`. Total = input + output. Missing fields default to 0. |
| Per-iteration timing from Python (accurate wall-clock) | JS `receivedAt` timestamps measure round-trip including bus latency and render time. Python `time.perf_counter()` around `get_completions()` measures only LLM API latency. | LOW | Capture `iter_started_at` before `get_completions()` call in the instrumentation override; emit `duration_ms` in the iteration bus event. JS uses Python value when present, falls back to `receivedAt` delta. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Cost-in-currency display (e.g. "$0.003") | Developers want dollar cost per run | Provider pricing changes constantly; different tiers/orgs have different rates; no reliable per-model pricing source; OpenAI prices vary by cache status | Show token counts with cache breakout; let developers apply their own pricing. |
| Streaming token updates during LLM call | Show tokens counting up while the API call is in flight | Odoo's provider layer uses synchronous `_request()` HTTP calls — no streaming. Bus events only fire after `get_completions()` returns. The entire iteration is one atomic event. | Animate from 0 to final count over ~300ms on event arrival. This gives the feel of live counting without requiring streaming infrastructure changes. |
| Historical cost aggregation across sessions | Total tokens/cost across all IDB-stored traces | Requires pricing data, aggregate IDB queries across potentially large stores, currency handling. Not a developer observability feature. | Export traces as JSON; analyze externally with the token fields. |
| Token efficiency scores or derived metrics | "Tokens per tool call", "efficiency rating" | Meaningless without baseline; different tasks are not comparable. Adds interpretation burden without grounding. | Raw numbers (input, output, cached) give developers all the data to draw their own conclusions. |
| Model-specific display differences | Show different field labels depending on detected provider | Adds conditional rendering complexity; confuses users switching between providers | Normalize at extraction time in Python. JS always sees one unified schema. |

---

## Feature Dependencies

```
[Normalized token extraction in Python]
    └──required by──> [Token counters in sidebar rows]
    └──required by──> [Token breakdown in IterationDetail Metrics tab]
    └──required by──> [Trace-level token totals in LoopDetail]
    └──required by──> [Animated counter effect]

[Per-iteration duration_ms in Python bus event]
    └──enhances──> [Per-iteration timing in sidebar rows]
    (JS receivedAt fallback already exists via getIterationDuration() — Python value is more accurate)

[Sidebar compact counter layout (DOM)]
    └──required by──> [Animated counting-up effect]
    (Animation needs stable DOM targets with known current value to animate from)

[Trace-level token totals]
    └──requires──> [Normalized token extraction]
    └──computed by──> [Summing iteration.tokens.total across trace.iterations.values()]
    └──recommended implementation──> [JS computed getter, not a stored field]
```

### Dependency Notes

- **Normalized token extraction is the first task.** Every display feature depends on it. The JS layer must never parse `raw_response` for usage data — `raw_response` stays as an opaque blob for the Raw Response tab. A dedicated `tokens` field carries the structured extract.

- **`getIterationDuration()` already exists** (app.js line 729) and uses JS `receivedAt` timestamps. Python-side `duration_ms` on the iteration event measures only LLM API latency (not bus round-trip or render time). Both can coexist: display Python `duration_ms` when present, compute from `receivedAt` delta as fallback.

- **Animated counter requires reactive value changes.** The `_onIteration` handler already fires and updates the iteration object reactively. Adding animation means observing when `iteration.tokens.total` changes (from 0 or null to a new value) and triggering the count-up from 0.

- **Trace totals are computed on read, not stored.** A computed JS getter summing across `trace.iterations.values()` is simpler than maintaining an accumulator in `_onLoopEnd`. It avoids the question of what happens if the trace is later imported/hydrated (the sum is always correct from the iteration objects).

---

## Token Extraction: What the Code Actually Shows

This is not speculative — extracted directly from the provider service source.

**OpenAI provider** (`ai_api_service_openai.py` lines 86-94):
```python
if usage := response.get('usage'):
    _logger.info("...Tokens: %s in (%s cached)|%s out|%s reasoning",
        usage.get('input_tokens', 0),
        usage.get('input_tokens_details', {}).get('cached_tokens', 0),
        usage.get('output_tokens', 0),
        usage.get('output_tokens_details', {}).get('reasoning_tokens', 0),
    )
```
The `usage` dict is available in the full `response` dict. The provider returns `response.get("output", [])` — the usage dict is discarded before return.

**Google provider** (`ai_api_service_google.py` lines 75-83):
```python
if usage := response.get('usageMetadata'):
    _logger.info("...Tokens: %s in (%s cached)|%s out|%s reasoning",
        usage.get('promptTokenCount', 0),
        usage.get('cachedContentTokenCount', 0),
        usage.get('candidatesTokenCount', 0),
        usage.get('thoughtsTokenCount', 0),
    )
```
The `usageMetadata` dict is available in the full `response` dict. The provider returns `[content]` — the metadata is discarded before return.

**Implication:** Token extraction cannot happen in the existing `_run_agentic_loop` override by inspecting `item.get('metadata')`, because by the time `metadata` is set on the yielded item it contains only the formatted output list (no usage). Extraction requires either:

1. Overriding the service-level `get_completions()` in `ai_debug` to capture usage before discarding it — requires two subclass overrides (one per provider).
2. Adding a mutable container to `tools_context` that the service populates as a side effect — requires touching the service layer.
3. Introducing a hook in the `ai_debug` session override that intercepts the provider service call directly — cleanest without touching provider files.

The cleanest approach that stays within the `ai_debug` module's constraints (no modification to `ai` module) is option 3: override `get_completions()` on both service classes via a thin wrapper that runs in the `ai_debug` module. This is the same inheritance pattern used for `_run_agentic_loop`. The wrapper stashes the usage dict in `tools_context` or a thread-local before calling `super()`, then reads it back when emitting the iteration event.

---

## MVP Definition

This is a bounded feature addition. All items below are v1.5 scope as defined in PROJECT.md.

### Implementation Sequence (ordered by dependency)

1. **Python: Normalized token extraction** — Extract `tokens` dict from the full API response at the service layer (before it is discarded). Emit as `tokens` field in the iteration bus event alongside the existing `raw_response`. Schema: `{input, output, cached, reasoning, total}`.

2. **Python: Per-iteration duration_ms** — Capture `iter_started_at = time.perf_counter()` before each `get_completions()` call in `_run_agentic_loop`. Compute `duration_ms = int((time.perf_counter() - iter_started_at) * 1000)`. Emit in the iteration bus event.

3. **JS: Store tokens and duration_ms on iteration object** — The `_onIteration` handler stores `payload.tokens` and `payload.duration_ms` on the iteration. Trace object gains a computed getter `totalTokens` summing `iter.tokens.total` across all iterations.

4. **Sidebar compact counters** — Iteration rows show `duration_ms` (formatted) + `tokens.total`. Trace rows show accumulated totals. Layout must fit within existing 34px/44px row heights.

5. **Animated counting-up effect** — On each iteration event arrival, animate sidebar counter from 0 (or previous value) to new value over ~300ms. CSS transition or lightweight `useState`/`onPatched` pattern.

6. **IterationDetail Metrics tab** — New tab in the existing Notebook showing: input tokens, output tokens, cached tokens (if > 0), reasoning tokens (if > 0), duration_ms. All from `iteration.tokens` and `iteration.duration_ms`.

7. **LoopDetail totals section** — Aggregate metrics section: total tokens (all iterations), total duration (`trace.duration_ms` from loop_end), iteration count, tool call count.

### Defer to Post v1.5

- Subagent token roll-up: Include child trace token totals in the parent trace's sidebar counter. Subagent traces already show their own counters independently. Add only if user feedback identifies this as a pain point.
- IDB schema changes: The current denormalized record-per-trace approach (locked decision) stores token data inside iteration objects. No schema migration needed unless token aggregates become a query target.

### Future Consideration (v2+)

- Provider cost table (configurable per-model pricing per 1M tokens) mapped to extracted token counts — only viable if pricing data can be reliably maintained.
- OpenTelemetry OTLP export with token/duration attributes (EXPT-01 in PROJECT.md v2+ list).

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Normalized token extraction (Python) | HIGH | LOW-MEDIUM | P1 — everything else depends on this |
| Per-iteration duration_ms (Python) | HIGH | LOW | P1 |
| JS iteration object gains tokens + duration_ms | HIGH | LOW | P1 |
| Trace-level token totals (computed getter) | HIGH | LOW | P1 |
| Sidebar compact counters (time + tokens) | HIGH | MEDIUM | P1 |
| IterationDetail Metrics tab | HIGH | LOW | P1 |
| LoopDetail trace-level totals section | MEDIUM | LOW | P1 |
| Cached token annotation | MEDIUM | LOW | P1 — data is free once extraction exists |
| Animated counting-up effect | MEDIUM | MEDIUM | P1 |
| Reasoning token annotation | LOW-MEDIUM | LOW | P2 — relevant only on thinking models |
| Subagent token roll-up in parent | LOW | MEDIUM | P3 |

**Priority key:** P1 = in v1.5 scope, P2 = consider in v1.5 polish, P3 = future milestone

---

## Sources

- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — iteration event structure, `raw_response` capture, `loop_end` duration_ms (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — `_onIteration` handler, `getIterationDuration()` method, `_onLoopEnd` handler (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_openai.py` lines 86-94 — OpenAI usage logging pattern confirming field names (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_google.py` lines 75-83 — Google usageMetadata logging pattern confirming field names (HIGH — direct inspection)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` — `_run_agentic_loop` upstream implementation confirming how `metadata` is set on yielded items (HIGH — direct inspection)

---

*Feature research for: AI Debugger v1.5 Live Metrics (animated counters, token normalization, per-iteration timing)*
*Researched: 2026-02-24*
