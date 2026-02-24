# Phase 18: Display Components and Animation - Research

**Researched:** 2026-02-24
**Domain:** OWL component display, number formatting, CSS animation, live timer
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Metrics formatting:**
- Smart abbreviation for token counts: exact under 1,000; "3.4k" for 1,000+; "1.2M" for 1,000,000+
- Adaptive time units: 850ms, 1.2s, 2m 14s — pick the most natural unit based on magnitude
- Middle dot separator between metrics: "1.2s · 3.4k tok"
- Sidebar metrics line shows input→output split, not just total (e.g. "1.2s · 1.2k→ 2.2k tok")

**Table design (LoopDetail Metrics tab):**
- Column order: # (iteration) | Duration | Input | Output | Cached | Reasoning
- Scrollable table — all rows always rendered, no collapsing
- Totals row: bold text with horizontal rule/top border above (accounting style)
- Zero-value cells display as "–" dash to reduce visual noise (all columns always visible)

**Live timer UX:**
- Timer replaces the duration chip in the detail panel header while trace is running
- Pulsing animation (opacity or subtle scale) on the duration chip while running to indicate live counting
- Instant freeze on completion — pulse stops, final duration displayed, no transition animation
- Sidebar metrics line also updates live as iterations complete, showing partial totals while running

**Visual hierarchy:**
- Sidebar metrics line: secondary text (smaller font, muted color) below the trace name
- Metrics table: compact data-dense styling — tighter padding, reduced row height, optimized for scanning numeric data
- Numbers use normal proportional figures (app's default font), not tabular/monospace

### Claude's Discretion

- IterationDetail header chip colors (monochrome vs color-coded by metric type)
- Exact spacing, padding, and font sizes
- Error state handling
- Pulsing animation exact parameters (timing, opacity range)

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIDE-01 | Trace rows show compact metrics line with total time and total tokens (e.g. `"1.2s · 3,450 tok"`) | `getTraceTotals()` already exists in app.js and is reactive; sidebar trace rows in app.xml have a `.ai-tree-meta-line` span; just add a third line with formatted values |
| DETL-01 | IterationDetail shows duration and token count chips in the header | `iter_detail.xml` header has type badge + name + optional meta spans; add chip elements after the name using `iter.tokens` and `iter.duration_ms` fields that already exist on iteration objects |
| DETL-02 | LoopDetail shows a Metrics tab with per-iteration token/timing table and trace-level totals row | `loop_detail.xml` already uses OWL `Notebook`; add a 4th tab slot; iterate `props.trace.iterations.values()` for rows; call `getTraceTotals()` for totals — but `getTraceTotals` lives in `AiDebugApp`, so LoopDetail needs either a passed-in prop or duplicated computation |
| DETL-03 | Detail panel shows live elapsed timer for running traces (updates at 1-second granularity) | STATE.md decision: use `setRecurringAnimationFrame` + `useRef` DOM mutation (not reactive state) to avoid 60fps OWL re-render; `setRecurringAnimationFrame` is in `@web/core/utils/timing` |
</phase_requirements>

## Summary

Phase 18 is a pure display layer on top of a complete data foundation. Phases 16-17 already deposited token/timing data into the reactive store: every iteration object has `tokens: {input, output, cache_read, cache_write, reasoning, total}` and `duration_ms`. The trace object gets `duration_ms` on loop_end. `getTraceTotals(trace)` in `AiDebugApp` aggregates across iterations reactively and is documented as the Phase 18 entry point.

The work divides into four concrete areas: (1) a formatting utility for tokens and durations, (2) a sidebar metrics line added to trace rows in `app.xml`, (3) header chips and a Metrics tab in `IterationDetail` / `LoopDetail`, and (4) a live elapsed timer using `setRecurringAnimationFrame` + direct DOM mutation. All four use OWL patterns already established in the codebase — no new libraries needed.

The main architectural decision is where the `getTraceTotals` aggregation runs for `LoopDetail`. Since `getTraceTotals` lives in `AiDebugApp` and the `LoopDetail` component only receives `props.trace`, the cleanest path is to pass `getTraceTotals(trace)` as a prop from `app.xml` (already the pattern for `iteration` and `toolCall`), or alternatively move the totals computation into `LoopDetail` itself since it has direct access to `props.trace.iterations`.

**Primary recommendation:** Move aggregation into `LoopDetail.js` (it already has `props.trace` with the full reactive Map), add a `formatTokens()` and `formatDuration()` utility module shared across components, implement the live timer as a `setInterval`-based DOM mutation in `IterationDetail` and/or `LoopDetail` setup (simpler than `setRecurringAnimationFrame` for 1-second granularity), and extend `app.xml` trace rows with a third meta line.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@odoo/owl` | (project version) | Component system, reactive state, `useRef`, lifecycle hooks | This is the entire app's framework — no choice |
| `@web/core/utils/timing` | Odoo core | `setRecurringAnimationFrame` for animation loop | Already available, cited in STATE.md decision |
| `@web/core/notebook/notebook` | Odoo core | Tab container — already in `LoopDetail` and `IterationDetail` | Existing pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `setInterval` / `clearInterval` | Browser native | 1-second tick for live elapsed timer | Simpler than rAF for 1s granularity; STATE.md says rAF+DOM mutation but 1s ticks via `setInterval` is functionally identical and avoids 60fps overhead |
| CSS `@keyframes` + `animation` | CSS | Pulsing animation on running duration chip | Already used extensively in `app.scss` (`.ai-debug-pulse-dot`) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `setInterval` for 1s timer | `setRecurringAnimationFrame` | rAF fires every frame (~16ms); would need manual 1s accumulation; `setInterval(fn, 1000)` is simpler and the project decision cited rAF + DOM mutation — either works, but `setInterval` is the standard choice for 1s granularity |
| Prop-passing `getTraceTotals` result | Compute in `LoopDetail` | Passing a pre-computed prop requires `app.xml` change; computing in `LoopDetail` is self-contained since it has `props.trace` — preferred |

**Installation:** No new packages. All utilities available via Odoo module imports.

## Architecture Patterns

### Recommended Project Structure

No new files strictly required. Recommended additions:

```
ai_debug/static/src/app/
├── format_metrics.js        # NEW: formatTokens(), formatDuration() utilities
├── app.js                   # MODIFY: pass totals to sidebar template (or use getTraceTotals in template)
├── app.xml                  # MODIFY: add metrics line to trace rows
├── app.scss                 # MODIFY: add .ai-tree-metrics-line + chip + table styles
├── detail/
│   ├── iter_detail.js       # MODIFY: add timer setup, formatters
│   ├── iter_detail.xml      # MODIFY: add token/duration chips to header
│   ├── loop_detail.js       # MODIFY: add getIterTotals(), formatters, timer setup
│   └── loop_detail.xml      # MODIFY: add Metrics tab with table
```

### Pattern 1: Shared Formatting Utility

**What:** A standalone JS module with `formatTokens(n)` and `formatDuration(ms)` — pure functions, no OWL dependency.

**When to use:** Called from all three display contexts (sidebar, IterationDetail, LoopDetail).

**Example:**
```javascript
/** @odoo-module **/

/**
 * Format a token count with smart abbreviation.
 * < 1000: exact number
 * >= 1000: one decimal "k" (e.g. 3.4k)
 * >= 1000000: one decimal "M" (e.g. 1.2M)
 */
export function formatTokens(n) {
    if (!n) return "0";
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}k`;
    return String(n);
}

/**
 * Format a duration in milliseconds with adaptive units.
 * < 1000ms: "850ms"
 * < 60000ms: "1.2s"
 * >= 60000ms: "2m 14s"
 */
export function formatDuration(ms) {
    if (!ms && ms !== 0) return "–";
    if (ms < 1000) return `${Math.round(ms)}ms`;
    if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
    const mins = Math.floor(ms / 60000);
    const secs = Math.round((ms % 60000) / 1000);
    return `${mins}m ${secs}s`;
}
```

**Note:** `_formatDuration` already exists in `AiDebugApp` with identical logic (lines 791-797 of app.js). The new module extracts this into a shared utility rather than duplicating it.

### Pattern 2: Sidebar Metrics Line (SIDE-01)

**What:** A third line in the trace row label, below the existing `.ai-tree-meta-line`.

**When to use:** Every trace row in `app.xml`.

**Key insight:** `getTraceTotals(trace)` already exists in `AiDebugApp` and reads through the reactive proxy chain, so OWL will re-render the sidebar whenever a new iteration arrives (SIDE-02 precondition). The sidebar metrics line updates automatically for free.

**Example template fragment:**
```xml
<!-- In app.xml, inside the trace row .ai-tree-label -->
<t t-set="totals" t-value="this.getTraceTotals(node.trace)"/>
<span class="ai-tree-metrics-line"
      t-if="totals.total_tokens > 0 or totals.total_duration_ms > 0">
    <t t-esc="this.formatDuration(totals.total_duration_ms)"/>
    <t t-if="totals.total_tokens > 0">
        &#xB7;
        <t t-esc="this.formatTokens(totals.total_input)"/>&#x2192;<t t-esc="this.formatTokens(totals.total_output)"/> tok
    </t>
</span>
```

**Note:** `formatDuration` and `formatTokens` need to be accessible on the component instance. Since they're pure functions, binding them in `setup()` or defining them as static helpers works fine.

### Pattern 3: IterationDetail Header Chips (DETL-01)

**What:** Token count and duration chips added to the existing `.ai-detail-header` in `iter_detail.xml`.

**Data available:** `props.iteration.tokens` (full token shape) and `props.iteration.duration_ms`.

**Example:**
```xml
<!-- In iter_detail.xml .ai-detail-header -->
<span t-if="props.iteration.duration_ms"
      class="ai-metric-chip ai-metric-chip--duration">
    <t t-esc="this.formatDuration(props.iteration.duration_ms)"/>
</span>
<span t-if="props.iteration.tokens and props.iteration.tokens.total > 0"
      class="ai-metric-chip ai-metric-chip--tokens">
    <t t-esc="this.formatTokens(props.iteration.tokens.total)"/> tok
</span>
```

### Pattern 4: LoopDetail Metrics Tab (DETL-02)

**What:** A new Notebook tab slot `metrics` added to `loop_detail.xml`, containing a table with one row per iteration plus a totals row.

**Key insight:** `LoopDetail` has `props.trace` with the full reactive `iterations` Map. Since OWL tracks reactive reads in the render function, the table re-renders as new iterations arrive — the same reactivity that drives SIDE-01.

**Column order (locked):** # | Duration | Input | Output | Cached | Reasoning

**Zero-value display:** "–" dash. In the template: `t-esc="val > 0 ? this.formatTokens(val) : '–'"`.

**Totals row pattern (accounting style):**
```xml
<tr class="ai-metrics-totals-row">
    <td colspan="2"><strong>Total</strong></td>
    <td><strong t-esc="this.formatTokens(totals.total_input)"/></td>
    <!-- etc. -->
</tr>
```

**Table computation in LoopDetail.js:**
```javascript
get iterationRows() {
    // Returns [{index, duration_ms, tokens}] in display order
    return [...this.props.trace.iterations.values()].map((iter, i) => ({
        index: iter.iteration_index ?? i + 1,
        duration_ms: iter.duration_ms || 0,
        tokens: iter.tokens || { input: 0, output: 0, cache_read: 0, reasoning: 0, total: 0 },
    }));
}

get traceTotals() {
    let total_input = 0, total_output = 0, total_cached = 0,
        total_reasoning = 0, total_duration_ms = 0;
    for (const iter of this.props.trace.iterations.values()) {
        const t = iter.tokens;
        if (t) {
            total_input += t.input || 0;
            total_output += t.output || 0;
            total_cached += t.cache_read || 0;
            total_reasoning += t.reasoning || 0;
        }
        total_duration_ms += iter.duration_ms || 0;
    }
    return { total_input, total_output, total_cached, total_reasoning, total_duration_ms };
}
```

### Pattern 5: Live Elapsed Timer (DETL-03)

**What:** While `props.trace.status === 'running'`, show a counting elapsed time in the `LoopDetail` header that increments every 1 second. Freeze instantly on completion.

**Architectural decision (from STATE.md):** Use `setRecurringAnimationFrame` + `useRef` DOM mutation (not reactive state) to avoid 60fps OWL re-renders. However, for a 1-second update rate a `setInterval(fn, 1000)` + DOM mutation is simpler and achieves identical output. The critical constraint is: do NOT use `useState` for the timer value — that causes OWL re-renders at tick rate.

**Pattern:**
```javascript
// In LoopDetail setup():
this.timerRef = useRef("liveTimer");
this._timerInterval = null;

onMounted(() => {
    if (this.props.trace && this.props.trace.status === 'running') {
        this._startTimer();
    }
});

onWillUnmount(() => {
    this._stopTimer();
});

// onPatched: watch for status transition running→complete
onPatched(() => {
    if (this.props.trace && this.props.trace.status !== 'running') {
        this._stopTimer();
    } else if (this.props.trace && this.props.trace.status === 'running' && !this._timerInterval) {
        this._startTimer();
    }
});

_startTimer() {
    this._timerInterval = setInterval(() => {
        if (!this.timerRef.el) return;
        const elapsed = Date.now() - (this.props.trace.started_at?.getTime() || Date.now());
        this.timerRef.el.textContent = this.formatDuration(elapsed);
    }, 1000);
}

_stopTimer() {
    if (this._timerInterval) {
        clearInterval(this._timerInterval);
        this._timerInterval = null;
    }
}
```

**Template:**
```xml
<!-- In loop_detail.xml .ai-detail-header -->
<span t-if="props.trace.status === 'running'"
      class="ai-metric-chip ai-metric-chip--duration ai-metric-chip--live"
      t-ref="liveTimer">0s</span>
<span t-elif="props.trace.duration_ms"
      class="ai-metric-chip ai-metric-chip--duration">
    <t t-esc="this.formatDuration(props.trace.duration_ms)"/>
</span>
```

**Pulsing animation:** Apply `animation: ai-debug-pulse 1.5s ease-in-out infinite` to `.ai-metric-chip--live`. This reuses the existing `ai-debug-pulse` keyframe already defined in `app.scss`.

### Anti-Patterns to Avoid

- **Reactive state for timer value:** Using `useState({ elapsed: 0 })` and mutating it in `setInterval` causes an OWL re-render every second for the entire `LoopDetail` component, including re-rendering the Notebook and iteration table. DOM mutation via `useRef` + `textContent` is the correct pattern.
- **Calling `getTraceTotals` from `LoopDetail` props:** `getTraceTotals` is on `AiDebugApp`. `LoopDetail` should compute its own aggregation (it has `props.trace.iterations`) rather than require the parent to pass an extra prop.
- **Tabular/monospace font for numbers:** Decision is proportional figures. Do not apply `font-family: monospace` to metric values.
- **Hiding zero columns:** Decision is all columns always visible; zero-value cells show "–".

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Abbreviating large numbers | Custom formatter | `formatTokens()` utility (described above) | Simple pure function; no library needed |
| Adaptive time units | Custom formatter | `formatDuration()` utility (described above) — mirrors existing `_formatDuration` in app.js | Already battle-tested in iteration rows |
| 60fps animation loop | Custom rAF wrapper | `setRecurringAnimationFrame` from `@web/core/utils/timing` (if rAF approach chosen) | Returns a clean stop function; handles `browser.*` abstraction for test environments |
| Pulsing animation | JS-driven opacity tweening | CSS `@keyframes` + `animation` property | GPU-composited; already a pattern in app.scss |

**Key insight:** All the complex data work is done. Phase 18 is display-only — the hardest parts (reactive aggregation, IDB persistence, bus wiring) are already complete. Don't over-engineer.

## Common Pitfalls

### Pitfall 1: Timer leaks on component unmount
**What goes wrong:** `setInterval` (or rAF loop) continues running after `LoopDetail` unmounts (e.g., user clicks a different item in the sidebar). The callback tries to write to `timerRef.el`, which is now null, producing silent errors.
**Why it happens:** Forgetting `onWillUnmount(() => clearInterval(...))`.
**How to avoid:** Always pair `_startTimer()` with `_stopTimer()` in `onWillUnmount`.
**Warning signs:** Console errors about null element access; memory pressure from accumulated intervals.

### Pitfall 2: Timer keeps running after trace completes
**What goes wrong:** The trace's `status` flips to `'success'` (via the bus `loop_end` handler mutating the reactive store), but the timer interval keeps ticking. The chip should freeze showing the final duration.
**Why it happens:** The interval callback only checks `timerRef.el` existence, not the trace status.
**How to avoid:** In `onPatched`, check if `props.trace.status !== 'running'` and call `_stopTimer()`. On `loop_end`, `props.trace.status` changes → OWL patches the component → `onPatched` fires → timer stops.

### Pitfall 3: `started_at` is a Date object (not a number)
**What goes wrong:** `Date.now() - props.trace.started_at` returns `NaN` because `started_at` is a `Date` instance.
**Why it happens:** In `_placeTrace()`, `started_at: new Date()` — it's a Date object. In hydrateTrace, `started_at: plain.started_at ? new Date(plain.started_at) : null`.
**How to avoid:** Use `Date.now() - this.props.trace.started_at.getTime()` or `Date.now() - +this.props.trace.started_at`.

### Pitfall 4: `getTraceTotals` called from LoopDetail without access to `AiDebugApp`
**What goes wrong:** `LoopDetail` calls `this.getTraceTotals(...)` but the method is defined on `AiDebugApp`, not `LoopDetail`.
**Why it happens:** Forgetting that child components don't inherit parent methods.
**How to avoid:** Define a `get traceTotals()` getter directly in `LoopDetail.js` (it has `props.trace` with all iterations).

### Pitfall 5: Metrics line appearing for hydrated traces with no token data
**What goes wrong:** Pre-Phase-17 IDB records have tokens defaulted to `{input:0, output:0, ...}` via `hydrateTrace`. The metrics line would show "0ms · 0→0 tok" for old traces.
**Why it happens:** `hydrateTrace` zero-defaults missing fields.
**How to avoid:** Gate the metrics line on `totals.total_tokens > 0 || totals.total_duration_ms > 0`. Pure zero totals → hide the line entirely.

### Pitfall 6: Token input→output display when only total is available
**What goes wrong:** Backend occasionally emits only `total` with input/output=0 (errored iterations). Showing "0→0 tok" is misleading.
**Why it happens:** `normalizeTokens` sets all fields to 0 when payload is null/absent.
**How to avoid:** Show "Xtok" (total only) when input+output both = 0 but total > 0. Show "X→Y tok" only when both input and output are non-zero.

## Code Examples

### Sidebar metrics line integration

```xml
<!-- In app.xml, inside .ai-tree-trace-row .ai-tree-label -->
<t t-set="totals" t-value="this.getTraceTotals(node.trace)"/>
<span class="ai-tree-metrics-line"
      t-if="totals.total_duration_ms > 0 or totals.total_tokens > 0">
    <t t-esc="this.formatDuration(totals.total_duration_ms)"/>
    <t t-if="totals.total_input > 0 and totals.total_output > 0">
        &#xB7; <t t-esc="this.formatTokens(totals.total_input)"/>&#x2192;<t t-esc="this.formatTokens(totals.total_output)"/> tok
    </t>
    <t t-elif="totals.total_tokens > 0">
        &#xB7; <t t-esc="this.formatTokens(totals.total_tokens)"/> tok
    </t>
</span>
```

### Metrics table (LoopDetail Metrics tab)

```xml
<t t-set-slot="metrics" title="'Metrics'" isVisible="true">
    <div class="ai-metrics-table-wrapper">
        <table class="ai-metrics-table">
            <thead>
                <tr>
                    <th>#</th>
                    <th>Duration</th>
                    <th>Input</th>
                    <th>Output</th>
                    <th>Cached</th>
                    <th>Reasoning</th>
                </tr>
            </thead>
            <tbody>
                <t t-foreach="iterationRows" t-as="row" t-key="row.index">
                    <tr>
                        <td t-esc="row.index"/>
                        <td t-esc="row.duration_ms > 0 ? this.formatDuration(row.duration_ms) : '–'"/>
                        <td t-esc="row.tokens.input > 0 ? this.formatTokens(row.tokens.input) : '–'"/>
                        <td t-esc="row.tokens.output > 0 ? this.formatTokens(row.tokens.output) : '–'"/>
                        <td t-esc="row.tokens.cache_read > 0 ? this.formatTokens(row.tokens.cache_read) : '–'"/>
                        <td t-esc="row.tokens.reasoning > 0 ? this.formatTokens(row.tokens.reasoning) : '–'"/>
                    </tr>
                </t>
            </tbody>
            <tfoot>
                <tr class="ai-metrics-totals-row">
                    <td colspan="2"><strong>Total</strong></td>
                    <td><strong t-esc="traceTotals.total_input > 0 ? this.formatTokens(traceTotals.total_input) : '–'"/></td>
                    <td><strong t-esc="traceTotals.total_output > 0 ? this.formatTokens(traceTotals.total_output) : '–'"/></td>
                    <td><strong t-esc="traceTotals.total_cached > 0 ? this.formatTokens(traceTotals.total_cached) : '–'"/></td>
                    <td><strong t-esc="traceTotals.total_reasoning > 0 ? this.formatTokens(traceTotals.total_reasoning) : '–'"/></td>
                </tr>
            </tfoot>
        </table>
    </div>
</t>
```

### Live timer SCSS

```scss
// Metric chips in detail panel headers
.ai-metric-chip {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 500;
    background-color: $o-gray-200;
    color: $o-gray-700;

    &--live {
        // Pulsing while running — reuses existing keyframe
        animation: ai-debug-pulse 1.5s ease-in-out infinite;
    }
}

// Compact data-dense metrics table
.ai-metrics-table-wrapper {
    overflow-x: auto;
    padding: 12px 16px;
}

.ai-metrics-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;

    th {
        text-align: right;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: $o-gray-600;
        padding: 4px 8px;
        border-bottom: 1px solid $border-color;

        &:first-child { text-align: left; }
    }

    td {
        text-align: right;
        padding: 3px 8px;
        color: $o-gray-700;
        border-bottom: 1px solid $o-gray-100;

        &:first-child { text-align: left; color: $o-gray-500; }
    }
}

.ai-metrics-totals-row td {
    border-top: 2px solid $border-color;
    border-bottom: none;
    padding-top: 6px;
}

// Third metrics line in sidebar trace rows
.ai-tree-metrics-line {
    font-size: 10px;
    color: $o-gray-500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| All metrics in one meta line | Two-line label (query + agent·model) | Phase prior to 18 | Metrics need a 3rd line, not to replace line 2 |
| No token data | `iter.tokens` + `iter.duration_ms` fields | Phase 16-17 | Phase 18 can read data directly |
| `_formatDuration` private to `AiDebugApp` | Extract to shared `format_metrics.js` | Phase 18 | Enables reuse in child components |

## Open Questions

1. **Where exactly does the live timer live?**
   - What we know: DETL-03 says "detail panel header shows live elapsed timer for running traces". The detail panel shows `LoopDetail` when a trace is selected, `IterationDetail` when an iteration is selected.
   - What's unclear: Should the timer appear in `LoopDetail` header only, or also when viewing an iteration of a running trace in `IterationDetail`?
   - Recommendation: Implement in `LoopDetail` header (most natural — trace-level view). For `IterationDetail`, since iterations have their own `duration_ms` from the backend, they don't need a live timer (individual iteration duration comes from the backend event, not client-side timing).

2. **`formatDuration`/`formatTokens` — class methods or module-level?**
   - What we know: OWL templates call `this.methodName(...)`. Module-level functions must be bound or called via a class method wrapper.
   - What's unclear: Adding them to `AiDebugApp`, `LoopDetail`, and `IterationDetail` means three copies OR inheritance.
   - Recommendation: Define as module-level exported functions in `format_metrics.js`. In each component's `setup()`, bind: `this.formatTokens = formatTokens; this.formatDuration = formatDuration;` so templates can call `this.formatTokens(...)`.

## Sources

### Primary (HIGH confidence)

- Direct codebase inspection of `app.js` (lines 791-829) — `_formatDuration`, `getTraceTotals` implementation confirmed
- Direct codebase inspection of `app.xml` — sidebar trace row structure, `.ai-tree-meta-line` location confirmed
- Direct codebase inspection of `iter_detail.xml`, `loop_detail.xml` — existing header structure confirmed
- Direct codebase inspection of `app.scss` — `.ai-debug-pulse-dot` animation, existing keyframes confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/timing.js` (line 101) — `setRecurringAnimationFrame` signature and implementation confirmed
- `STATE.md` accumulated decisions — "live elapsed ticker: use setRecurringAnimationFrame + useRef DOM mutation (not reactive state)" confirmed

### Secondary (MEDIUM confidence)

- OWL `onPatched` lifecycle for detecting trace status changes — pattern observed in `app.js` (existing `onPatched` usage for DOM sync)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — entire stack is the existing codebase; no new libraries
- Architecture: HIGH — data structures fully inspected; API surface confirmed
- Pitfalls: HIGH — root-caused from actual code paths

**Research date:** 2026-02-24
**Valid until:** Stable (no external dependencies changing)
