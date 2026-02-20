---
phase: quick
plan: 6
subsystem: ai_debug/frontend
tags: [layout, ux, debug-panel, two-column, auto-load]
dependency_graph:
  requires: []
  provides: [two-column-debug-panel]
  affects: [debug_panel.xml, debug_panel.js, debug_panel.scss]
tech_stack:
  added: []
  patterns: [flex-row layout, fire-and-forget async, OWL reactive state]
key_files:
  created: []
  modified:
    - ai_debug/static/src/debug_panel/debug_panel.js
    - ai_debug/static/src/debug_panel/debug_panel.xml
    - ai_debug/static/src/debug_panel/debug_panel.scss
decisions:
  - "Auto-load trace detail on channel switch rather than on user toggle — eliminates friction for primary use case (always want context visible)"
  - "_loadTraceDetail guards against double-fetch via 'instructions' in state.traceInfo check — safe to call from both _switchToTraceChannel and any future entry point"
  - "Direct-link traces (_loadTrace) already fetch instructions/rag_context/tools_definition in initial read — _loadTraceDetail early-returns due to guard, no extra request"
metrics:
  duration: 4 min
  completed: 2026-02-20
  tasks_completed: 3
  files_modified: 3
---

# Quick Task 6: Split Debug Panel into Left Trace Context + Right Timeline Summary

**One-liner:** Two-column debug panel — left panel shows system prompt/RAG/tools always-visible, right panel shows iterations timeline with independent scroll.

## What Was Built

Restructured the AI Debug Panel from a stacked layout (collapsible trace context above timeline) to a permanent two-column layout. The left panel shows trace context (system prompt, RAG context, tools definition) immediately when a trace is loaded — no clicking required. The right panel shows the iterations timeline and scrolls independently.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| 1 | Replace toggleTraceDetail with auto-load _loadTraceDetail | 5dc2c3b |
| 2 | Restructure XML template — two-column layout | fbaf094 |
| 3 | Update SCSS — flex row body, split panels, remove toggle styles | eacf82a |

## Changes by File

### debug_panel.js
- Removed `traceDetailExpanded` from reactive state
- Removed `toggleTraceDetail` binding and method entirely
- Added `_loadTraceDetail()` — fire-and-forget method that fetches `instructions`, `rag_context`, `tools_definition` if not already present on traceInfo
- `_switchToTraceChannel()` now calls `this._loadTraceDetail()` after channel subscribe (handles live new traces)
- Direct-link traces already get full data in `_loadTrace()` initial read — no change needed there

### debug_panel.xml
- Removed collapsible `ai-debug-trace-context` wrapper (toggle bar, chevron icon, expand guard)
- Added `ai-debug-body` flex container wrapping both panels
- Added `ai-debug-left-panel` — renders trace context sections directly (no conditional gate)
- Added `ai-debug-right-panel` with `t-ref="timeline"` — contains all existing iteration/timeline content unchanged
- Left panel shows listen-mode placeholder when `state.mode === 'listen'`

### debug_panel.scss
- Added `.ai-debug-body` — `display: flex; flex-direction: row; flex: 1; overflow: hidden; min-height: 0`
- Added `.ai-debug-left-panel` — 50% width, `overflow-y: auto`, white background, `border-right` separator
- Added `.ai-debug-right-panel` — 50% width, `overflow-y: auto`, 80px bottom padding
- Removed `.ai-debug-trace-context`, `.ai-debug-trace-context-toggle`, `.ai-debug-trace-context-hint`, `.ai-debug-trace-context-body`
- Removed `.ai-debug-timeline` (replaced by `.ai-debug-right-panel`)
- Retained `.ai-debug-trace-context-section`, `.ai-debug-trace-context-pre`, `.ai-debug-trace-context-count` — still used inside left panel

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check: PASSED

- `ai_debug/static/src/debug_panel/debug_panel.js` — modified, committed 5dc2c3b
- `ai_debug/static/src/debug_panel/debug_panel.xml` — modified, committed fbaf094
- `ai_debug/static/src/debug_panel/debug_panel.scss` — modified, committed eacf82a
- No references to `toggleTraceDetail` or `traceDetailExpanded` remain in any file
- XML validated: `xmllint --noout` passes
