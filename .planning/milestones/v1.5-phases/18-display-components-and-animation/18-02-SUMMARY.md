---
phase: 18-display-components-and-animation
plan: "02"
subsystem: frontend-display
tags: [metrics, table, timer, owl, scss, loop-detail, animation]
dependency_graph:
  requires: [18-01]
  provides: [loop_detail_metrics_tab, loop_detail_live_timer]
  affects: []
tech_stack:
  added: []
  patterns: [useRef-dom-mutation-timer, setInterval-timer-lifecycle, owl-reactive-getter, accounting-style-table]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/detail/loop_detail.js
    - ai_debug/static/src/app/detail/loop_detail.xml
    - ai_debug/static/src/app/app.scss
decisions:
  - "DOM mutation via useRef + setInterval for timer (not reactive state) — avoids OWL re-rendering entire LoopDetail every second"
  - "traceTotals computed in LoopDetail (not delegated to AiDebugApp.getTraceTotals) — reads reactive proxy chain directly"
  - "Timer chip replaces duration chip while running (not additive) — instant freeze on status change via t-if/t-elif DOM swap"
metrics:
  duration: "2 minutes"
  completed: "2026-02-24"
  tasks_completed: 2
  files_modified: 3
---

# Phase 18 Plan 02: LoopDetail Metrics Tab and Live Elapsed Timer Summary

One-liner: LoopDetail Metrics tab with per-iteration token/timing table and totals row, plus a pulsing live elapsed timer using setInterval DOM mutation to avoid OWL re-render overhead.

## What Was Built

### Metrics Tab (loop_detail.xml + loop_detail.js)

A fourth tab slot `metrics` added to the `Notebook` in LoopDetail, after the existing "Tools Definition" tab.

**iterationRows getter** — reads `props.trace.iterations.values()` through the reactive proxy chain, mapping each iteration to a display row with `index`, `duration_ms`, and `tokens` fields. Zero/absent values default to 0 for safe cell rendering.

**traceTotals getter** — aggregates `total_input`, `total_output`, `total_cached`, `total_reasoning`, `total_duration_ms` across all iterations. Computed locally in LoopDetail (not delegated to AiDebugApp) so OWL re-renders the table as iterations arrive during a live run.

**Table structure:**
- Columns: # | Duration | Input | Output | Cached | Reasoning
- Zero-value cells render as "–" (en-dash `\u2013`)
- `<tfoot>` totals row uses `<strong>` for bold text
- SCSS applies 2px accounting-style top border to totals row

### Live Elapsed Timer (loop_detail.js + loop_detail.xml + app.scss)

**Timer lifecycle:**
- `onMounted` — starts timer if `props.trace.status === 'running'`
- `onWillUnmount` — stops timer, prevents leak on navigation
- `onPatched` — stops timer on `status !== 'running'` transition; restarts if status becomes `running` without an active interval

**Timer update pattern:**
- `useRef("liveTimer")` references the chip DOM element
- `_updateTimerDisplay()` mutates `timerRef.el.textContent` directly (no reactive state)
- `started_at.getTime()` used correctly — `started_at` is a `Date` object, not a numeric timestamp

**Chip display logic (t-if/t-elif):**
- Running → `<span class="ai-metric-chip ai-metric-chip--live" t-ref="liveTimer">0s</span>` (pulsing chip, DOM mutation updates text)
- Completed with duration → `<span class="ai-metric-chip">` with static `formatDuration` output
- Instant freeze: OWL swaps DOM elements on status change, pulse stops naturally

### SCSS (app.scss)

**`ai-metric-chip--live` modifier** added to existing `.ai-metric-chip` block:
```scss
// ai-metric-chip--live: pulsing chip for live elapsed timer
&--live {
    animation: ai-debug-pulse 1.5s ease-in-out infinite;
}
```
Reuses existing `@keyframes ai-debug-pulse` — no new keyframe definition needed.

**Metrics table styles** (`.ai-metrics-table-wrapper`, `.ai-metrics-table`, `.ai-metrics-totals-row`):
- Compact data-dense: 12px font, tight 3px/4px padding
- Numbers right-aligned, row index left-aligned
- Column headers: 10px uppercase with `$o-gray-600`
- Row separators: `1px solid $o-gray-100`
- Totals row: `2px solid $border-color` top, no bottom border
- All values use Odoo SCSS variables, no hardcoded hex

## Decisions Made

1. **DOM mutation timer** — `setInterval` + `timerRef.el.textContent` mutation instead of `useState({ elapsed })`. Avoids OWL re-rendering the full LoopDetail (including Notebook and Metrics table) at 1Hz, which would cause visible jank during live runs.

2. **traceTotals in LoopDetail** — Local getter reading `props.trace.iterations` reactive proxy rather than calling a shared utility. Ensures OWL tracks the reactive dependency and re-renders the totals row as new iterations arrive.

3. **Chip swap pattern** — The live timer chip and static duration chip are separate DOM elements gated by `t-if`/`t-elif`. When the trace completes, OWL replaces the `--live` chip with the static chip, stopping the pulse animation immediately with no CSS transition needed.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `loop_detail.js` contains `iterationRows` getter
- [x] `loop_detail.js` contains `traceTotals` getter
- [x] `loop_detail.js` imports `formatTokens, formatDuration` from `../format_metrics`
- [x] `loop_detail.js` contains `timerRef`, `_startTimer`, `_stopTimer`, `onWillUnmount`
- [x] `loop_detail.xml` contains `ai-metrics-table` table structure
- [x] `loop_detail.xml` contains `t-ref="liveTimer"` chip
- [x] `app.scss` contains `.ai-metrics-table` styles using Odoo variables
- [x] `app.scss` contains `ai-metric-chip--live` modifier comment
- [x] Commit `7c1f15d` exists

## Self-Check: PASSED
