# Project Research Summary

**Project:** AI Debugger v1.5 — Live Metrics (animated counters, token normalization, per-iteration timing)
**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched:** 2026-02-24
**Confidence:** HIGH — all findings derived from direct source inspection of the enterprise `ai` module and `ai_debug` custom module

---

## Executive Summary

The v1.5 milestone adds live time and token metrics to an already-shipped, fully functional developer tool. The implementation is bounded and additive: no new npm packages, Python libraries, or Odoo module dependencies are required. The entire feature set is achievable with existing OWL primitives, `time.monotonic()`, and the bus event infrastructure already in place. The critical discovery from research is that **token usage data is stripped before the instrumentation layer can see it** — the `get_completions()` method in each provider service discards the raw HTTP envelope (containing `usage` / `usageMetadata`) and returns only the output list. This is the single highest-risk design constraint and must be addressed first via a thread-local capture pattern at the `AIApiService._request` level, implemented in a new `ai_provider_patch.py` file.

The recommended approach is a clean three-phase delivery: (1) backend token extraction via `ai_provider_patch.py` that monkey-patches `AIApiService._request` at module load time and writes normalized token counts into a thread-local, plus per-iteration timing from `time.monotonic()` in the `_run_agentic_loop` override; (2) frontend reactive store extension — new fields on the iteration object, computed getters for trace totals, and IDB persistence updated symmetrically; (3) display components — sidebar compact metrics line, `IterationDetail` header chips, and `LoopDetail` Metrics Notebook tab. The "counting up" animation in the sidebar requires no `requestAnimationFrame` infrastructure: OWL's reactive re-render, triggered by new iteration events at LLM-call frequency (1–30 seconds), naturally produces the count-up effect.

The primary render performance risk is storing animation counter values in OWL reactive state. If an intermediate `displayed_tokens` field is added to reactive state and a rAF loop increments it, the `sidebarNodes` and `depthLinePaths` computed getters will recompute at 60fps causing sidebar jank. Research resolves this cleanly: store only the final reactive value and let OWL's own render cycle (triggered by new iteration events) provide the visual update. For the live elapsed timer in the detail panel header, use `setRecurringAnimationFrame` from `@web/core/utils/timing` with 1-second granularity and `useRef` + direct DOM mutation — no reactive state updates per frame.

---

## Key Findings

### Recommended Stack

No new stack additions for v1.5. All capabilities are achievable with the existing Odoo OWL application infrastructure.

**Core technologies in use (unchanged from v1.4):**

- **OWL 2 reactive system** (`useState`, `useEffect`, `useRef`) — reactive Map-based store drives all display updates; OWL's read-tracking is the counting-up mechanism for sidebar totals
- **`setRecurringAnimationFrame`** from `@web/core/utils/timing` — already in the Odoo bundle; correct choice for the live elapsed ticker (pauses when tab is backgrounded, unlike `setInterval`)
- **`requestAnimationFrame` + `useRef` direct DOM mutation** — recommended pattern for the live elapsed counter in the detail panel; avoids OWL reactive re-render at 60fps
- **`time.monotonic()`** — Python standard library; already called at loop start in `ai_session.py`; extend to capture per-iteration timing
- **`threading.local()`** — Python standard library; thread-safe side channel for passing token usage from the service layer to the instrumentation layer without touching enterprise files

**What NOT to use:**

- External counter animation libraries (countUp.js, animate.js) — not in Odoo's asset pipeline; 20 lines of rAF code achieves the same result
- `CSS @property` + `counter()` — Firefox support gap (required Firefox 128+); limited to `::after` pseudo-element content; cannot format numbers with inline suffixes or comma separators
- `setInterval` for the elapsed ticker — fires when tab is backgrounded
- Updating `useState` on every rAF frame — triggers OWL re-render at 60fps; sidebar with dozens of nodes causes visible jank
- Extracting token counts in JavaScript from `raw_response` — `raw_response` contains the provider output list, not the HTTP envelope; `usage` and `usageMetadata` are stripped before it is set

### Expected Features

**Must have (table stakes) — all P1:**
- Normalized token extraction from OpenAI and Google provider responses into a common `{input, output, total, cached, reasoning}` schema
- Per-iteration timing instrumentation (`duration_ms` in the `iteration` bus event; Python server-side, not JS `receivedAt` differences)
- Trace-level token totals computed from per-iteration data (never a separate stored accumulator)
- Trace-level total duration (already in `loop_end.duration_ms`; needs surfacing in sidebar row)
- Compact sidebar row counters showing time and tokens inline (`"1.2s · 3,450 tok"` format)
- `IterationDetail` Metrics tab with full per-iteration breakdown (input, output, cached, reasoning tokens + duration)
- `LoopDetail` trace-level totals section (aggregate tokens + total duration)
- Cached-token annotation — OpenAI `input_tokens_details.cached_tokens`, Google `usageMetadata.cachedContentTokenCount`
- Animated counting-up visual effect on sidebar counters as new iterations arrive

**Should have — P2:**
- Reasoning-token annotation — relevant only on o-series and Gemini 2.5+ thinking models; data is free once extraction exists

**Defer (post-v1.5 / v2+):**
- Subagent token roll-up in parent trace total — each trace shows only its own iterations independently; roll-up adds cross-trace accounting complexity with marginal value
- Cost-in-currency display — provider pricing changes constantly; per-tier rates vary; not reliable to maintain in code
- Historical cost aggregation across sessions — requires pricing data, aggregate IDB queries, currency handling
- OpenTelemetry OTLP export with token/duration attributes (listed as EXPT-01 in PROJECT.md v2+ list)

### Architecture Approach

The v1.5 architecture introduces one new Python file (`ai_provider_patch.py`) and makes additive modifications to ten existing files. The data flow is: `AIApiService._request` (patched at module load) writes normalized token dict to `threading.local()` before returning → `ai_session._run_agentic_loop` reads the thread-local after each super() yield and adds `tokens` + `duration_ms` to the `iteration` bus event → `_onIteration` in `app.js` stores two new fields on the iteration object in the reactive Map → `traceTokenTotals()` and `traceTimingTotal()` computed getters recompute when new iterations arrive → OWL re-renders the sidebar row, producing the count-up effect automatically.

**Major components and their v1.5 changes:**

1. **`ai_provider_patch.py` (NEW)** — monkey-patches `AIApiService._request`; normalizes OpenAI `usage` and Google `usageMetadata` into a common `{input, output, total, cached, reasoning}` schema; stores in `threading.local()._last_usage`; imported in `models/__init__.py`
2. **`ai_session.py` (MODIFIED)** — reads thread-local after each super() yield via `_ai_debug_read_usage()`; captures `iter_start = time.monotonic()` before the loop and resets per iteration; emits `tokens` and `duration_ms` on each `iteration` event alongside existing fields
3. **`app.js` reactive store (MODIFIED)** — `_onIteration` stores `tokens` and `duration_ms` on the iteration object; `traceTokenTotals(trace)` and `traceTimingTotal(trace)` new getters provide computed aggregates; `ROW_H_TRACE` constant updated if trace row gains a third line
4. **`app.xml` sidebar (MODIFIED)** — compact metrics line (`"1.2s · 3,450 tok"`) below the existing agent/model meta line on trace rows; driven by getter calls; reactive via OWL re-render
5. **`db.js` `serializeTrace` (MODIFIED)** — adds `tokens` and `duration_ms` to iteration record serialization
6. **`app.js` `hydrateTrace` (MODIFIED — likely no code change)** — new fields pass through via existing spread; verification only
7. **Detail panels (MODIFIED)** — `IterationDetail` gains `formatDuration()` helper and header chips for duration + token summary; `LoopDetail` gains `metricsData` getter and a new "Metrics" Notebook tab with per-iteration table and totals row
8. **`app.scss` (MODIFIED)** — new CSS classes for metrics line, detail chips, and metrics table; all using `$o-*` SCSS variables

**Key architectural pattern:** The counting-up effect requires no animation infrastructure. It is OWL's own reactive re-render triggered by new `iteration` bus events. The sidebar `sidebarNodes` getter reads `trace.iterations` (a reactive Map); when `_onIteration` adds a new entry, OWL re-renders the sidebar tree, which re-calls `traceTokenTotals()`, which returns the higher accumulated total. At LLM iteration frequency (1–30 seconds), this re-render is invisible cost. The only place a rAF-based ticker is needed is the live elapsed time display in the detail panel header while a trace is actively running.

### Critical Pitfalls

1. **Token data is stripped before the instrumentation layer can access it** — `get_completions()` returns only the output list; `usage`/`usageMetadata` are logged and discarded before the return. `raw_response` in the JS store has no token fields. Solution: patch `AIApiService._request` in `ai_provider_patch.py` to capture usage into `threading.local()` before the method returns. Never parse `raw_response` in JS for token data.

2. **OpenAI and Google use structurally different token field names** — OpenAI: `usage.input_tokens` / `usage.output_tokens` with nested `input_tokens_details.cached_tokens`; Google: `usageMetadata.promptTokenCount` / `usageMetadata.candidatesTokenCount` with flat `cachedContentTokenCount`. A normalizer that only handles one provider silently returns zeros for the other with no error. Solution: explicit branches for both envelope keys in a single Python normalizer; unit-test with fixture dicts for both providers before considering extraction done.

3. **Storing animation counter values in OWL reactive state causes render storms** — any value stored in the reactive trace/iteration objects that changes at 60fps triggers `sidebarNodes` and `depthLinePaths` recomputation at 60fps, causing visible sidebar jank. Solution: store only final values in reactive state (changed at LLM-call frequency); animate via CSS class toggle (`classList` + `void el.offsetWidth` reflow), which is the existing `ai-tree-flash` pattern; use `useRef` + direct DOM mutation for the live elapsed timer.

4. **`serializeTrace()` / `hydrateTrace()` asymmetry silently drops new fields** — both functions explicitly enumerate iteration fields; adding new fields to `_onIteration` without updating both serializers means tokens are present during a live run but disappear after page refresh (no error). Solution: always edit both functions in the same commit; add a version comment block listing iteration fields by version number.

5. **Do not bump `DB_VERSION`** — bumping from `1` to `2` triggers `onupgradeneeded` which destroys all stored developer trace history. Adding JSON fields to the existing blob does NOT change the IDB schema. Only bump if a new IDB object store is added or a key-path changes.

---

## Implications for Roadmap

Based on the dependency graph from FEATURES.md and the explicit build order from ARCHITECTURE.md, v1.5 delivers cleanly in three sequential phases. Each phase has a clear verification gate before the next begins.

### Phase 1: Backend Token Extraction and Per-Iteration Timing

**Rationale:** Every display feature depends on receiving non-zero `tokens` and `duration_ms` fields in the `iteration` bus event. Zero token data means no UI feature can be validated. The interception point is the hardest part of the milestone — non-obvious and easy to get wrong in ways that silently produce zeros. This must be verified end-to-end (real API call shows `tokens` field in DevTools) before frontend work begins.

**Delivers:** `iteration` bus events include normalized `tokens: {input, output, total, cached, reasoning}` and `duration_ms` fields. Both OpenAI and Google providers emit non-zero token data on real API calls.

**Implements:**
- New `ai_debug/models/ai_provider_patch.py` with `threading.local()` capture and dual-provider normalization
- `models/__init__.py` import of `ai_provider_patch`
- `ai_session.py` `_run_agentic_loop` modification: `iter_start` timing + `_ai_debug_read_usage()` + new `tokens`/`duration_ms` fields on iteration event

**Avoids:** Pitfall 1 (wrong extraction point), Pitfall 2 (single-provider normalization), Pitfall 3 from PITFALLS.md (JS `receivedAt` inaccuracy for the featured timing metric)

**Verification gate:** Open DevTools Network tab or add `console.log` in `_onIteration`; confirm iteration object has `tokens.total > 0` and `duration_ms > 0` for both an OpenAI and a Google model before proceeding.

**Research flag:** None — exact code for `ai_provider_patch.py`, the normalization function, and the `ai_session.py` changes are all fully specified in ARCHITECTURE.md Integration Points 1-3. No deeper research needed.

---

### Phase 2: Frontend Reactive Store and IDB Persistence

**Rationale:** Connect the new bus event fields to the JS reactive store and IDB. The IDB serialization must happen in this phase — not deferred to Phase 3 — to prevent the hydration mismatch pitfall where the live run looks correct but everything shows null after page refresh (the most common silent failure mode for this type of additive change). Computed getters for trace-level totals are the data contract that Phase 3 display components consume.

**Delivers:** Iteration objects in the reactive Map include `tokens` and `duration_ms`. `traceTokenTotals(trace)` and `traceTimingTotal(trace)` computed getters are available in `app.js`. New fields persist through IDB round-trip: tokens survive `serializeTrace` → IDB write → page refresh → `hydrateTrace`.

**Implements:**
- `app.js` `_onIteration`: store `tokens` + `duration_ms` on iteration object
- `app.js` new getters: `traceTokenTotals()` + `traceTimingTotal()`
- `db.js` `serializeTrace`: add `tokens` and `duration_ms` to iteration records
- `app.js` `hydrateTrace`: verify pass-through via spread (likely no code change)
- Null guards in all JS token arithmetic (`|| 0`); `—` display pattern for error iterations with `has_error: true`

**Avoids:** Pitfall 6 (serialization/hydration asymmetry — both functions updated in same commit), Pitfall 7 (DB_VERSION unchanged), Pitfall 9 (trace total computed from iterations, never stored as accumulator), Pitfall 10 (NaN from error iterations — null guard in sum)

**Verification gate:** Run a trace, confirm live tokens appear; reload page, confirm tokens survive in the hydrated trace across both sidebar and detail view; run a trace that errors, confirm `—` appears rather than NaN.

**Research flag:** None — all integration points specified with exact code in ARCHITECTURE.md Integration Points 3-5 and 9-10.

---

### Phase 3: Display Components, Animation, and Styling

**Rationale:** All display work is unblocked once Phase 2 getters exist. Animation strategy must be locked in before writing any counter code: the sidebar count-up is achieved via OWL reactive re-render (no rAF needed); the live elapsed ticker uses `setRecurringAnimationFrame` + `useRef` DOM mutation; sidebar chips use the existing `classList` + `void el.offsetWidth` CSS animation pattern. These decisions eliminate all render-performance risks identified in PITFALLS.md.

**Delivers:** Sidebar trace rows show `"1.2s · 3,450 tok"` compact metric line counting up with each iteration. `IterationDetail` shows duration + token chips in the header. `LoopDetail` shows a new "Metrics" Notebook tab with per-iteration table and totals row. Live elapsed timer shows in the detail panel header for running traces.

**Implements:**
- `app.xml`: compact metrics line in trace row using `traceTimingTotal` + `traceTokenTotals` getters (reactive re-render = count-up)
- `iter_detail.js` + `iter_detail.xml`: `formatDuration()` helper + duration and token chips in detail header
- `loop_detail.js` + `loop_detail.xml`: `metricsData` getter + Metrics Notebook tab with per-iteration table
- `app.scss`: `.ai-tree-metrics-line`, `.ai-detail-chip`, `.ai-metrics-table` and related classes using `$o-*` SCSS variables only
- `ROW_H_TRACE` constant update in `app.js` if trace row gains a third line (44px → 56px); `depthLinePaths` geometry stays in sync
- Live elapsed ticker in `LoopDetail` using `setRecurringAnimationFrame` at 1-second granularity, started in `onMounted` when `trace.status === "running"`, stopped in `onWillUnmount`
- CSS animation class trigger via `onPatched` + `classList` (same pattern as existing `ai-tree-flash` animation) for sidebar chip visual flash on each new iteration

**Avoids:** Pitfall 4 (reactive state animation — OWL re-render at event frequency, not rAF), Pitfall 5 (counter jitter — no animation resets to 0; values only increase), Pitfall 8 (RAF vs. OWL DOM conflict — one owner per DOM node)

**Research flag:** None — animation strategy is fully specified using verified patterns from existing `onPatched` + `classList` animation and `setRecurringAnimationFrame` usage in Odoo core.

---

### Phase Ordering Rationale

- **Phase 1 must complete before Phase 2** — no token data on the bus means no iteration object field to store, and there is nothing to validate the extraction is correct.
- **Phase 2 must complete before Phase 3** — display components read from the store; building templates before the getters exist produces false null/zero displays that look identical to real failures.
- **IDB persistence belongs in Phase 2, not Phase 3** — deferring `serializeTrace` creates a gap where the live run looks correct but hydration fails silently; this is the most common form of confidence trap for additive field work.
- **Phase 3 components are independent of each other** — sidebar metrics line, `IterationDetail` chips, and `LoopDetail` Metrics tab can be implemented in any order once Phase 2 is complete.
- **No `DB_VERSION` bump across any phase** — the IDB schema does not change for additive JSON fields; confirm in code review that `DB_VERSION` remains `1`.

### Research Flags

All three phases use fully specified, verified patterns. No phase requires a `gsd:research-phase` invocation.

**Standard patterns (skip research-phase):**
- **Phase 1:** Thread-local `_request` patch with normalization, both provider field name mappings, and `_run_agentic_loop` timing modifications are all fully specified with exact code in ARCHITECTURE.md.
- **Phase 2:** All integration points have exact code. Hydration spread behavior confirmed from source. IDB no-bump reasoning verified from `IndexedDB` class `_checkVersion()` implementation.
- **Phase 3:** OWL reactive re-render as count-up mechanism is verified from the reactive Map + getter pattern. `setRecurringAnimationFrame` usage is confirmed from `@web/core/utils/timing` source. CSS animation class toggle is the existing `ai-tree-flash` pattern.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All patterns verified against enterprise + custom source. No new dependencies. Every import path confirmed. |
| Features | HIGH | Token field locations confirmed directly from provider service source files (logger calls show exact field names). Feature scope is bounded by PROJECT.md. |
| Architecture | HIGH | Full data flow traced end-to-end from HTTP response to IDB. All integration points have exact code. Build order dependency graph is explicit with risk ratings per step. |
| Pitfalls | HIGH | All pitfalls grounded in direct source reading. Root causes confirmed (not inferred). Warning signs and recovery steps specified for each pitfall. |

**Overall confidence:** HIGH

### Gaps to Address

- **`ROW_H_TRACE` value for three-line trace rows:** ARCHITECTURE.md suggests 56px (up from 44px). The exact value should be verified visually with the actual rendered three-line layout at implementation time. Easy to adjust; the only concern is keeping it in sync between `app.js` constant and the CSS.

- **`AnimatedCounter` component vs. inline `onPatched` approach:** STACK.md documents both a reusable `AnimatedCounter` OWL component (with `useEffect` + rAF) and an inline `onPatched` CSS class-toggle approach. The inline approach (same pattern as `ai-tree-flash`) is simpler and already proven. Recommend locking in the inline approach at implementation start to avoid over-engineering.

- **Anthropic/Claude provider:** Only OpenAI and Google providers are present in the enterprise `ai` module. The normalization function handles both. If Anthropic is added to the enterprise module in the future, a third branch is needed in `ai_provider_patch.py`. Not a v1.5 concern.

---

## Sources

### Primary (HIGH confidence — direct source inspection at worktree paths)

- `ai_debug/models/ai_session.py` — existing iteration event structure, `raw_response: item.get('metadata')` at line 206, `_debug_ctx` mutable dict pattern, `loop_end` `duration_ms` timing, `started_at = time.monotonic()` variable
- `ai_debug/static/src/app/app.js` — OWL reactive architecture, `sidebarNodes` computed getter chain (lines 628-702), `depthLinePaths` reads `sidebarNodes` (line 551), `getIterationDuration()` using `receivedAt` diffs (lines 729-751), `onPatched` DOM pattern with `classList` and `useRef` (lines 342-366)
- `ai_debug/static/src/app/db.js` — IDB schema, `DB_VERSION = 1`, `serializeTrace` manual field enumeration (lines 37-89), `hydrateTrace` spread pattern (lines 24-47)
- `ai_debug/static/src/app/app.scss` — existing `@keyframes ai-tree-flash` animation pattern (lines 529-537); confirms CSS animation class-toggle approach
- `ai/services/ai_api_service_openai.py` lines 86-94 — OpenAI `usage` field structure (`input_tokens`, `output_tokens`, `input_tokens_details`, `output_tokens_details`); confirms `usage` is logged then only `output` list is returned
- `ai/services/ai_api_service_google.py` lines 75-83 — Google `usageMetadata` field structure (`promptTokenCount`, `candidatesTokenCount`, `cachedContentTokenCount`, `thoughtsTokenCount`); confirms `usageMetadata` is logged then only `[content]` is returned
- `ai/models/ai_session.py` lines 413-435 — `_run_agentic_loop` yield structure confirming `metadata = response = output list` (not raw HTTP envelope)
- `odoo/addons/web/static/src/core/utils/timing.js` lines 101-116 — `setRecurringAnimationFrame` implementation confirmed present in bundle

### Secondary (MEDIUM confidence — training knowledge confirmed by codebase patterns)

- OWL 2 `useEffect` reactive model — training knowledge; HIGH confidence by prevalence in Odoo core OWL components and existing `ai_debug` `app.js` patterns
- `threading.local()` thread-safety for Odoo HTTP workers — training knowledge; HIGH confidence given synchronous request-per-thread Odoo server model

---

*Research completed: 2026-02-24*
*Ready for roadmap: yes*
