# Architecture Research

**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched:** 2026-02-23 (v1.4 section added); 2026-02-22 (v1.3 and earlier); 2026-02-24 (v1.5)
**Confidence:** HIGH (all findings derived from direct source reading)

---

# v1.5 Live Metrics Architecture

> This section answers the research question for v1.5: How do animated token/timing counters integrate with the existing OWL reactive store + bus.bus streaming architecture? What new components, data flow changes, and integration points are needed?

## The Integration Challenge

The core question is where token data lives and how to get it from the LLM API response into the iteration bus event. This requires tracing the full data flow from HTTP response through the provider service layer to the bus event payload.

**Key discovery from source reading:**

In enterprise `_run_agentic_loop()` (ai_session.py line 413):

```python
response = provider.get_service(self.env, model).get_completions(...)
# response = output of get_completions()
ai_message = provider._format_from_llm(response)
if tool_calls := ai_message.get('tool_calls'):
    yield {'tool_calls': tool_calls, 'metadata': response}  # metadata = OUTPUT LIST
else:
    yield {'final_message': ..., 'metadata': response}      # metadata = OUTPUT LIST
```

`get_completions()` returns:
- OpenAI: `response.get("output", [])` — the output items list. `usage` is logged and DISCARDED.
- Google: `[content]` — the candidates content. `usageMetadata` is logged and DISCARDED.

So `item.get('metadata')` (which becomes `raw_response` in the bus event and JS store) is the provider-formatted output list. **It contains NO token usage data.**

Token data must be captured at the service layer before it is discarded, then threaded to the instrumentation layer.

## System Overview (v1.5)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  PYTHON LAYER                                                             │
│                                                                           │
│  ai_debug/models/ai_provider_patch.py  [NEW FILE]                        │
│  ├── monkey-patches AIApiService._request at module load time            │
│  ├── captures usage/usageMetadata from full HTTP response dict           │
│  ├── normalizes to {input, output, total, cached, reasoning}             │
│  └── stores in threading.local()._last_usage before returning            │
│                                                                           │
│  ai_debug/models/ai_session.py  [MODIFIED]                               │
│  ├── _run_agentic_loop(): captures iter_start = time.monotonic()         │
│  ├── after super() yields: reads threading.local()._last_usage           │
│  ├── computes duration_ms = int((now - iter_start) * 1000)               │
│  └── emits 'iteration' bus event with NEW tokens + duration_ms fields    │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │ bus.bus ('ai_debug' channel)
                       │ separate cursor, immediate NOTIFY
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  BUS EVENT: 'iteration' (EXTENDED schema)                                 │
│                                                                           │
│  {                                                                        │
│    type, trace_id, iteration_id, iteration_index,                         │
│    messages_sent, raw_response, has_tool_calls, is_final,                │
│    tokens: {input, output, total, cached, reasoning},   ← NEW            │
│    duration_ms: int,                                    ← NEW            │
│  }                                                                        │
└──────────────────────┬───────────────────────────────────────────────────┘
                       │ WebSocket (bus_service)
                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  JS REACTIVE STORE (useState(new Map()) in AiDebugApp)  [MODIFIED]       │
│                                                                           │
│  _onIteration handler:                                                    │
│    stores tokens: payload.tokens || null    ← NEW field on iter object   │
│    stores duration_ms: payload.duration_ms || null  ← NEW field          │
│                                                                           │
│  NEW getters on AiDebugApp:                                               │
│    traceTokenTotals(trace) → {input, output, total} | null               │
│    traceTimingTotal(trace) → number (ms)                                  │
│                                                                           │
│  db.js serializeTrace [MODIFIED]:                                         │
│    adds tokens + duration_ms to iteration serialization                   │
│                                                                           │
│  app.js hydrateTrace [MODIFIED]:                                          │
│    tokens + duration_ms pass through via spread (no special handling)     │
└────────────┬───────────────────────────────┬─────────────────────────────┘
             │                               │
             ▼                               ▼
┌───────────────────────────┐   ┌────────────────────────────────────────┐
│  SIDEBAR (app.xml) [MOD]  │   │  DETAIL PANELS                          │
│                           │   │                                         │
│  Trace row:               │   │  LoopDetail [MODIFIED]:                 │
│  NEW compact metrics line │   │    new "Metrics" Notebook tab           │
│  below agent/model line   │   │    per-iteration table: #, dur, tokens  │
│                           │   │    totals row at bottom                 │
│  "1.2s · 3,450 tok"       │   │                                         │
│  counts up as iterations  │   │  IterationDetail [MODIFIED]:            │
│  arrive — animation via   │   │    token + duration chips in header     │
│  OWL reactive re-render   │   │    (static, not animated)               │
└───────────────────────────┘   └────────────────────────────────────────┘
```

## Token Extraction: The Service Layer Gap

### Why raw_response Cannot Be Used for Tokens

`raw_response` in the JS store = `item['metadata']` from Python = return value of `get_completions()`.

OpenAI `get_completions()` return value is `response.get("output", [])` — the output items list. This list contains `[{type: 'message', ...}]` or `[{type: 'function_call', ...}]` entries. No `usage` key anywhere in this list.

Google `get_completions()` return value is `[content]` — a list containing the candidates content dict (`{role: 'model', parts: [...]}`). No `usageMetadata` key.

The usage data is logged at the service layer by the enterprise code but then dropped before the return value is formed.

### The Thread-Local Capture Pattern

The `AIApiService._request()` method is the single point where the full raw HTTP response dict (containing `usage` / `usageMetadata`) is available. Both `AIApiServiceOpenAI` and `AIApiServiceGoogle` inherit it. By patching `_request` at module load time in `ai_provider_patch.py`, we capture usage before `get_completions()` strips it down to the output list.

Thread-locals are safe here: Odoo serves HTTP requests on worker threads and the agentic loop runs synchronously within a single request's thread. There is never concurrent usage from two different agentic loops on the same OS thread.

```python
# ai_debug/models/ai_provider_patch.py
import threading
from odoo.addons.ai.services.ai_api_service import AIApiService

_last_usage = threading.local()

_orig_request = AIApiService._request

def _patched_request(self, method, endpoint, **kwargs):
    result = _orig_request(self, method, endpoint, **kwargs)
    if isinstance(result, dict):
        if 'usage' in result:                    # OpenAI Responses API
            u = result['usage']
            _last_usage.data = {
                'input': u.get('input_tokens', 0),
                'output': u.get('output_tokens', 0),
                'total': u.get('input_tokens', 0) + u.get('output_tokens', 0),
                'cached': u.get('input_tokens_details', {}).get('cached_tokens'),
                'reasoning': u.get('output_tokens_details', {}).get('reasoning_tokens'),
            }
        elif 'usageMetadata' in result:          # Google Gemini API
            um = result['usageMetadata']
            _last_usage.data = {
                'input': um.get('promptTokenCount', 0),
                'output': um.get('candidatesTokenCount', 0),
                'total': um.get('totalTokenCount', 0),
                'cached': um.get('cachedContentTokenCount'),
                'reasoning': um.get('thoughtsTokenCount'),
            }
        else:
            _last_usage.data = None
    else:
        _last_usage.data = None
    return result

AIApiService._request = _patched_request
```

In `ai_session.py` `_run_agentic_loop` override, after `super()` yields an iteration item, read and clear:

```python
from odoo.addons.ai_debug.models.ai_provider_patch import _last_usage

def _ai_debug_read_usage(self):
    """Read and clear the thread-local usage slot. Returns dict or None."""
    try:
        data = getattr(_last_usage, 'data', None)
        _last_usage.data = None   # clear after reading
        return data
    except Exception:
        return None
```

### Timing: Per-Iteration duration_ms

The per-iteration timing measurement must span from the moment the previous `super()` yield returns (i.e., after tool calls finish and messages are appended) to the moment the current yield lands. This captures the real LLM call time plus tool execution overhead — the "iteration wall time" that developers care about.

```python
iter_start = time.monotonic()  # before the super() loop starts

for item in super()._run_agentic_loop(...):
    if 'tool_calls' in item or 'final_message' in item:
        # LLM returned — capture time for this iteration
        duration_ms = int((time.monotonic() - iter_start) * 1000)
        iter_start = time.monotonic()  # reset for next iteration's tool calls
        tokens = self._ai_debug_read_usage()
        # ... existing iteration event payload + new fields ...
        self._ai_debug_bus_send('iteration', {
            ...,
            'tokens': tokens,
            'duration_ms': duration_ms,
        })
    yield item
```

Note: The existing `started_at = time.monotonic()` variable already exists for the total loop duration in `loop_end`. The new `iter_start` is a separate variable that resets per-iteration.

## Integration Points (All Explicit)

### Integration Point 1: `ai_provider_patch.py` (NEW FILE)

**File:** `ai_debug/models/ai_provider_patch.py`
**Dependencies:** `odoo.addons.ai.services.ai_api_service.AIApiService`
**What it does:** Monkey-patches `AIApiService._request` at import time to write token usage into a thread-local before the method returns. Provides `_last_usage` thread-local for reading in `ai_session.py`.
**Risk:** MEDIUM. Monkey-patching is fragile if the enterprise code renames or restructures `_request`. Scoped to one file with a clear comment. Must be imported early enough that it patches before any completions call.
**Registration:** Must add `from . import ai_provider_patch` to `ai_debug/models/__init__.py`.

### Integration Point 2: `ai_session.py` `_run_agentic_loop` (MODIFIED)

**File:** `ai_debug/models/ai_session.py`
**New behavior:**
- Capture `iter_start = time.monotonic()` before the loop body (alongside existing `started_at`).
- After each super() yield that carries an iteration: compute `duration_ms`, read `_last_usage.data`, reset both.
- Add `tokens` and `duration_ms` to the `'iteration'` bus event payload dict.
**Backward compatibility:** The `iteration` event gains two new keys. The JS handler reads them with `|| null` fallbacks. Old JS consumers (hypothetical) ignore unknown keys.

### Integration Point 3: `_onIteration` Handler (MODIFIED)

**File:** `ai_debug/static/src/app/app.js`
**Change:** Two new fields on the iteration object stored in the reactive Map:

```javascript
// Existing fields... PLUS:
tokens: payload.tokens || null,
duration_ms: payload.duration_ms || null,
```

**Risk:** Zero. Additive. Existing code reads named fields it knows about; unknown fields are ignored.

### Integration Point 4: `traceTokenTotals(trace)` Getter (NEW)

**File:** `ai_debug/static/src/app/app.js`
**Purpose:** Compute running token totals across all iterations in a trace. Used by the sidebar trace row to display the animated counter.
**Reactivity:** Reads `trace.iterations` (a `reactive(new Map())`). OWL tracks this read. When `_onIteration` adds a new entry, OWL re-renders the sidebar, which re-calls this getter, which returns a higher total. This IS the counting-up animation — no `requestAnimationFrame` needed.

```javascript
traceTokenTotals(trace) {
    let input = 0, output = 0, total = 0;
    let hasData = false;
    for (const iter of trace.iterations.values()) {
        if (iter.tokens) {
            input += iter.tokens.input || 0;
            output += iter.tokens.output || 0;
            total += iter.tokens.total || 0;
            hasData = true;
        }
    }
    return hasData ? { input, output, total } : null;
}
```

### Integration Point 5: `traceTimingTotal(trace)` Getter (NEW)

**File:** `ai_debug/static/src/app/app.js`
**Purpose:** Sum `duration_ms` across all iterations for display in the sidebar trace row.

```javascript
traceTimingTotal(trace) {
    let ms = 0;
    for (const iter of trace.iterations.values()) {
        if (iter.duration_ms != null) ms += iter.duration_ms;
    }
    return ms;
}
```

### Integration Point 6: Sidebar Trace Row Compact Metrics (MODIFIED)

**File:** `ai_debug/static/src/app/app.xml`
**Where:** Inside the trace row `<span class="ai-tree-label">`, after the existing `ai-tree-meta-line` span.
**Change:** Add a new metrics line that displays running totals. Since `traceTokenTotals` and `traceTimingTotal` are reactive getter calls, the line updates automatically with each new iteration.

```xml
<!-- After the existing agent/model meta line: -->
<t t-set="tMs" t-value="this.traceTimingTotal(node.trace)"/>
<t t-set="tTok" t-value="this.traceTokenTotals(node.trace)"/>
<span t-if="tMs > 0 or tTok" class="ai-tree-metrics-line">
    <t t-if="tMs > 0">
        <span class="ai-tree-metric-time" t-esc="this._formatDuration(tMs)"/>
    </t>
    <t t-if="tTok">
        <span t-if="tMs > 0" class="ai-tree-metric-sep"> · </span>
        <span class="ai-tree-metric-tokens"
              t-esc="tTok.total.toLocaleString() + ' tok'"/>
    </t>
</span>
```

**Row height impact:** The trace row currently contains two lines (query title + meta line). Adding a third line (metrics) increases row height. This affects `depthLineTotalHeight` and `depthLinePaths` which use `ROW_H_TRACE = 44`. Update `ROW_H_TRACE` to accommodate three lines (suggest 56px) and update the corresponding CSS.

### Integration Point 7: `IterationDetail` Header Chips (MODIFIED)

**Files:** `ai_debug/static/src/app/detail/iter_detail.js` + `iter_detail.xml`
**Change:** Show duration and token counts in the detail panel header for the selected iteration.

In `iter_detail.js`, add a `formatDuration(ms)` helper (mirrors `_formatDuration` in `app.js`; a shared utility module is an option but over-engineering for two consumers):

```javascript
formatDuration(ms) {
    if (ms == null) return null;
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const mins = Math.floor(ms / 60000);
    return `${mins}m ${Math.round((ms % 60000) / 1000)}s`;
}
```

In `iter_detail.xml`, add chips in the `ai-detail-header` div:

```xml
<span t-if="props.iteration.duration_ms != null"
      class="ai-detail-chip ai-detail-chip-time"
      t-esc="this.formatDuration(props.iteration.duration_ms)"/>
<span t-if="props.iteration.tokens"
      class="ai-detail-chip ai-detail-chip-tokens">
    <t t-esc="props.iteration.tokens.total.toLocaleString()"/> tok
    <span class="ai-detail-chip-sub">
        (<t t-esc="props.iteration.tokens.input"/> in ·
         <t t-esc="props.iteration.tokens.output"/> out)
    </span>
</span>
```

### Integration Point 8: `LoopDetail` Metrics Tab (MODIFIED)

**Files:** `ai_debug/static/src/app/detail/loop_detail.js` + `loop_detail.xml`
**Change:** Add a "Metrics" slot to the existing Notebook.

In `loop_detail.js`, add two methods:

```javascript
formatDuration(ms) { /* same as IterationDetail helper */ }

get metricsData() {
    const rows = [];
    let totalMs = 0, totalIn = 0, totalOut = 0, totalTok = 0;
    for (const iter of this.props.trace.iterations.values()) {
        rows.push({
            index: iter.iteration_index,
            duration_ms: iter.duration_ms,
            tokens: iter.tokens,
        });
        if (iter.duration_ms) totalMs += iter.duration_ms;
        if (iter.tokens) {
            totalIn += iter.tokens.input;
            totalOut += iter.tokens.output;
            totalTok += iter.tokens.total;
        }
    }
    return { rows, totalMs, totalIn, totalOut, totalTok };
}
```

In `loop_detail.xml`, add the Metrics slot to the Notebook:

```xml
<t t-set-slot="metrics" title="'Metrics'" isVisible="true">
    <div class="ai-detail-section">
        <t t-set="m" t-value="this.metricsData"/>
        <table class="ai-metrics-table">
            <thead>
                <tr>
                    <th>#</th><th>Duration</th>
                    <th>Input</th><th>Output</th><th>Total</th>
                </tr>
            </thead>
            <tbody>
                <t t-foreach="m.rows" t-as="row" t-key="row.index">
                    <tr>
                        <td t-esc="row.index"/>
                        <td t-esc="row.duration_ms != null ? this.formatDuration(row.duration_ms) : '—'"/>
                        <td t-esc="row.tokens ? row.tokens.input.toLocaleString() : '—'"/>
                        <td t-esc="row.tokens ? row.tokens.output.toLocaleString() : '—'"/>
                        <td t-esc="row.tokens ? row.tokens.total.toLocaleString() : '—'"/>
                    </tr>
                </t>
            </tbody>
            <tfoot>
                <tr class="ai-metrics-totals-row">
                    <td>Total</td>
                    <td t-esc="this.formatDuration(m.totalMs)"/>
                    <td t-esc="m.totalIn.toLocaleString()"/>
                    <td t-esc="m.totalOut.toLocaleString()"/>
                    <td t-esc="m.totalTok.toLocaleString()"/>
                </tr>
            </tfoot>
        </table>
    </div>
</t>
```

**Reactivity:** `props.trace.iterations` is a `reactive(new Map())`. The `metricsData` getter reads it via `.values()`. OWL tracks this. When a new iteration arrives for the selected trace, OWL re-renders `LoopDetail` and the table gains a new row. This works even during a live run.

### Integration Point 9: `serializeTrace` in `db.js` (MODIFIED)

**File:** `ai_debug/static/src/app/db.js`
**Change:** Add `tokens` and `duration_ms` to the iteration record in `serializeTrace`:

```javascript
// In the toolCalls map entries:
{
    ...existing fields...,
    tokens: iter.tokens || null,
    duration_ms: iter.duration_ms != null ? iter.duration_ms : null,
}
```

**IDB version bump:** NOT required. Fields are additive nullable. Old stored records that lack these fields will hydrate with `null` via the spread + `|| null` pattern. The `IndexedDB` utility version is unchanged.

### Integration Point 10: `hydrateTrace` in `app.js` (MODIFIED — minimal)

**File:** `ai_debug/static/src/app/app.js`
**Change:** The existing `hydrateTrace` spreads the iteration object: `{...iter, ...reconstructions}`. Since `tokens` and `duration_ms` are included in `serializeTrace` output (step 9), they come through the spread automatically. No special reconstruction needed — both are plain JSON-compatible types (object + number).

Verify the existing spread chain:
```javascript
iterations.set(iterId, {
    ...iter,              // tokens and duration_ms land here from IDB record
    receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null,
    expanded: true,
    toolCalls,
});
```

No code change required if the spread is already in place. This is a VERIFICATION step, not a modification.

### Integration Point 11: `app.scss` (MODIFIED)

**File:** `ai_debug/static/src/app/app.scss`
**Changes needed:**
- `.ai-tree-metrics-line`: smaller font, muted color, monospace, flex layout
- `.ai-tree-metric-time`: timestamp color (use `$o-info` or `$o-gray-600`)
- `.ai-tree-metric-sep`: separator styling
- `.ai-tree-metric-tokens`: token count color (use `$o-gray-600`)
- `.ai-detail-chip`: pill-shaped badge in detail header
- `.ai-detail-chip-time` / `.ai-detail-chip-tokens`: color variants
- `.ai-detail-chip-sub`: smaller sub-text for input/output breakdown
- `.ai-metrics-table`: table styling, borders, font size
- `.ai-metrics-totals-row`: bold totals row with separator

All use `$o-*` SCSS variables only — no hardcoded colors.

Update `ROW_H_TRACE` constant in `app.js` if trace row height changes (currently 44px; three-line rows may need 56px). Must stay in sync with the CSS.

---

## New vs Modified Components

| Component | Status | What changes |
|-----------|--------|--------------|
| `ai_debug/models/ai_provider_patch.py` | **NEW** | Thread-local `_request` patch for usage capture |
| `ai_debug/models/__init__.py` | MODIFIED | Import `ai_provider_patch` |
| `ai_debug/models/ai_session.py` | MODIFIED | Add `iter_start` timing + `_ai_debug_read_usage()` + new `tokens`/`duration_ms` fields on iteration bus event |
| `ai_debug/static/src/app/app.js` | MODIFIED | `_onIteration`: store new fields; add `traceTokenTotals()` + `traceTimingTotal()` getters; update `ROW_H_TRACE` if needed |
| `ai_debug/static/src/app/app.xml` | MODIFIED | Trace row: add compact metrics line |
| `ai_debug/static/src/app/db.js` | MODIFIED | `serializeTrace`: add `tokens`/`duration_ms` to iteration records |
| `ai_debug/static/src/app/detail/iter_detail.js` | MODIFIED | Add `formatDuration()` helper |
| `ai_debug/static/src/app/detail/iter_detail.xml` | MODIFIED | Token + duration chips in header |
| `ai_debug/static/src/app/detail/loop_detail.js` | MODIFIED | Add `metricsData` getter + `formatDuration()` helper |
| `ai_debug/static/src/app/detail/loop_detail.xml` | MODIFIED | New "Metrics" Notebook tab |
| `ai_debug/static/src/app/app.scss` | MODIFIED | New classes for metrics line + table + chips |

**Unchanged files:** `main.js`, `tc_detail.js`, `tc_detail.xml`, `json_tree.js`, `json_tree.xml`, `import_dialog.js`, `debug_menu_button.js`, `app.dark.scss` (may need small additions if metrics need dark-specific color overrides, but likely handled by `$o-*` vars)

---

## Build Order (Dependency-Aware)

| Step | File(s) | What | Dependencies | Risk |
|------|---------|------|-------------|------|
| 1 | `ai_provider_patch.py` | Thread-local `_request` patch + normalization helpers | None | MEDIUM — verify both providers trigger the patch |
| 2 | `models/__init__.py` | Import `ai_provider_patch` | Step 1 | LOW |
| 3 | `ai_session.py` | Add `iter_start` timing + `_ai_debug_read_usage()` + new iteration event fields | Step 1 (needs `_last_usage`) | LOW — additive fields |
| 4 | `app.js` `_onIteration` | Store `tokens` + `duration_ms` on iteration object | Step 3 (server emits them) | LOW |
| 5 | `app.js` new getters | `traceTokenTotals` + `traceTimingTotal` | Step 4 | LOW |
| 6 | `db.js` | Add fields to `serializeTrace` iteration records | Step 4 | LOW |
| 7 | `app.js` `hydrateTrace` | Verify pass-through (likely no code change) | Step 6 | LOW |
| 8 | `app.xml` | Compact metrics line in trace row | Step 5 | LOW |
| 9 | `iter_detail.js` + `iter_detail.xml` | `formatDuration` + chips in header | Step 4 | LOW |
| 10 | `loop_detail.js` + `loop_detail.xml` | `metricsData` + Metrics tab | Step 5 | LOW |
| 11 | `app.scss` | Style all new metric elements | Steps 8–10 | LOW |

**Critical path:** Steps 1 → 3 → 4 → 5. Everything from step 8 onward is display work that can proceed in parallel once step 5 is complete.

**Verification gate after step 3:** Confirm via browser DevTools that iteration bus events include `tokens` and `duration_ms` fields before proceeding to display work. The quickest check: select an iteration in the debugger → Raw Response tab → inspect the bus event payload in network traffic or `console.log` the iteration object in `_onIteration`.

---

## Architectural Patterns

### Pattern 1: Reactive Counting-Up via OWL Re-Render

**What:** Token and timing totals in the sidebar count up automatically with each new iteration because the getter reads from a `reactive(new Map())`. OWL tracks the read and re-renders when the Map mutates. No animation infrastructure needed.

**When to use:** When updates arrive at human-perceptible intervals (LLM iterations: 1–30 seconds). Not suitable for sub-second high-frequency updates.

**Trade-offs:** Numbers jump (not interpolate) on each iteration — this is correct behavior for metrics that genuinely step up once per LLM call. Zero additional complexity vs. the existing `getIterationDuration` pattern which already works this way.

### Pattern 2: Thread-Local Usage Capture

**What:** Monkey-patch `AIApiService._request` to write token data to `threading.local()` before the method returns the full HTTP response dict. Read and clear the slot in `_run_agentic_loop` immediately after `super()` yields. This bridges the service layer (where usage data exists) and the instrumentation layer (where bus events are emitted).

**When to use:** When the target data is available in a lower layer that cannot be modified under the project's constraints (model inheritance only). Thread-locals are safe for synchronous per-request code in Odoo workers.

**Trade-offs:** Monkey-patching is fragile if `_request` is renamed or split. Contained in one clearly commented file. The read-and-clear pattern prevents stale data from leaking between iterations.

### Pattern 3: Additive Nullable Bus Event Schema Extension

**What:** New `tokens` and `duration_ms` fields are added to the existing `iteration` event payload. JS handlers that predated the change ignore unknown keys. IDB records lacking the new fields hydrate correctly via `|| null` fallbacks.

**When to use:** When adding data to existing event types with a single handler. Avoid introducing new event types unless fundamentally different data is being communicated.

---

## Anti-Patterns

### Anti-Pattern 1: AnimatedCounter OWL Component

**What people do:** Create a dedicated OWL component with `useEffect` + `requestAnimationFrame` that lerps from `prevValue` to `nextValue` over ~300ms when its prop changes.

**Why it's wrong:** Adds ~50 lines of animation infrastructure for a use case where OWL's reactive re-render already produces a visible counting-up effect. LLM iterations arrive seconds apart; the numeric jump is perceptible and accurate. Smooth interpolation would show values that were never real.

**Do this instead:** Let OWL re-renders drive the counter update. The `traceTokenTotals(trace)` pattern is sufficient.

### Anti-Pattern 2: Token Extraction from raw_response on the JS Side

**What people do:** Parse `props.iteration.raw_response` in JS to extract token counts.

**Why it's wrong:** `raw_response` is the provider-formatted output list, not the full API response. OpenAI's output list and Google's candidates list contain NO usage data — that information was consumed and discarded by `get_completions()` before the output list was returned.

**Do this instead:** Extract in Python via the `AIApiService._request` patch and include normalized `tokens` dict in the bus event payload.

### Anti-Pattern 3: IDB Version Bump for Additive Fields

**What people do:** Increment `DB_VERSION` in `db.js` and write an `onupgradeneeded` migration when adding new fields to iteration records.

**Why it's wrong:** `tokens` and `duration_ms` are nullable fields that old records simply won't have. The existing `...iter` spread in `hydrateTrace` + `|| null` guards mean old records load correctly with null values. The UI displays "—" for missing data.

**Do this instead:** Use `|| null` fallbacks. No migration needed. No version bump needed.

### Anti-Pattern 4: Per-Iteration IDB Write

**What people do:** Write the trace to IDB on every `iteration` event (not just on `loop_end`).

**Why it's wrong:** The existing write-through pattern (write on `loop_end` only) is intentional — it avoids multiple writes for in-progress traces. The iteration data IS included in the final `writeTrace` call. Writing on every iteration would thrash IDB for long sessions.

**Do this instead:** Continue the existing `_onLoopEnd` write-once pattern. The new `tokens` and `duration_ms` fields on iteration objects will be included in `serializeTrace` automatically when `loop_end` fires.

---

## Normalized Token Schema

| Field | OpenAI `usage` source | Google `usageMetadata` source | Notes |
|-------|----------------------|-------------------------------|-------|
| `input` | `input_tokens` | `promptTokenCount` | Always present |
| `output` | `output_tokens` | `candidatesTokenCount` | Always present |
| `total` | computed `input + output` | `totalTokenCount` | Google provides directly; OpenAI computed |
| `cached` | `input_tokens_details.cached_tokens` | `cachedContentTokenCount` | null if not cached |
| `reasoning` | `output_tokens_details.reasoning_tokens` | `thoughtsTokenCount` | null for non-reasoning models |

The `total` field is computed as `input + output` for OpenAI (to maintain consistency; the API does not provide a separate total). For Google, `totalTokenCount` is used directly as it may include internal tokens not in the sum.

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| Short traces (1–5 iterations) | Current design is optimal |
| Long traces (20–50 iterations) | `traceTokenTotals` iterates all iterations on every sidebar render — ~50 Map lookups is negligible |
| Very long traces (100+ iterations) | Consider memoizing totals on `loop_end` if profiling reveals render cost. Not anticipated for current use. |
| Multiple concurrent sessions | Thread-local is per-OS-thread; Odoo workers are thread-isolated. No contention. |
| New LLM provider (not OpenAI/Google) | Patch detects `usage` vs `usageMetadata` keys. New providers need an additional key check in `_patched_request`. This is a one-line addition. |

---

## Sources

All findings derived from direct source inspection on 2026-02-24:

- `ai_debug/models/ai_session.py` (complete — 379 lines)
- `ai_debug/static/src/app/app.js` (complete — 1005 lines)
- `ai_debug/static/src/app/app.xml` (complete)
- `ai_debug/static/src/app/db.js` (complete)
- `ai_debug/static/src/app/detail/iter_detail.js` + `iter_detail.xml`
- `ai_debug/static/src/app/detail/loop_detail.js` + `loop_detail.xml`
- `enterprise/ai/models/ai_session.py` (`_run_agentic_loop` body — confirms metadata = output list)
- `enterprise/ai/services/ai_api_service_openai.py` (confirms `usage` in full response, `output` returned)
- `enterprise/ai/services/ai_api_service_google.py` (confirms `usageMetadata` in full response, `[content]` returned)
- `enterprise/ai/services/ai_provider_openai.py` (`_format_from_llm` — confirms output list structure)
- `.planning/PROJECT.md` (v1.5 requirements)

---

# v1.4 Subagent Support Architecture

> This section answers the research questions for the v1.4 milestone: Where in ai_session.py instrumentation should parent trace linkage be captured? How should the reactive store be restructured? How should the sidebar components be refactored for flat + nested rendering? What IDB schema changes are needed?

## The Four Integration Questions

### Q1: Where in ai_session.py to Capture Parent Trace Linkage

**The call chain that creates a subagent:**

```
parent ai.session._run_agentic_loop()        [ai_debug override emits new_trace(A)]
  → super()._run_agentic_loop()
      → _handle_tool_calls()
          → tool._ai_tool_run()
              → agent._ai_tool_request_sub_agent()
                  → child ai.session._generate_next_response()
                      → child._run_agentic_loop()   [ai_debug override runs on child]
                              → emits new_trace(B)   [currently no parent linkage]
```

**Key facts from source reading:**

1. `_ai_tool_request_sub_agent` (in `enterprise/ai/models/ai_agent.py` line 1339) creates a new `ai.session` with `parent_session_id` set. The child session object is created via `self.env["ai.session"].sudo().create(...)` — this inherits the calling env's context.

2. The tool name for the subagent tool follows the pattern `make_tool_name(tool)` = `"ai_request_subagent_{id}"`. The upstream `_handle_tool_calls` already uses this pattern: `if "ai_request_subagent" in tool_call.get("name", "")` (line 221 of enterprise ai_session.py).

3. `parent_session_id` is a model field on `ai.session` — it tells us which session is the parent, but NOT which runtime `trace_id` (a UUID generated only at instrumentation time, not stored in DB) or which `tool_call_id` spawned us.

4. The `_debug_ctx` dict (which carries `trace_id`, `iteration_id`, `tool_call_count`) is threaded via `env.context` in the parent. Child sessions have their own `env`, so `_debug_ctx` is not automatically available to them.

**Solution: Thread parent trace linkage through `env.context` before the subagent tool call.**

In `_handle_tool_calls`, scan `tool_calls` before calling `super()`. If any tool call targets the subagent tool, inject parent linkage into `self`'s context using `self.with_context()`. Because `env.context` propagates through ORM recordset creation (`.create()`, `.sudo()`, `.with_company()`), the child session's env will carry the injected keys when `_run_agentic_loop` is called on it.

```python
# In ai_debug/models/ai_session.py — _handle_tool_calls override:
# Before the super() call:
for tc in tool_calls:
    if "ai_request_subagent" in tc.get("name", ""):
        reserved_tc_id = uuid.uuid4().hex
        _debug_ctx['reserved_subagent_tc_id'] = reserved_tc_id
        self = self.with_context(
            _ai_debug_parent_trace_id=_debug_ctx['trace_id'],
            _ai_debug_parent_tool_call_id=reserved_tc_id,
        )
        break  # one subagent tool call per batch in practice

for item in super()._handle_tool_calls(...):  # self already carries context
    ...
```

Then in `_run_agentic_loop` on the child:

```python
parent_trace_id = self.env.context.get('_ai_debug_parent_trace_id')   # None for root
parent_tool_call_id = self.env.context.get('_ai_debug_parent_tool_call_id')  # None for root

self._ai_debug_bus_send('new_trace', {
    'type': 'new_trace',
    'trace_id': trace_id,
    'parent_trace_id': parent_trace_id,        # NEW — null for root
    'parent_tool_call_id': parent_tool_call_id, # NEW — null for root
    ...
})
```

**Why `reserved_tc_id` in `_debug_ctx`:** The `tool_call_id` emitted in the subsequent `tool_call` bus event must match the `parent_tool_call_id` the child reports. Generate it once before `super()`, store it in `_debug_ctx['reserved_subagent_tc_id']`, and use it when emitting the `tool_call` event for the subagent tool. This ensures parent and child refer to the same identifier.

**Compatibility:** The separate-cursor `_ai_debug_bus_send` creates a new env from `self.env.registry.cursor()`. This env does NOT carry context — but bus sends only write to `bus_bus`, they don't need parent linkage. No issue.

**Backward compatibility:** `parent_trace_id` and `parent_tool_call_id` are absent from events emitted by existing non-subagent sessions. The JS handlers default these to `null` when missing.

### Q2: Reactive Store — Flat Map with Parent Pointers (NOT Nested Map)

**Options analyzed:**

**Option A: Nested Map** — child traces stored as nested objects inside the parent trace or inside the spawning tool call.

Rejected because:
- Breaks every existing lookup: `getSelectedTrace`, `getSelectedIteration`, `getSelectedToolCall` all assume flat `traces.get(id)`.
- Breaks `deleteCheckedTraces` (iterates top-level traces only).
- Breaks `exportSelected` / `serializeTrace` / `hydrateTrace`.
- Makes color assignment (by agent name across all traces) require recursive traversal.
- Violates the existing IDB decision: "one denormalized record per trace."

**Option B: Flat Map with parent pointers** — keep `traces` flat. Each subagent trace carries `parent_trace_id` and `parent_tool_call_id`. The display hierarchy is derived at render time from these pointers.

Chosen because:
- Zero changes to any existing lookup functions.
- IDB schema change is additive: two new nullable fields.
- Bulk delete, export, import, color assignment all work unchanged.
- Rendering hierarchy is computed once per render in `sidebarNodes` getter.

**Concrete store changes — only additive:**

```javascript
// _onNewTrace handler adds two nullable fields:
this.traces.set(payload.trace_id, {
    trace_id: payload.trace_id,
    parent_trace_id: payload.parent_trace_id || null,       // NEW
    parent_tool_call_id: payload.parent_tool_call_id || null, // NEW
    agent_name: payload.agent_name || "Unknown Agent",
    agent_color: null,   // NEW — assigned by _assignAgentColor()
    ...existing fields unchanged...
});
// After set: assign color
this._assignAgentColor(payload.agent_name, payload.trace_id);
```

**Color assignment:** Add `this.agentColors = useState(new Map())` as a second reactive Map. The `_assignAgentColor(agentName, traceId)` method:
1. Checks `this.agentColors.has(agentName)`
2. If not, picks next color from a fixed palette array (cycling), writes to `agentColors`, and persists to IDB
3. Sets `trace.agent_color = this.agentColors.get(agentName)` on the just-inserted trace object

The trace object itself holds `agent_color` for direct template access without a second Map lookup in the render path.

### Q3: Sidebar — Computed Display List, Not Template Recursion

**Why not nested `t-foreach`:** OWL templates cannot call themselves recursively. Achieving arbitrary nesting depth with static template nesting requires knowing the maximum depth at write time. The v1.4 spec says "arbitrary nesting depth."

**Why not template-level conditional for subagent nesting:** Would require complex conditional logic (check if a tool call has a child trace, render it inline, check if that child trace's tool calls have grandchildren, etc.) that belongs in JavaScript, not XML.

**Solution: `sidebarNodes` computed getter** that produces a flat, ordered array of display node objects. The template iterates this single array with one `t-foreach`.

```javascript
get sidebarNodes() {
    const nodes = [];
    // Root traces: no parent, newest first
    const rootTraces = [...this.traces.values()]
        .filter(t => !t.parent_trace_id)
        .sort((a, b) => (b.created_ts || 0) - (a.created_ts || 0));

    const renderTrace = (trace, depth) => {
        nodes.push({
            type: 'trace',
            id: trace.trace_id,
            depth,
            data: trace,
        });
        if (!trace.expanded) return;

        // Flat within-trace: iterations and tool calls interleaved
        for (const [iterationId, iter] of trace.iterations) {
            nodes.push({
                type: 'iteration',
                id: iterationId,
                depth: depth + 1,
                data: iter,
                traceId: trace.trace_id,
            });
            // Tool calls immediately after their iteration (always shown when trace expanded)
            for (const [tcId, tc] of iter.toolCalls) {
                nodes.push({
                    type: 'tool_call',
                    id: tcId,
                    depth: depth + 1,
                    data: tc,
                    traceId: trace.trace_id,
                });
                // Subagent traces under this tool call — recursive
                const children = [...this.traces.values()]
                    .filter(t => t.parent_tool_call_id === tcId);
                for (const child of children) {
                    renderTrace(child, depth + 2);
                }
            }
        }
    };

    for (const trace of rootTraces) {
        renderTrace(trace, 0);
    }
    return nodes;
};
```

**OWL reactivity:** This getter reads from `this.traces` (a `useState(new Map())` proxy), `trace.iterations` (a `reactive(new Map())`), and `iter.toolCalls` (a `reactive(new Map())`). OWL's reactive proxy records every `.values()`, `.has()`, `.get()` access during render. When any of those Maps mutate, OWL triggers a re-render which re-evaluates the getter. This is identical to how the current template works — the getter merely moves the traversal from XML to JS.

**Template becomes a single `t-foreach` over `sidebarNodes`:**

```xml
<t t-foreach="sidebarNodes" t-as="node" t-key="node.id">
    <!-- depth-based indentation via CSS custom property -->
    <div t-attf-class="ai-tree-row node-{{node.type}}"
         t-attf-style="padding-left: calc({{node.depth}} * 12px + 8px)"
         t-att-class="{
             'selected': state.selectedId === node.id,
             'ancestor': isAncestorOf(node.id)
         }"
         t-att-data-node-id="node.id">
        <!-- color swatch for trace nodes (agent identity) -->
        <span t-if="node.type === 'trace' and node.data.agent_color"
              class="ai-agent-color-swatch"
              t-attf-style="background: {{node.data.agent_color}}"/>
        <!-- ... existing label/status/chevron rendering switched on node.type ... -->
    </div>
</t>
```

**The `iteration.expanded` toggle is removed.** In v1.4's flat layout, tool calls are always visible when the parent trace is expanded (they are at the same depth level as iterations, not nested under them). The `expanded` flag on iterations becomes unused. Remove the expand chevron from iteration rows and the `toggleExpand(traceId, iterationId)` call path.

**`isAncestorOf(nodeId)` helper:** Replaces the current `selectedTraceId` and `selectedIterationId` getters. Given a `nodeId`, returns true if that node is an ancestor of the currently selected node. Needed to apply the `.ancestor` CSS class for breadcrumb tinting.

### Q4: IDB Schema Changes

**No DB_VERSION bump required** for the trace store — changes are additive nullable fields.

**Changes to `serializeTrace` (add three fields):**

```javascript
export function serializeTrace(trace) {
    return {
        ...existing fields...,
        parent_trace_id: trace.parent_trace_id || null,        // NEW
        parent_tool_call_id: trace.parent_tool_call_id || null, // NEW
        agent_color: trace.agent_color || null,                // NEW
    };
}
```

**Changes to `hydrateTrace` (default new fields from null):**

```javascript
function hydrateTrace(plain) {
    return {
        ...plain,
        parent_trace_id: plain.parent_trace_id || null,        // NEW — old records → null
        parent_tool_call_id: plain.parent_tool_call_id || null, // NEW — old records → null
        agent_color: plain.agent_color || null,                // NEW — old records → null
        ...existing reconstructions (dates, reactive Maps)...
    };
}
```

**New `agent_colors` IDB object store:**

```javascript
const COLORS_STORE = "agent_colors";
idb._tables.add(COLORS_STORE);  // add alongside existing STORE = "traces"

export function writeAgentColor(agentName, color) {
    return idb.write(COLORS_STORE, agentName, {
        name: agentName,
        color,
        assignedAt: Date.now(),
    });
}

export async function loadAllAgentColors() {
    return idb.execute((db) => {
        if (!db || !db.objectStoreNames.contains(COLORS_STORE)) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(COLORS_STORE, "readonly");
            const req = tx.objectStore(COLORS_STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
```

**DB_VERSION caveat:** Adding `idb._tables.add(COLORS_STORE)` before the first `idb.execute()` call will cause the Odoo `IndexedDB` utility to create the store in `onupgradeneeded` only if the DB is being created fresh. On an existing DB at version 1, `onupgradeneeded` does not fire unless the version is bumped. If the `agent_colors` store is not created on existing DBs, increment `DB_VERSION = 2`. The `IndexedDB` utility from `@web/core/utils/indexed_db` handles multi-store upgrades — verify empirically whether `_tables.add()` is sufficient or if a version bump is needed.

**Hydration sequence change in `onWillStart`:**

```javascript
onWillStart(async () => {
    const available = await probeIDB();
    if (!available) { this.state.ephemeralMode = true; return; }

    // NEW: load agent colors before traces (traces reference colors on hydration)
    const storedColors = await loadAllAgentColors();
    for (const { name, color } of storedColors) {
        this.agentColors.set(name, color);
    }

    // Existing: load traces
    const stored = await loadAllTraces();
    stored.sort(...);
    for (const plain of stored) {
        const hydrated = hydrateTrace(plain);
        // Assign color from loaded agentColors Map (or allocate new one)
        if (!hydrated.agent_color && hydrated.agent_name) {
            hydrated.agent_color = this._getOrAssignColor(hydrated.agent_name);
        }
        this.traces.set(plain.trace_id, hydrated);
    }
    ...
});
```

---

## System Overview (v1.4)

```
┌──────────────────────────────────────────────────────────────────────┐
│                        Python (Odoo Backend)                          │
│                                                                        │
│  ai_debug/models/ai_session.py  (_inherit = 'ai.session')            │
│  ┌──────────────────────────────────────────────────────────────┐    │
│  │  _run_agentic_loop()                                          │    │
│  │  ├── reads context: _ai_debug_parent_trace_id [v1.4 NEW]     │    │
│  │  ├── reads context: _ai_debug_parent_tool_call_id [v1.4 NEW] │    │
│  │  └── emits new_trace with parent fields (null for root)       │    │
│  │                                                                │    │
│  │  _handle_tool_calls()                                         │    │
│  │  ├── scans tool_calls for "ai_request_subagent" [v1.4 NEW]   │    │
│  │  ├── self = self.with_context(_ai_debug_parent_*) [v1.4 NEW] │    │
│  │  └── emits tool_call with reserved_tc_id [v1.4 MOD]          │    │
│  └──────────────────────────────────────────────────────────────┘    │
│                    │ bus.bus (separate cursor, immediate NOTIFY)       │
└────────────────────┼─────────────────────────────────────────────────┘
                     │ WebSocket (bus_service)
┌────────────────────▼─────────────────────────────────────────────────┐
│                        JavaScript (OWL App)                           │
│                                                                        │
│  this.traces = useState(new Map())    [flat — key: trace_id]          │
│  this.agentColors = useState(new Map()) [key: agent_name] [v1.4 NEW] │
│                                                                        │
│  _onNewTrace:  traces.set(id, {..., parent_trace_id, agent_color})    │
│  _onIteration: trace.iterations.set(iterId, {...})                    │
│  _onToolCall:  iter.toolCalls.set(tcId, {...})                        │
│  _onLoopEnd:   trace.status = ...; writeTrace(trace)  [IDB]           │
│                                                                        │
│  get sidebarNodes() [v1.4 NEW]                                        │
│  ├── filter root traces (parent_trace_id === null)                    │
│  ├── renderTrace(trace, depth=0) → recursive                          │
│  │   ├── push trace node                                              │
│  │   ├── for each iteration: push iteration node (depth+1)            │
│  │   │   └── for each toolCall: push tool_call node (depth+1)         │
│  │   │       └── for child traces: renderTrace(child, depth+2)        │
│  │   └── return flat ordered array                                    │
│  └── template: t-foreach sidebarNodes → depth-based padding-left     │
│                                                                        │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │  IndexedDB (db.js)                                               │  │
│  │  ├── "traces" store  — serializeTrace adds parent + color fields │  │
│  │  └── "agent_colors" store  — key: agent_name, value: hex color   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## New vs Modified Components

| Component | Status | What changes |
|-----------|--------|--------------|
| `ai_debug/models/ai_session.py` | MODIFIED | `_handle_tool_calls`: detect subagent tool, inject context, use `reserved_subagent_tc_id`; `_run_agentic_loop`: read and emit parent fields |
| `app.js` | MODIFIED | Add `agentColors` Map; add `_assignAgentColor`; add `sidebarNodes` getter; update `_onNewTrace` for parent fields + color; update `onWillStart` to load colors; update `hydrateTrace` |
| `app.xml` | MODIFIED | Replace 3-level nested `t-foreach` with single `t-foreach` over `sidebarNodes`; depth-based `padding-left`; color swatch element; remove `iteration.expanded` toggle |
| `db.js` | MODIFIED | `serializeTrace` adds 3 fields; `hydrateTrace` handles new fields; add `COLORS_STORE`, `writeAgentColor`, `loadAllAgentColors` |
| `app.scss` | MODIFIED | Add `.ai-agent-color-swatch` styling; CSS custom property for depth indentation |

**No new files are required for v1.4.**

---

## Build Order (Dependency-Aware)

```
Step 1 — Python instrumentation (independent starting point)
  Files: ai_debug/models/ai_session.py
  Change: detect subagent tool in _handle_tool_calls, inject context,
          read parent fields in _run_agentic_loop, emit in new_trace
  Validates: bus events for subagent sessions carry parent_trace_id + parent_tool_call_id
  Validates: reserved_tc_id in tool_call event matches parent_tool_call_id in child new_trace

Step 2 — IDB schema (parallel with step 1; depends only on existing db.js)
  Files: db.js
  Change: add parent fields to serializeTrace + hydrateTrace;
          add COLORS_STORE, writeAgentColor, loadAllAgentColors
  Validates: write → read round-trip preserves parent_trace_id, parent_tool_call_id, agent_color
  Validates: agent_colors store is created and persists colors across reload

Step 3 — JS store + color assignment (depends on step 1 for live data, step 2 for IDB)
  Files: app.js
  Change: add agentColors Map; add _assignAgentColor + _getOrAssignColor;
          update _onNewTrace to store parent fields + call color assignment;
          update onWillStart to load colors before traces;
          update hydrateTrace wrapper to default new fields
  Validates: traces.get(id).parent_trace_id is set correctly for subagent traces
  Validates: traces.get(id).agent_color is assigned for each distinct agent_name

Step 4 — sidebarNodes getter (depends on step 3 for parent fields being in store)
  Files: app.js (add sidebarNodes getter)
  Change: implement sidebarNodes with renderTrace recursive helper
  Validates: getter returns correct ordered flat array
  Validates: subagent traces appear after the tool call that spawned them

Step 5 — template refactor (depends on step 4 for sidebarNodes API)
  Files: app.xml
  Change: replace nested t-foreach with t-foreach over sidebarNodes;
          add depth-based padding-left; add color swatch; remove iteration expand toggle
  Validates: sidebar renders root traces at depth 0, iterations/tool-calls at depth 1,
             subagent traces at depth 2, grandchildren at depth 4, etc.
  Validates: color swatch visible for subagent traces; absent for root (or all, depending on design)

Step 6 — SCSS (depends on step 5 for element classes)
  Files: app.scss
  Change: add .ai-agent-color-swatch (small circle, inline-block, fixed size);
          add CSS custom property --ai-depth-indent if using variable indentation
  Validates: visual color accent renders correctly in both light and dark themes
```

Steps 1 and 2 are fully parallel — neither depends on the other.

---

## Anti-Patterns

### Anti-Pattern 1: Nested Map for Subagent Traces

**What people might do:** Store child traces as nested objects inside the parent trace's tool call.

**Why it's wrong:** Breaks `getSelectedTrace(id)`, `deleteCheckedTraces()`, `exportSelected()`, `serializeTrace()`, `hydrateTrace()`, and the import validation — all of which assume `traces` is a flat Map keyed by `trace_id`.

**Do this instead:** Keep `traces` flat. Add `parent_trace_id` and `parent_tool_call_id` pointer fields. Derive display hierarchy in the `sidebarNodes` getter.

### Anti-Pattern 2: Template-Level Recursive Rendering

**What people might do:** Use nested `t-foreach` in app.xml to recursively render subagent traces inside tool call rows.

**Why it's wrong:** OWL templates are static — no template recursion is possible. Static nesting only works for a fixed maximum depth. The v1.4 spec requires arbitrary nesting depth.

**Do this instead:** Compute the ordered flat node list in a JavaScript getter (`sidebarNodes`). The template iterates one flat array. Depth is a field on each node object, applied as CSS `padding-left`.

### Anti-Pattern 3: Context Injection After super() Call

**What people might do:** Try to inject `_ai_debug_parent_trace_id` into context in `_handle_tool_calls` after the `super()` generator has already yielded and the child session has already been created.

**Why it's wrong:** The child session is created during `super()._handle_tool_calls()` execution. By the time the ai_debug wrapper processes `tool_results` from `super()`, the child's `_run_agentic_loop` has already emitted its `new_trace` event — without the parent linkage.

**Do this instead:** Set context on `self` before the `super()` call. Scan `tool_calls` upfront to detect subagent calls and pre-inject the context. This ensures the context is available when the child session is created inside the generator chain.

### Anti-Pattern 4: Using `iteration.expanded` to Gate Tool Call Visibility

**What people might do:** Keep the existing `iteration.expanded` flag to toggle tool call visibility in the new flat layout.

**Why it's wrong:** In the v1.4 flat layout, tool calls appear at the same depth level as iterations. The original three-level hierarchy (trace > iteration > tool calls nested under iteration) is replaced by a two-level flat list within a trace. The `expanded` concept at the iteration level no longer applies.

**Do this instead:** Remove `iteration.expanded`. When a trace is expanded (`trace.expanded = true`), ALL its iterations and tool calls are visible. Only the trace-level expand/collapse remains.

---

## Sources

- Direct source read: `ai_debug/models/ai_session.py` (full instrumentation code — all methods)
- Direct source read: `ai_debug/static/src/app/app.js` (reactive store, bus handlers, hydration, full 627 lines)
- Direct source read: `ai_debug/static/src/app/app.xml` (sidebar template — all 201 lines)
- Direct source read: `ai_debug/static/src/app/db.js` (IDB schema and operations — all 143 lines)
- Direct source read: `enterprise/ai/models/ai_session.py` (upstream agentic loop, `_handle_tool_calls` subagent forward, `parent_session_id` field)
- Direct source read: `enterprise/ai/models/ai_agent.py` (`_ai_tool_request_sub_agent`, `agent_ids` M2M, `_get_tools` includes subagent tool conditionally)
- Direct source read: `enterprise/ai/models/ir_actions_server.py` (`_ai_tool_run`, tool name pattern detection)
- Direct source read: `enterprise/ai/data/ir_actions_server_data.xml` (tool XML id `ir_actions_server_request_sub_agent`, name "AI: Request Sub-Agent", schema: `agent_id` + `prompt`)
- Direct source read: `.planning/PROJECT.md` (v1.4 requirements, all key decisions, constraints)

---

# v1.3 Persistence Architecture

> This section answers the research question for v1.3 milestone: How does IndexedDB persistence integrate with the existing OWL reactive store architecture? What are the integration points, new components, and data flow changes?

## The Core Problem

The existing store is `useState(new Map())` in `AiDebugApp`. OWL's reactive proxy observes `.set()`, `.delete()`, and `.clear()` calls on the Map and triggers re-renders. This reactive Map is the single source of truth — every component reads from it.

IndexedDB is an async key-value store. It cannot be directly observed by OWL. The integration must preserve the existing reactive Map as the runtime source of truth while using IDB as a durable backing store that persists across page refreshes.

The relationship is **write-through caching**: every mutation to the reactive Map also writes to IDB (fire-and-forget async). On page load, IDB is read once to populate the Map before the bus subscription starts.

## System Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                  INSTRUMENTATION LAYER (unchanged)                   │
│  AiSessionDebug → bus.bus → WebSocket → AiDebugApp bus handlers      │
├──────────────────────────────────────────────────────────────────────┤
│                 AiDebugApp (root OWL component)                      │
│                                                                      │
│  this.traces = useState(new Map())   ←── Runtime source of truth     │
│       │                                                              │
│       │  Every mutation (set/delete/clear) triggers:                 │
│       │    1. OWL reactive re-render (existing behavior)             │
│       │    2. IDB write (new — fire-and-forget async)                │
│       ▼                                                              │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │  db.js  (plain ES module, NOT an OWL service)               │     │
│  │  ├── openDB()          — opens/upgrades IDB                 │     │
│  │  ├── loadAllTraces()   — hydration read on startup          │     │
│  │  ├── saveTrace(trace)  — upsert full trace record           │     │
│  │  ├── deleteTrace(id)   — delete one record                  │     │
│  │  └── clearAllTraces()  — wipe entire store                  │     │
│  └──────────────────────┬──────────────────────────────────────┘     │
│                         │                                            │
│                         ▼                                            │
├──────────────────────────────────────────────────────────────────────┤
│                    IndexedDB (browser storage)                       │
│  Database: "ai_debug_traces"                                         │
│  Object store: "traces"                                              │
│  Key: trace_id (string UUID)                                         │
│  Value: plain JS object (serialized trace with nested arrays)        │
└──────────────────────────────────────────────────────────────────────┘
```

## Integration Points

### Integration Point 1: Hydration (page load → reactive Map)

**Location:** `AiDebugApp.setup()` → `onWillStart` callback

**What changes:** Before the first render, the component loads all persisted traces from IDB and populates `this.traces`. `onWillStart` is the correct lifecycle hook — it runs before the first render and supports async/await.

**Sequence:**
```
onWillStart async:
  1. await probeIDB()              → check availability
  2. await loadAllTraces()         → returns plain object array
  3. for each trace: hydrateTrace() → reconstruct reactive Maps
  4. this.traces.set(...)          → populate Map before first render
  5. (bus subscription starts in onMounted, after first render)
```

### Integration Point 2: Write-Through on Bus Events

**Location:** `AiDebugApp._onLoopEnd`

In the actual v1.3 implementation, IDB writes happen on `loop_end` (not on every event). This is a practical optimization: writing the full trace only when it's complete avoids many redundant writes. The `writeTrace` call in `_onLoopEnd` captures the complete trace state.

**Which handlers write to IDB:**

| Handler | IDB action | Reason |
|---------|-----------|--------|
| `_onNewTrace` | No IDB write | Trace incomplete |
| `_onIteration` | No IDB write | Trace incomplete |
| `_onToolCall` | No IDB write | Trace incomplete |
| `_onLoopEnd` | `writeTrace(trace)` | Trace complete — write once |

### Integration Point 3: Delete and Clear

Both IDB calls are fire-and-forget. Delete removes from both reactive Map and IDB. Select-all + bulk delete covers "clear all."

### Integration Point 4: Export and Import

Export serializes from in-memory Map (not IDB). Import hydrates and writes to both Map and IDB. All-or-nothing validation rejects partial imports.

## Serialization: Reactive Maps → Plain Objects

IDB uses structured clone, which cannot handle OWL's reactive Proxy wrapper. Serialize before writing:

```javascript
export function serializeTrace(trace) {
    return {
        trace_id: trace.trace_id,
        // ... scalar fields ...
        iterations: [...trace.iterations.entries()].map(([iterId, iter]) => [
            iterId,
            {
                ...iterScalarFields,
                toolCalls: [...iter.toolCalls.entries()].map(([tcId, tc]) => [tcId, {...tcScalarFields}]),
            },
        ]),
    };
}
```

JSON round-trip in `writeTrace` strips OWL reactive Proxies that IDB's structured clone cannot handle.

Deserialize with `hydrateTrace()` which reconstructs `reactive(new Map())` for all nested Maps — essential so bus events after hydration trigger OWL re-renders.

## Build Order (v1.3)

1. `db.js` — IDB wrapper (no dependencies on other new code)
2. Hydration in `onWillStart` — depends on `db.js`
3. Write-through in `_onLoopEnd` — depends on hydration working
4. Delete (reactive Map + IDB) — depends on write-through
5. Export — depends on nothing new (reads in-memory Map)
6. Import — depends on export (need an export file to test)

## Anti-Patterns (v1.3)

- Storing reactive Maps directly in IDB → DataCloneError
- Subscribing to bus before hydration completes → dropped events for existing traces
- Normalizing IDB schema (separate stores) → over-engineered for a developer tool
- Awaiting IDB writes in bus handlers → unnecessary blocking

---

# v1.2 Theming Architecture

> This section answers the research questions for v1.2 milestone: How does native theming integrate with a standalone OWL app? How is `color_scheme` detected? How does the template serve the correct CSS bundle? How should SCSS be restructured?

## How Odoo's Theming System Works

Odoo's theme system has three layers. Understanding all three is required to integrate correctly.

### Layer 1: User preference storage (enterprise only)

`web_enterprise/models/res_users_settings.py` adds a `color_scheme` field (`Selection: light/dark/system`). `res.users` exposes this as `color_scheme` (via `related`). The preference persists across sessions.

### Layer 2: Server-side color_scheme resolution

`web_enterprise/models/ir_http.py` overrides `color_scheme()`:

```python
def color_scheme(self):
    cookie_scheme = request.httprequest.cookies.get('color_scheme')
    scheme = cookie_scheme if cookie_scheme else super().color_scheme()
    if user := request.env.user:
        if user._is_public():
            return super().color_scheme()           # light for public
        if user_scheme := user.res_users_settings_id.color_scheme:
            if user_scheme in ('light', 'dark'):    # not 'system'
                return user_scheme                  # user explicit choice wins
    return scheme                                   # cookie fallback
```

The base `web/models/ir_http.py` returns `"light"` as the hardcoded default. **'system' is not passed through** — the server cannot know the OS preference, so `color_scheme()` never returns `'system'`, only `'light'` or `'dark'`.

### Layer 3: Cookie synchronization

`web_enterprise/controllers/home.py` sets the cookie on every webclient visit. This means: every time the user visits `/odoo`, Odoo sets (or refreshes) the `color_scheme` cookie to `'light'` or `'dark'`. **The ai_debug controller can read this cookie directly.**

## Data Flow: Theme Detection to CSS Bundle

```
User sets theme in Odoo Settings
    → res.users_settings.color_scheme = 'dark'
    → User visits /odoo → Odoo sets cookie: color_scheme='dark'
    → User navigates to /ai-debug
    → AiDebugController reads cookie → color_scheme='dark' → template context
    → QWeb template: t-if="color_scheme == 'dark'" → loads assets_dark CSS
    → Bootstrap CSS vars resolve to dark values (compiled at build time)
    → app.scss's var(--bs-body-bg) etc. get dark colors automatically
```

## Architecture for v1.2

**`controllers/main.py`:** Read `color_scheme` cookie, pass to template via `webclient_rendering_context()`.

**`views/ai_debug_index.xml`:** Split `t-call-assets` into JS-only (base bundle) + conditional CSS-only (light or dark bundle).

**`__manifest__.py`:** Add `ai_debug.assets_dark` bundle:
```python
'ai_debug.assets_dark': [
    ('include', 'web.dark_mode_variables'),
    ('include', 'ai_debug.assets'),
    'ai_debug/static/src/app/**/*.dark.scss',
],
```

**`static/src/app/app.scss`:** Replace all hardcoded hex colors with `var(--bs-*)` CSS custom properties. See the Catppuccin → Bootstrap mapping in the original full section below.

**`static/src/app/app.dark.scss`** (new): Dark-only overrides for values not expressible via `--bs-*` vars (JSON syntax highlighting colors, status dot colors).

## Anti-Patterns (v1.2)

- Using `prefers-color-scheme` CSS media query — conflicts with server-side Odoo preference
- Including `web.assets_web` instead of `web.assets_backend` — duplicates webclient bootstrap JS
- Duplicating JS in dark bundle — causes `@odoo-module` double-registration errors

---

# v1.1 Base Architecture

> The v1.1 standalone OWL app replaced v1.0's persistent DB models + backend XML views. Key decisions that carry forward unchanged:

- Generator yield passthrough for instrumentation (zero behavioral change to agentic loop)
- Separate cursor bus sends (`registry.cursor()`) for immediate NOTIFY before next iteration
- Full bus payloads (no lazy ORM reads, since there is no DB)
- `useState(new Map())` for trace store (not `reactive()` which uses NO_CALLBACK sentinel)
- Standalone OWL app at `/ai-debug` using `mountComponent` from `@web/env`
- Channel access gated by `ir.websocket` override to internal users only

The root component `AiDebugApp` owns all application state. Children receive props. Selection state is separate from trace data (SIDE-05 prevents selection loss on bus events).

---

## Sources

**v1.5 sources (HIGH confidence — direct source reads, 2026-02-24):**
- `ai_debug/models/ai_session.py` (complete — 379 lines)
- `ai_debug/static/src/app/app.js` (complete — 1005 lines)
- `ai_debug/static/src/app/app.xml` (complete)
- `ai_debug/static/src/app/db.js` (complete)
- `ai_debug/static/src/app/detail/iter_detail.js` + `iter_detail.xml`
- `ai_debug/static/src/app/detail/loop_detail.js` + `loop_detail.xml`
- `enterprise/ai/models/ai_session.py` (complete — confirms `metadata` = output list, not full response)
- `enterprise/ai/services/ai_api_service_openai.py` (confirms `usage` in full response dict, `output` list returned)
- `enterprise/ai/services/ai_api_service_google.py` (confirms `usageMetadata` in full response dict, `[content]` returned)
- `enterprise/ai/services/ai_provider_openai.py` (`_format_from_llm` — confirms output list structure)
- `.planning/PROJECT.md` (v1.5 requirements)

**v1.4 sources (HIGH confidence — direct source reads, 2026-02-23):**
- Same source files above plus `enterprise/ai/models/ai_agent.py` and `ir_actions_server.py`

**v1.3 sources (HIGH confidence — direct source reads, 2026-02-22):**
- Same source files above plus MDN IndexedDB API and OWL 2.x reactive proxy mechanics

**v1.2 sources (HIGH confidence — direct source reads, 2026-02-22):**
- `web_enterprise/models/ir_http.py`, `web_enterprise/controllers/home.py`
- `web/models/ir_http.py`, `web/views/webclient_templates.xml`
- `web/__manifest__.py`, `web_enterprise/__manifest__.py`
- `web/static/lib/bootstrap/scss/_root.scss`
- `web_enterprise/static/src/scss/primary_variables.dark.scss`

---
*Architecture research for: AI Debugger v1.5 — Live metrics (token/timing)*
*Researched: 2026-02-24*

---

# v1.6 Per-DB IndexedDB Isolation Architecture

> This section answers the research question for v1.6: How does per-DB IndexedDB isolation integrate with the existing ai_debug architecture? Where does the DB name need to flow? What components need changes? What is the suggested build order?

## The Integration Challenge

All browser-origin IndexedDB databases share a flat namespace. A user who works against multiple Odoo databases from the same browser will have all traces from all databases mixed into the single `"ai_debug_traces"` IDB — a wrong-DB trace can appear in the sidebar with no indication it belongs to a different server database.

The fix is to suffix the IDB database name with the Odoo database name: `"ai_debug_aaa"` for Odoo DB `aaa`, `"ai_debug_bbb"` for `bbb`. Traces are naturally separated — each IDB is opened only when connected to its corresponding Odoo DB.

**Key discovery from source reading:**

The Odoo database name is already injected into the page by the QWeb template (`ai_debug_index.xml`) via `odoo.__session_info__`:

```xml
var odoo = {
    __session_info__: <t t-out="json.dumps(session_info)"/>,
};
```

`session_info` is produced by `ir.http.session_info()` (`addons/web/models/ir_http.py` line 110):

```python
"db": self.env.cr.dbname,
```

This field is therefore available synchronously at JS startup via `odoo.__session_info__.db`. No network request, no async operation, no controller change needed.

## System Overview (v1.6)

```
Server: controller renders /ai-debug
  └─ webclient_rendering_context() includes session_info["db"] = "aaa"
       │
       ▼
Browser page load:
  odoo.__session_info__ = { "db": "aaa", ... }   (synchronous, inline script)
       │
       ▼
db.js module evaluation (synchronous):
  _rawDb  = odoo.__session_info__.db   →  "aaa"
  _safeDb = "aaa".replace(...)         →  "aaa"
  DB_NAME = "ai_debug_" + "aaa"        →  "ai_debug_aaa"
  idb     = new IndexedDB("ai_debug_aaa", 1)   ← isolated per Odoo DB
       │
       ├── probeIDB()       → opens "ai_debug_aaa"
       ├── loadAllTraces()  → reads from "ai_debug_aaa".traces
       ├── writeTrace()     → writes to "ai_debug_aaa".traces
       └── deleteTraces()   → deletes from "ai_debug_aaa".traces

app.js: unchanged — same export calls, same signatures
```

## Component Boundaries: What Changes vs What Stays

### What Changes

**Only `db.js` changes.** The change is confined to the first four lines of the file where the DB name and `idb` singleton are constructed.

**Current (4 lines at top of db.js):**

```javascript
const DB_NAME = "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";
const idb = new IndexedDB(DB_NAME, DB_VERSION);
```

**After:**

```javascript
const _rawDb = (typeof odoo !== "undefined" && odoo.__session_info__ && odoo.__session_info__.db) || "";
const _safeDb = _rawDb.replace(/[^a-zA-Z0-9_-]/g, "_");
const DB_NAME = _safeDb ? "ai_debug_" + _safeDb : "ai_debug_traces";
const DB_VERSION = 1;
const STORE = "traces";
const idb = new IndexedDB(DB_NAME, DB_VERSION);
```

All exports (`probeIDB`, `writeTrace`, `deleteTrace`, `deleteTraces`, `loadAllTraces`, `serializeTrace`) are unchanged. `app.js` requires no changes.

### What Does Not Change

| Component | File | Status | Reason |
|-----------|------|--------|--------|
| `app.js` | `static/src/app/app.js` | Unchanged | Calls `db.js` exports by name; signatures unchanged |
| `main.js` | `static/src/app/main.js` | Unchanged | Entry point only; no DB logic |
| `controllers/main.py` | `controllers/main.py` | Unchanged | Already calls `webclient_rendering_context()` which includes `"db"` in `session_info` |
| `ai_debug_index.xml` | `views/ai_debug_index.xml` | Unchanged | Already injects `odoo.__session_info__` |
| All OWL detail components | `detail/*.js`, `detail/*.xml` | Unchanged | No IDB awareness |
| Python models | `models/*.py` | Unchanged | No IDB awareness |

## Data Flow: DB Name Resolution

```
[Python] ir.http.session_info()
  ├── "db": env.cr.dbname   → e.g. "aaa"
  └── ... other session fields

[QWeb] ai_debug_index.xml
  └── odoo.__session_info__ = { "db": "aaa", ... }   (inline JSON, synchronous)

[JS module evaluation] db.js (top of file, before any export is called)
  ├── read odoo.__session_info__.db → "aaa"
  ├── sanitize: replace /[^a-zA-Z0-9_-]/g with "_"
  ├── compose: "ai_debug_" + "aaa" → "ai_debug_aaa"
  └── idb = new IndexedDB("ai_debug_aaa", 1)

[JS] app.js onWillStart():
  ├── probeIDB()       → db "ai_debug_aaa" opens (or fails → ephemeral mode)
  └── loadAllTraces()  → getAll from "ai_debug_aaa".traces

[JS] app.js _onLoopEnd():
  └── writeTrace(trace)  → write to "ai_debug_aaa".traces

[JS] app.js _onDeleteSelected():
  └── deleteTraces(ids)  → delete from "ai_debug_aaa".traces
```

## Design Decisions

### Decision 1: Read at Module Evaluation Time, Not Lazily

`odoo.__session_info__` is available synchronously when the JS module is parsed (it is set by an inline `<script>` block that runs before any module bundle). Reading it at module evaluation time means the `idb` singleton is configured before any consumer can call an export — no lazy init, no factory pattern, no ordering dependency.

### Decision 2: Defensive Fallback to `"ai_debug_traces"`

If `odoo.__session_info__` is absent or `db` is empty string, `DB_NAME` falls back to `"ai_debug_traces"` (the pre-v1.6 name). This guards against:
- Unusual rendering paths where session_info is not injected
- Test environments or future controller changes
- The empty-suffix case where `DB_NAME` would otherwise become `"ai_debug_"` (wrong and confusing)

### Decision 3: Sanitize the DB Name

Odoo database names can legally contain hyphens, dots, or Unicode. IDB accepts arbitrary strings as database names, but embedding unsanitized names in a prefix pattern can produce unexpected strings. The regex `[^a-zA-Z0-9_-]` replaces anything outside alphanumeric, underscore, and hyphen with underscore. This is permissive enough to preserve common patterns (`my-db`, `my_db`) while eliminating edge cases.

### Decision 4: No Migration or Data Copy

Old traces stored under `"ai_debug_traces"` are not migrated to the new per-DB name. The milestone goal is isolation going forward. Developers can re-run sessions to regenerate traces. Auto-migration would require reading the old DB name, iterating all records, writing to the new DB, and deleting the old — disproportionate complexity for a developer tool with ephemeral trace data.

## Suggested Build Order

This milestone is a single-file, single-concern change:

1. **Modify `db.js`** — replace the `const DB_NAME` and `const idb` lines at the top of the file with the DB-name-reading pattern (sanitize, compose, fallback). No other changes anywhere.

**Post-change verification:**
- Open `/ai-debug` on Odoo DB `aaa` → DevTools Application panel → IndexedDB shows `ai_debug_aaa`
- Create a trace → confirm it appears in `ai_debug_aaa`.traces
- Open `/ai-debug` on Odoo DB `bbb` → `ai_debug_bbb` is empty; `aaa` trace does not appear
- Confirm all existing operations still work: hydration on page refresh, write on loop end, delete on bulk delete, ephemeral mode fallback

## Anti-Patterns

### Anti-Pattern 1: Passing DB Name as Function Argument

**What people do:** Change all `db.js` export signatures to `probeIDB(dbName)`, `writeTrace(trace, dbName)`, etc., and have `app.js` read `session_info` and thread the name through every call.

**Why it's wrong:** Seven call sites in `app.js` all need to change. `db.js` already owns IDB configuration — adding a parameter just moves the config responsibility to the caller without benefit. The `idb` singleton approach is architecturally cleaner.

**Do this instead:** Module-level resolution in `db.js`. `app.js` has no reason to know the IDB name.

### Anti-Pattern 2: Lazy Initialization with Async Factory

**What people do:** Export an `initDb(name)` function from `db.js`, call it from `app.js` `onWillStart`, and gate other exports on initialization.

**Why it's wrong:** `odoo.__session_info__` is synchronously available at parse time. Adding async initialization creates a race condition risk and forces every export to check initialization state. Unnecessary complexity.

**Do this instead:** Synchronous read at module evaluation time.

### Anti-Pattern 3: Reading Session Info in `app.js` and Injecting into `db.js`

**What people do:** `app.js` reads `odoo.__session_info__.db` and calls an exported `configureDb(name)` before other operations.

**Why it's wrong:** Fragile ordering dependency. Any code path that calls `probeIDB()` or any other export before `configureDb()` runs (e.g., from another module or test) operates against the wrong IDB name. Module-level init eliminates this class of bug.

**Do this instead:** Read synchronously at module initialization with no explicit init call required.

## Sources

**v1.6 sources (HIGH confidence — direct source reads, 2026-02-26):**
- `ai_debug/static/src/app/db.js` (complete — confirmed hardcoded `"ai_debug_traces"` on line 4)
- `ai_debug/static/src/app/app.js` (complete — all `db.js` call sites confirmed; no `session_info` access)
- `ai_debug/static/src/app/main.js` (complete — no DB logic)
- `ai_debug/views/ai_debug_index.xml` (complete — `odoo.__session_info__` injection confirmed)
- `ai_debug/controllers/main.py` (complete — `webclient_rendering_context()` call confirmed)
- `odoo/addons/web/models/ir_http.py` line 110 — `"db": self.env.cr.dbname` confirmed in `session_info`
- `.planning/PROJECT.md` — v1.6 milestone goal and constraints

---
*Architecture research for: AI Debugger v1.6 — Per-DB IndexedDB isolation*
*Researched: 2026-02-26*
