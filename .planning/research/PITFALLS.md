# Pitfalls Research

**Domain:** Adding live animated token/time metrics to an existing OWL streaming debugger (ai_debug v1.5)
**Researched:** 2026-02-24
**Confidence:** HIGH (grounded in direct codebase inspection of ai_debug and the upstream enterprise `ai` module)

This document supersedes the v1.4 PITFALLS.md for v1.5 planning. V1.4 pitfalls are resolved and confirmed. This document focuses exclusively on the new surface area: token extraction from two structurally different LLM providers, per-iteration timing instrumentation, animated counters in OWL's reactive rendering system, and IDB schema additions for new fields.

---

## Critical Pitfalls

### Pitfall 1: Token Data Is Stripped Before the Instrumentation Override Can See It

**What goes wrong:**
The `iteration` bus event already carries `raw_response: item.get('metadata')`. The natural first assumption is that `raw_response` contains the full HTTP response envelope — including usage fields. It does not.

Tracing the data flow from the actual source code:

- **OpenAI** (`AIApiServiceOpenAI.get_completions`, lines 86-100): the full HTTP response dict has both a `usage` key and an `output` key. The logger reads `response.get('usage')`, then the method returns `response.get('output', [])`. The `output` list is what becomes `metadata` in `_run_agentic_loop` → `raw_response` in the bus event. `usage` is gone.
- **Google** (`AIApiServiceGoogle.get_completions`, lines 75-101): the full HTTP response dict has both `usageMetadata` and `candidates`. The logger reads `response.get('usageMetadata')`, then the method returns `[content]` (a single-element list from `candidates[0]['content']`). `usageMetadata` is gone.

The `ai_debug` override of `_run_agentic_loop` calls `super()._run_agentic_loop()` and iterates its yielded items. At that point the raw HTTP envelope is already gone — it was consumed inside the service layer. Reading `payload.raw_response?.usage` or `payload.raw_response?.[0]?.usageMetadata` in JS will always be `undefined`.

**Why it happens:**
The service layer was designed to return only LLM *output* (messages / tool calls), discarding the HTTP envelope. The logging calls in the service files are the only consumers of token data today. It is natural to assume `metadata` (= `raw_response`) would carry everything — but it only carries what `get_completions()` returns.

**How to avoid:**
Token counts must be extracted *inside* the service layer, before the envelope is discarded, and surfaced through a side channel that the instrumentation override can read.

The correct interception point is to override `get_completions()` on each provider's service class inside `ai_debug`. Since `AIApiServiceOpenAI` and `AIApiServiceGoogle` are concrete classes (not Odoo models), they cannot use `_inherit`. The practical options are:

1. **Add a thread-local / mutable-dict side channel**: pass a mutable dict (e.g., `token_sink = {}`) through `tools_context` into the service call. Subclass the service classes in `ai_debug` to write token data into the sink. Override `provider.get_service()` at the provider level to return the debug-aware subclass. This requires adding module-level subclasses for each provider service.

2. **Inject into `tools_context`**: the `_debug_ctx` mutable dict is already threaded through `tools_context`. Add a `token_sink` list to `_debug_ctx` before calling `super()._run_agentic_loop()`. Override `get_completions()` to append to it after each API call. The iteration event then reads from `_debug_ctx['token_sink'][-1]` after each yield.

3. **Minimal approach — extract from `raw_response` at the Odoo model layer**: Override `_run_agentic_loop` to call the service directly (not via `super()`) and capture the pre-formatted response. This duplicates the service-call logic and breaks the override-only constraint.

Option 2 (mutable `token_sink` in `_debug_ctx`) is the least invasive: it requires subclassing the service classes to write a single dict into a pre-existing channel, with no changes to the main agentic loop logic.

**Warning signs:**
- JS code doing `payload.raw_response?.usage` or `payload.raw_response?.[0]?.usageMetadata` — both are always undefined
- Sidebar counters stuck at 0 tokens for all runs, all providers
- The `iteration` bus event payload has no top-level `tokens` field

**Phase to address:** Backend token extraction (the first backend phase). Must be resolved before any frontend counter work begins, as zero tokens arriving means the UI cannot be validated.

---

### Pitfall 2: OpenAI and Google Use Structurally Different Token Field Names — a Single Extraction Path Silently Drops One Provider

**What goes wrong:**
Even with a correct interception point, the two providers use completely different JSON structures for usage data:

| Field | OpenAI (`usage` key in HTTP response) | Google (`usageMetadata` key in HTTP response) |
|-------|----------------------------------------|------------------------------------------------|
| Envelope key | `usage` | `usageMetadata` |
| Input tokens | `input_tokens` | `promptTokenCount` |
| Output tokens | `output_tokens` | `candidatesTokenCount` |
| Cached tokens | `input_tokens_details.cached_tokens` | `cachedContentTokenCount` |
| Reasoning tokens | `output_tokens_details.reasoning_tokens` | `thoughtsTokenCount` |

This is confirmed directly from the logger calls in the two service files (lines 87-94 in `ai_api_service_openai.py` and lines 76-83 in `ai_api_service_google.py`).

A normalizer that only checks `response.get('usage')` returns zeros for Google. A normalizer that only checks `response.get('usageMetadata')` returns zeros for OpenAI. Because the service returns normally (no error) and the fallback is `0`, the failure is completely silent.

**Why it happens:**
The logging calls in the two service files provide the ground truth, but they are easy to miss when writing a new normalizer. Developers test against one provider, see non-zero counts, and ship.

**How to avoid:**
Write a single Python normalizer function with explicit branches for both envelope keys:

```python
def _ai_debug_normalize_tokens(raw_envelope):
    """Extract token counts from the raw HTTP response envelope before stripping.
    raw_envelope is the full response dict from self._request(), not the stripped output.
    """
    if usage := raw_envelope.get('usage'):           # OpenAI Responses API
        return {
            'input_tokens': usage.get('input_tokens', 0),
            'output_tokens': usage.get('output_tokens', 0),
            'cached_tokens': (usage.get('input_tokens_details') or {}).get('cached_tokens', 0),
            'reasoning_tokens': (usage.get('output_tokens_details') or {}).get('reasoning_tokens', 0),
        }
    if usage := raw_envelope.get('usageMetadata'):   # Google Gemini
        return {
            'input_tokens': usage.get('promptTokenCount', 0),
            'output_tokens': usage.get('candidatesTokenCount', 0),
            'cached_tokens': usage.get('cachedContentTokenCount', 0),
            'reasoning_tokens': usage.get('thoughtsTokenCount', 0),
        }
    return {'input_tokens': 0, 'output_tokens': 0, 'cached_tokens': 0, 'reasoning_tokens': 0}
```

Unit-test this function with fixture dicts representing both provider HTTP responses.

**Warning signs:**
- Token counters work for one model family but show 0 for another
- No unit test covers both OpenAI and Google fixture responses
- Normalizer written with only one provider's field names verified against actual API docs

**Phase to address:** Backend token extraction phase — add a fixture-based unit test covering both provider shapes before the normalizer is considered done.

---

### Pitfall 3: `time.monotonic()` Measures Server-Side Elapsed Time, But JS `receivedAt` Differences Include Bus Latency

**What goes wrong:**
The existing `getIterationDuration()` method in `app.js` computes per-iteration duration by differencing `receivedAt` timestamps (JS `Date.now()` at the moment the bus event arrives at the browser). This works well enough for a rough display, but bus.bus delivery latency — typically 50-300ms — is included in every gap measurement. For a featured "per-iteration time" metric (not just a rough display), this inaccuracy is visible:

- Fast iterations (< 500ms LLM call) can show 2-3x their true duration
- The sum of JS-computed per-iteration durations will consistently exceed `loop_end.duration_ms` (which is server-side `time.monotonic()`)
- Two identical prompts can show different displayed durations depending on WebSocket jitter

**Why it happens:**
The current timing was introduced as a client-side convenience. When per-iteration timing is a featured metric shown prominently in the detail panel and sidebar, the inaccuracy becomes misleading to developers trying to diagnose LLM latency.

**How to avoid:**
Emit `duration_ms` from Python in the `iteration` bus event. In the `_run_agentic_loop` override, track `_iter_start = time.monotonic()` just before each invocation of `super()._run_agentic_loop()` yields an iteration item, then compute `duration_ms = int((time.monotonic() - _iter_start) * 1000)` and include it in the `iteration` event payload. The existing `getIterationDuration()` in `app.js` can then be replaced by `iter.duration_ms` from the server.

Keep the JS `receivedAt`-based method as a fallback for hydrated traces that were recorded before v1.5 (older IDB records will not have `duration_ms`).

**Warning signs:**
- Iteration timing shows large variance even for identical prompts (bus jitter showing through)
- Sum of per-iteration durations substantially exceeds `loop_end.duration_ms`
- No `duration_ms` field on the `iteration` event payload

**Phase to address:** Backend instrumentation phase — add `duration_ms` to the `iteration` event before the frontend uses it.

---

### Pitfall 4: OWL Re-renders the Full `sidebarNodes` Getter on Every Animation Frame If Counter State Is Reactive

**What goes wrong:**
`sidebarNodes` is a computed getter that reads `this.traces` and all nested reactive Maps (`iterations`, `toolCalls`). Any mutation to a reactive value in that chain re-runs `sidebarNodes`. Additionally, `depthLinePaths` reads `sidebarNodes`, so it too recomputes.

If animated token counters are implemented by storing a "current displayed value" in reactive state (e.g., `iter.displayed_tokens = 500`) and a `requestAnimationFrame` loop increments it each frame, every tick triggers:

1. `sidebarNodes` recompute (iterates all traces, all iterations)
2. `depthLinePaths` recompute (geometry for all sidebar rows)
3. OWL patch cycle (DOM diffing for the full sidebar tree)

At 60fps with even a 5-trace session, this creates measurable jank — the sidebar scroll and click response degrade during an active run.

**Why it happens:**
OWL's reactive system tracks *reads*, not write paths. If the animation loop writes `iter.displayed_tokens` and the template (or any getter) reads it during render, OWL re-renders on every write. There is no way to "opt out" of this for a single property without restructuring how state is stored.

**How to avoid:**
Do not store the in-flight animation value in reactive state. Two clean alternatives:

**Option A (recommended): Reactive final value + CSS transition.**
Store the final token count as `iter.tokens_total` in reactive state. This only changes when a new `iteration` event arrives (once per LLM call, not 60x/second). The template renders `iter.tokens_total` and applies a CSS `transition: color 0.2s, opacity 0.2s` or a brief CSS animation class (`@keyframes count-flash`) on the element. No RAF loop, no reactive-state thrashing.

**Option B: Non-reactive JS object + `useRef` DOM write.**
Store `{displayedValue, targetValue, startedAt}` in a plain (non-reactive) JS object keyed by `iterationId`. A single RAF loop runs continuously, interpolating `displayedValue` toward `targetValue` and writing directly to DOM via `useRef`-obtained element refs. The template renders a bare `<span t-ref="'tokenSpan_' + iterationId"></span>` with no OWL binding inside the span — OWL never patches this element because nothing reactive is bound to it.

Do NOT mix these strategies: do not use both `t-esc="iter.tokens_total"` and a RAF that writes `span.textContent`. One owner, always.

**Warning signs:**
- A `displayed_tokens` or `animating_value` field is stored on reactive state (trace or iteration objects)
- `console.time('sidebarNodes')` shows calls at 16ms intervals during animation
- Sidebar scroll lags or feels sticky during active trace execution
- OWL `__owl__.renderCount` increments 60 times per second

**Phase to address:** Frontend counter animation phase — animation strategy must be locked in before any counter code is written.

---

### Pitfall 5: Counter Jitter — Rapid Bus Events Reset the Count-Up Animation to 0

**What goes wrong:**
A multi-iteration trace emits one `iteration` event per LLM API call. If three events arrive within 500ms (a fast agentic loop), a naive animation implementation shows: "start counting from 0 to 500 → new event arrives, reset to 0, count to 1100 → new event arrives, reset to 0, count to 1800." The developer sees a flickering counter that never finishes before resetting.

**Why it happens:**
Naive approach: "on new event, set animation start = 0, target = new total, duration = 600ms." This treats each event as an independent animation. When events arrive faster than the animation completes, the counter perpetually resets.

**How to avoid:**
Track `{displayedValue, targetValue}` in the animation state (non-reactive JS object). On each new event:
- Update `targetValue = newTotal`
- Leave `displayedValue` unchanged (do not reset to 0)
- The RAF loop continues interpolating from `displayedValue` toward `targetValue`

If the new target arrives while the previous tween is still in progress, the tween simply aims higher without resetting. The counter appears to accelerate rather than reset.

Use a short tween duration (200-300ms). For sidebar counters where events arrive every 1-5 seconds, this is fast enough to feel live without being jarring.

**Warning signs:**
- Counter resets to 0 mid-run when a second iteration event arrives
- Counter shows an intermediate wrong value briefly after a multi-iteration run completes
- Animation duration exceeds 500ms (longer than the typical inter-iteration gap for fast agents)

**Phase to address:** Frontend counter animation phase — the `{displayedValue, targetValue}` tracking pattern must be established before any animation duration tuning.

---

### Pitfall 6: IDB `serializeTrace()` / `hydrateTrace()` Asymmetry Causes New Fields to Be Invisible in Hydrated Traces

**What goes wrong:**
`serializeTrace()` in `db.js` is a manual field enumeration — not a spread. Adding new fields to the in-memory iteration object (`tokens_input`, `tokens_output`, `duration_ms`) without also adding them to `serializeTrace()` means those fields are silently dropped when the trace is written to IDB. After a page refresh, the hydrated trace shows 0 tokens and no duration for all iterations, even though the live session showed correct values.

The symmetric failure: updating `serializeTrace()` but not `hydrateTrace()` means the fields are written to IDB but not read back. `hydrateTrace()` constructs the iteration object with an explicit property list — new fields not in that list are silently ignored.

**Why it happens:**
`serializeTrace()` and `hydrateTrace()` are in `db.js` far from the bus event handlers in `app.js`. It is easy to add new iteration fields to `_onIteration` and forget to update the two serialization functions. The failure is silent — no error, just 0/null values after reload.

**How to avoid:**
Treat `serializeTrace()` and `hydrateTrace()` as a contract: every field that must survive a page reload must appear in both. Add a comment block at the top of each function listing the iteration-level fields and marking which were added in which version:

```javascript
// Iteration fields (serializeTrace ↔ hydrateTrace must be symmetric):
// v1.0: iteration_id, trace_id, iteration_index, has_error, receivedAt, is_final, error, messages_sent, raw_response
// v1.5: duration_ms, tokens_input, tokens_output, tokens_cached, tokens_reasoning  ← NEW
```

Update both functions in the same commit. Add a hydration default for each new field:
```javascript
// hydrateTrace() iteration reconstruction:
duration_ms: iter.duration_ms ?? null,       // null = old record, show '—'
tokens_input: iter.tokens_input ?? 0,
tokens_output: iter.tokens_output ?? 0,
tokens_cached: iter.tokens_cached ?? 0,
tokens_reasoning: iter.tokens_reasoning ?? 0,
```

**Warning signs:**
- Tokens and timing display correctly during a live run but show 0/null after a page refresh
- Console shows no error — the failure is purely silent data loss
- `serializeTrace()` and `hydrateTrace()` have a different number of iteration-level fields

**Phase to address:** Frontend IDB/hydration phase — always edit both functions in the same commit, same PR.

---

### Pitfall 7: DB_VERSION Bump Wipes All Stored Traces — Should Not Be Bumped for Additive JSON Fields

**What goes wrong:**
The IDB store in `db.js` uses a single denormalized JSON blob per trace (one record per `trace_id` in the `traces` object store). Adding new fields to this JSON blob does NOT change the IDB object store schema — it only changes the JS object structure. Bumping `DB_VERSION = 2` triggers `onupgradeneeded`, which in Odoo's `IndexedDB` utility recreates stores from scratch. All v1.4 traces are deleted.

**Why it happens:**
Developers see "adding new fields = schema change" and reflexively bump the version. This reasoning applies to SQL schemas (adding a column) but not to IDB key-value stores where the value is opaque JSON. The IDB schema is: "one object store called `traces`, keyed by `trace_id`, value is a JSON blob." That schema does not change when the JSON blob gets new keys.

**How to avoid:**
Do NOT bump `DB_VERSION` for v1.5. Add `tokens_*` and `duration_ms` fields to the JSON blob only. Old IDB records (v1.4) will hydrate with these fields reading as `undefined`, which the `?? 0` / `?? null` defaults in `hydrateTrace()` handle correctly.

Only bump `DB_VERSION` if a new *object store* is added (a new IDB table) or if an existing key-path changes (restructuring the store itself).

**Warning signs:**
- `DB_VERSION` was changed to `2` — all developer trace history is gone after deploy
- The commit that bumps `DB_VERSION` also only adds new JSON properties, not new object stores
- Post-deploy, IDB is empty and all previously stored traces are lost

**Phase to address:** Frontend IDB/hydration phase — confirm `DB_VERSION` is unchanged in code review.

---

### Pitfall 8: Animated Counters Conflict With OWL's `onPatched` DOM Write Timing

**What goes wrong:**
If the animation strategy uses `requestAnimationFrame` to write directly to DOM elements (Option B from Pitfall 4), there is a timing conflict when OWL also patches those elements. The sequence:

1. RAF fires → writes "1,234" to `span.textContent`
2. Bus event arrives → `iter.tokens_total` changes → OWL schedules re-render
3. OWL patches the sidebar → overwrites `span.textContent` with whatever `t-esc` renders

If the RAF callback and the OWL patch cycle share ownership of the same DOM node, the counter flickers between the animation value and the OWL-rendered value.

**Why it happens:**
OWL patches what the template declares. If the template has `<span>{{iter.tokens_display}}</span>` and the RAF also writes to that span, two systems fight for the same node.

**How to avoid:**
Pick one owner per DOM node. The two clean patterns:

- **CSS-only animation (one owner: OWL):** Template renders `iter.tokens_total` via `t-esc`. CSS handles visual effect via `transition` or `@keyframes`. No RAF. No DOM write conflict.
- **RAF-only animation (one owner: RAF):** Template renders a bare `<span t-ref="..."></span>` with no `t-esc` binding. RAF writes `textContent`. OWL's patch cycle touches the span's container (the row div) but has nothing to diff inside the span — it leaves the textContent untouched.

The CSS approach is strongly preferred: it requires zero animation code beyond a CSS rule, survives OWL patch cycles without any special handling, and degrades gracefully (no animation if reduced-motion is set).

**Warning signs:**
- Counter text flickers between the animation value and a static value during rapid bus events
- Template has both `t-esc="iter.tokens_display"` and a RAF that writes to the same element
- `onPatched` fires more often than expected (visible via `console.log` in `onPatched` callback)

**Phase to address:** Frontend counter animation phase — before writing any animation code.

---

### Pitfall 9: Treating Per-Iteration Token Sum as a Running Accumulator Produces Wrong Totals After Hydration

**What goes wrong:**
Naive implementation: `trace.total_tokens` is updated by each `_onIteration` handler by adding the new iteration's tokens to the existing total. This works correctly during a live run. But after a page refresh and IDB hydration, `total_tokens` is not recomputed — it is read directly from the stored value. If `total_tokens` was stored before all iterations had arrived (e.g., written to IDB at `loop_end` time, correctly), it is fine. But if the IDB write happens on each `_onIteration` event (before the trace is complete), the stored `total_tokens` is the value at the time of the last write, which may be a partial sum from mid-run.

More common: `total_tokens` is derived from per-iteration values and never stored separately. After hydration, the detail panel computes the total by summing `iter.tokens_input + iter.tokens_output` across all iterations. This sum is always correct (computed from the stored per-iteration data). The sidebar counter reads `trace.total_tokens` which may be stale or absent.

**Why it happens:**
Mixing "live accumulator" for the sidebar counter with "computed sum" for the detail panel. The two views drift unless both derive from the same source.

**How to avoid:**
Never store `total_tokens` as a separate accumulator on the trace object. Always compute it as a getter from the per-iteration data:

```javascript
// As a helper or getter in app.js:
getTraceTotalTokens(trace) {
    let total = 0;
    for (const iter of trace.iterations.values()) {
        total += (iter.tokens_input || 0) + (iter.tokens_output || 0);
    }
    return total;
}
```

This is always correct: live runs accumulate as iterations arrive; hydrated traces compute from stored per-iteration data. No separate accumulator field, no drift.

For the sidebar display, this getter is called during render — OWL tracks the reactive reads on `trace.iterations` and re-renders when a new iteration is added.

**Warning signs:**
- A `total_tokens` field is stored on the trace object in reactive state
- Sidebar counter shows the correct total during a live run but shows a different (incorrect) total after reload
- Detail panel and sidebar counters disagree on the total

**Phase to address:** Frontend counter data model phase — decide "computed from iterations" before writing any accumulator code.

---

### Pitfall 10: Token Counts for Error Iterations Show NaN or Stale Values

**What goes wrong:**
When an LLM API call fails (UserError or general Exception), the existing `ai_session.py` override emits an error `iteration` event with `raw_response: None` and `error: termination_error`. In v1.5, a token extraction hook that runs on the API response would also return 0 (or None) for error iterations — because there is no response envelope to extract from.

If the JS `getTraceTotalTokens()` helper does `iter.tokens_input + iter.tokens_output` without null guards, `undefined + undefined = NaN`. The sidebar counter then shows "NaN tokens."

For a different failure mode: an iteration that was still running when the page was refreshed (status: "running", `loop_end` never arrived) may have partial token data. After hydration, the "running" state indicator shows alongside a token count that is no longer being incremented.

**Why it happens:**
Error iterations are created in the exception handlers of `_run_agentic_loop` with `raw_response: None`. Token extraction must handle `None` input without raising. JS addition with `undefined` operands produces `NaN` silently.

**How to avoid:**
- Python: the token extraction normalizer must accept `None` as input and return all-zero dict
- Python: emit `tokens: {'input_tokens': 0, 'output_tokens': 0, ...}` on all `iteration` events, including error events
- JS: always use `(iter.tokens_input || 0)` in the sum, never `iter.tokens_input +` without guard
- JS: display `—` (em dash) for iterations where `iter.has_error` is true and tokens are 0, rather than "0 tokens"

**Warning signs:**
- "NaN tokens" appears in the sidebar for any run that ends in an error
- Error iteration rows show "0 tokens" with no visual distinction from a successful iteration with no token data
- Python normalizer raises an exception when `raw_response` is `None`

**Phase to address:** Frontend counter rendering phase — add null guards before any token display logic.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Read tokens from `raw_response` in JS (after service strips envelope) | No Python changes needed | Always returns undefined; counters permanently show 0 for all providers | Never |
| Store animated counter value in reactive `iter.displayed_tokens` | Simple, idiomatic-looking code | Triggers full `sidebarNodes` recompute at 60fps; sidebar jank during any animation | Never |
| Use JS `receivedAt` differences for per-iteration timing | No backend changes | Includes bus latency (50-300ms); inaccurate for fast LLM calls | Acceptable as fallback for v1.4 hydrated traces; never for new live events |
| Bump `DB_VERSION` to 2 "for safety" | Ensures clean state | Destroys all stored developer traces on deploy | Never for additive JSON fields |
| Single token extraction path (only OpenAI or only Google) | Faster to write | Silent zero-tokens for one entire provider family | Only as temporary dev stub, never shipped |
| Accumulate `total_tokens` as a separate trace field | Avoids recomputation | Diverges from per-iteration data after hydration | Never — always compute from iterations |
| Animation duration > 500ms | More dramatic visual effect | Counter still animating when next iteration arrives; jitter visible | Never for agents with > 1 LLM call |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| OpenAI `usage` envelope | Accessing `response.get('usage')` after `get_completions()` returns | Capture inside service before `return response.get('output', [])` |
| Google `usageMetadata` envelope | Accessing `response.get('usageMetadata')` after `get_completions()` returns | Capture inside service before `return [content]` |
| `iteration` bus event | Adding `tokens` inside `raw_response` list | Add as a top-level sibling field: `'tokens': {...}` alongside `raw_response` |
| OWL reactive Map + animation | Storing animation counter in `iter.displayed_tokens` | Store final value only in reactive state; animate via CSS or non-reactive ref |
| IDB `serializeTrace()` | Updating serializer without updating `hydrateTrace()` | Always edit both in the same commit; add version comment |
| `getIterationDuration()` in `app.js` | Continuing to use JS `receivedAt` differences for featured timing metric | Replace with `iter.duration_ms` from server; keep JS method as fallback for old records |
| Error iteration tokens | Python normalizer raising when `raw_response` is `None` | Guard with `if raw_response is None: return zeros` |
| JS token sum | `iter.tokens_input + iter.tokens_output` without null guard | `(iter.tokens_input \|\| 0) + (iter.tokens_output \|\| 0)` always |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| RAF loop touching reactive iteration state | `sidebarNodes` and `depthLinePaths` recompute at 60fps; sidebar jank | Keep animation values in non-reactive plain JS objects | Immediately on first animation tick, even with 3 traces |
| `sidebarNodes` getter recomputing during animation | `depthLinePaths` geometry recalculated 60x/second | Ensure no reactive value read by `sidebarNodes` chain is written by animation loop | Any animation touching reactive state |
| Detail panel re-rendering on each token increment | JSON tree and message history re-render every frame | Token counter and detail panel reactive subtrees must be separate | With any moderately-sized message history (> 5 messages) |
| Computing `getTraceTotalTokens` in every `sidebarNodes` call | Per-trace token sum recomputed on every render | OWL tracks reactive reads; sum over `trace.iterations` is correct and efficient; only called on render | When trace count > 50 with many iterations each |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Showing "0 tokens" until `loop_end` event | Misleads developer — looks like tokens are not being captured | Show per-iteration token counts as each `iteration` event arrives |
| Sidebar counter counting from 0 on each iteration | Developer thinks token count resets per-iteration | Sidebar counter shows running total across all iterations; detail panel shows per-iteration breakdown |
| Raw token numbers without comma separators | "12345" is harder to read than "12,345" in a glance | Use `toLocaleString()` for all counter displays; store raw integers for computation |
| Animation duration > inter-event gap | Counter perpetually resets; developer cannot read the value | Use 200-300ms animation; the "counting up" effect should complete between events |
| "0 tokens" for error iterations without visual distinction | Looks identical to a successful zero-token iteration | Show `—` (em dash) for iterations with `has_error: true`; reserve "0" for successful iterations with genuinely no tokens |
| Showing `duration_ms` from `loop_end` as per-iteration time | Total loop time ≠ LLM call time; tool execution is included | Display `iter.duration_ms` (LLM-only time) separately from `trace.duration_ms` (total loop) |
| Sub-agent token counts rolled into parent trace total | Parent counter shows artificially high tokens; parent vs. child comparison is meaningless | Each trace shows only its own iteration tokens; sub-agent traces show their own count independently |

---

## "Looks Done But Isn't" Checklist

- [ ] **Token extraction (OpenAI):** Counter shows non-zero values when running against an OpenAI model — verify with a real API call, not just a fixture.
- [ ] **Token extraction (Google):** Counter shows non-zero values when running against a Gemini model — confirm `usageMetadata` path is exercised.
- [ ] **Hydrated traces:** Archived (IDB-hydrated) traces show token counts in both sidebar and detail panel — not just live-run traces.
- [ ] **Error iterations:** Iterations with `has_error: true` display `—` or 0 for tokens, not NaN.
- [ ] **`serializeTrace()` symmetry:** Every new field added to `hydrateTrace()` iteration object is also persisted by `serializeTrace()`.
- [ ] **Animation does not trigger `sidebarNodes` recompute:** Verify via `console.time` that `sidebarNodes` is NOT called during animation frames.
- [ ] **`DB_VERSION` unchanged at 1:** Confirmed no store wipe introduced by v1.5 changes.
- [ ] **Per-iteration timing is server-side `duration_ms`:** Sidebar and detail panel show timing from `iter.duration_ms` (server), not from JS `receivedAt` differences.
- [ ] **Trace total tokens:** Sidebar trace row shows sum of all iteration tokens, computed from iteration objects (not a stored accumulator), correct after hydration.
- [ ] **Sub-agent traces isolated:** Child traces (sub-agent runs) show their own token counts; parent trace total does NOT include child tokens.
- [ ] **Fast multi-iteration runs:** Run a 3+ iteration agent; counter never resets to 0 mid-run; it only counts upward.
- [ ] **`null` / `None` input to normalizer:** Python normalizer called with `None` returns all-zero dict without raising.

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Tokens always 0 (wrong extraction point) | MEDIUM | Subclass provider service classes in `ai_debug`; add token capture before envelope strip; re-test both providers |
| DB_VERSION bump wiped IDB history | LOW (data permanently lost) | Revert `DB_VERSION` bump; add comment explaining why it should not change for JSON-only additions |
| Animation causes render cascade | MEDIUM | Remove counter value from reactive state; switch to CSS transition on final reactive value; no backend change |
| `serializeTrace()`/`hydrateTrace()` mismatch | LOW | Add missing fields to whichever function lags; tokens correct on next `loop_end` write |
| Counter jitter (resets on each event) | LOW | Change animation logic to `{displayedValue, targetValue}` pattern; no backend change |
| Bus latency in per-iteration timing | MEDIUM | Add `duration_ms` field to `iteration` event in Python; update JS to prefer it over `receivedAt` diff |
| NaN tokens from error iterations | LOW | Add `|| 0` guards in JS sum; add `if not raw_envelope: return zeros` guard in Python normalizer |
| Trace total wrongly including sub-agent tokens | LOW | Ensure `getTraceTotalTokens()` only sums `trace.iterations.values()` for the trace's own iterations |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Token data stripped before instrumentation sees it | Phase: Backend token extraction | Integration test: emit `iteration` event, assert `tokens.input_tokens > 0` against a real or mocked API call for both providers |
| OpenAI vs. Google field name divergence | Phase: Backend token extraction | Unit test `_ai_debug_normalize_tokens()` with both OpenAI and Google fixture dicts |
| `time.monotonic()` inaccuracy for per-iteration timing | Phase: Backend instrumentation | Assert `iter.duration_ms` is within reasonable range of `loop_end.duration_ms` divided by iteration count |
| OWL render cascade from animated reactive state | Phase: Frontend counter animation | Profile: `sidebarNodes` getter call count must not increase at 60fps during animation |
| Counter jitter on rapid events | Phase: Frontend counter animation | Manual test: 3+ iteration agent; counter never resets to 0 mid-run |
| IDB serialization/hydration asymmetry | Phase: Frontend IDB/hydration | Test: write trace with new fields, clear in-memory store, reload — tokens survive round-trip |
| DB_VERSION accidental bump | Phase: Frontend IDB/hydration | Code review gate: diff confirms `DB_VERSION` still `1` |
| RAF vs. OWL patch conflict | Phase: Frontend counter animation | Visual test: no counter flicker during bus event arrival |
| NaN/null tokens on error iterations | Phase: Frontend counter rendering | Manual test: provoke a loop error; sidebar shows `—` or `0`, not NaN |
| Sub-agent token isolation | Phase: Frontend counter rendering | Manual test: run a sub-agent; parent total equals only parent iterations |

---

## Sources

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_openai.py` — OpenAI `usage` field location and exact field names (lines 86-100); confirms `usage` is logged then only `output` is returned
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_google.py` — Google `usageMetadata` field location and exact field names (lines 75-101); confirms `usageMetadata` is logged then only `[content]` is returned
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` — `_run_agentic_loop` yield structure (lines 422-435); confirms `metadata = response` = post-strip output list, not raw envelope
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — existing instrumentation override; `raw_response: item.get('metadata')` confirmed at line 206; `_debug_ctx` mutable dict pattern at lines 139-146
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — OWL reactive architecture; `sidebarNodes` computed getter chain (lines 628-702); `depthLinePaths` reads `sidebarNodes` (line 551); `getIterationDuration()` using `receivedAt` diffs (lines 729-751); `onPatched` DOM write pattern (lines 342-366)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — IDB schema, `DB_VERSION = 1`, manual field enumeration in `serializeTrace()` (lines 37-89), `hydrateTrace()` symmetric read pattern (lines 24-47)
- OWL reactivity model: reactive read tracking, `onPatched` timing, and RAF/patch interaction — training knowledge (HIGH confidence for the core reactive model, confirmed by the `useState(new Map())` pattern documented in PROJECT.md Key Decisions table)

---
*Pitfalls research for: Odoo AI Debugger v1.5 — Live animated token/time metrics*
*Researched: 2026-02-24*
