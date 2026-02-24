---
phase: 18-display-components-and-animation
plan: "01"
subsystem: frontend-display
tags: [metrics, formatting, sidebar, iteration-detail, owl, scss]
dependency_graph:
  requires: [17-01]
  provides: [format_metrics_utilities, sidebar_metrics_line, iter_detail_chips]
  affects: [18-02]
tech_stack:
  added: [format_metrics.js]
  patterns: [shared-formatter-module, owl-template-binding, scss-variable-chip]
key_files:
  created:
    - ai_debug/static/src/app/format_metrics.js
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
    - ai_debug/static/src/app/detail/iter_detail.js
    - ai_debug/static/src/app/detail/iter_detail.xml
decisions:
  - "Keep existing _formatDuration in AiDebugApp for getIterationDuration callers; bind new formatDuration separately for template use"
  - "Monochrome ai-metric-chip (gray-200/gray-700) — no color-coding by metric type for clean developer-tool aesthetic"
  - "ai-metric-chip placed as reusable utility class for Plan 02 LoopDetail and live timer chip"
metrics:
  duration: "2 minutes"
  completed: "2026-02-24"
  tasks_completed: 2
  files_modified: 6
---

# Phase 18 Plan 01: Display Components and Animation — Shared Formatting Utilities and Metrics Line Summary

One-liner: Shared formatTokens/formatDuration utilities with sidebar trace metrics line and IterationDetail header chips using smart abbreviation and adaptive time units.

## What Was Built

### format_metrics.js (new)

Pure utility module with two exported functions:

- `formatTokens(n)` — smart abbreviation: exact < 1000, `Xk` >= 1000, `XM` >= 1M; falsy returns "0"
- `formatDuration(ms)` — adaptive units: en-dash for null, `Xms` < 1s, `X.Xs` < 60s, `Xm Xs` >= 60s

Both functions are stateless and importable by any component.

### Sidebar Metrics Line (app.xml + app.scss)

After the existing `.ai-tree-meta-line` (agent · model) in trace rows, a new `.ai-tree-metrics-line` shows:
- Duration from `getTraceTotals().total_duration_ms` via `formatDuration`
- Token split `input→output tok` when both totals are nonzero
- Token total-only fallback when input+output are zero but total > 0
- Hidden entirely when both `total_duration_ms` and `total_tokens` are 0 (pre-Phase-17 records)

SCSS: `display: block`, 10px font, `$o-gray-500`, ellipsis overflow.

### IterationDetail Header Chips (iter_detail.xml + iter_detail.js + app.scss)

Two `.ai-metric-chip` spans added after the Error meta span:
- Duration chip: shown when `iteration.duration_ms` is truthy
- Token chip: shown when `iteration.tokens.total > 0`

SCSS `.ai-metric-chip`: inline-flex pill, `$o-gray-200` background, `$o-gray-700` text, 11px/500 font, `border-radius: 10px`. No hardcoded hex values. Reusable by LoopDetail and live timer in Plan 02.

## Decisions Made

1. **Kept `_formatDuration` in AiDebugApp** — existing callers (`getIterationDuration`) remain unchanged; new `formatDuration` is bound separately as `this.formatDuration` for template use.
2. **Monochrome chips** — single neutral color (gray-200/700), not color-coded by metric type, matching developer-tool aesthetic.
3. **`ai-metric-chip` as reusable class** — defined once in `app.scss`, designed for Plan 02 to add `--live` modifier variant.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

- [x] `ai_debug/static/src/app/format_metrics.js` created with `formatTokens` and `formatDuration` exports
- [x] `app.js` imports `formatTokens, formatDuration` from `./format_metrics`
- [x] `app.xml` contains `ai-tree-metrics-line` with `getTraceTotals(node.trace)` binding
- [x] `app.scss` contains `.ai-tree-metrics-line` and `.ai-metric-chip` using Odoo variables only
- [x] `iter_detail.js` imports from `../format_metrics` and binds to instance
- [x] `iter_detail.xml` contains `ai-metric-chip` chips for duration and tokens
- [x] Task 1 commit: `f8b9e5d`
- [x] Task 2 commit: `231e3ca`

## Self-Check: PASSED
