---
phase: 29-toolbar-toggle-nesting-mode
plan: "01"
type: quick-task
subsystem: ai_debug/sidebar-ui
tags: [ui, sidebar, toggle, localStorage, scss]
dependency_graph:
  requires: []
  provides: [nestingMode-toggle]
  affects: [ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.xml, ai_debug/static/src/app/app.scss]
tech_stack:
  added: []
  patterns: [OWL-useState, localStorage-persistence, SCSS-@for-loop]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
decisions:
  - "nestingMode defaults to 'lines' (current behavior unchanged by default)"
  - "Toggle button placed first in header-actions (before export/import/delete — view mode vs destructive actions)"
  - "Hover color for toggle button uses $o-action (blue) not $o-danger (red)"
  - "Base indent-mode padding is 8px (vs 28px SVG-clearance), +16px per depth level"
metrics:
  duration: ~5 minutes
  completed: 2026-02-24T10:45:11Z
  tasks_completed: 3
  files_modified: 3
---

# Quick Task 29: Add Toolbar Toggle for SVG Guide Lines vs Indentation Mode

**One-liner:** nestingMode toggle button in sidebar header persists 'lines'/'indent' preference to localStorage, conditionally renders SVG depth lines or applies progressive padding-left per depth.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add nestingMode state with localStorage persistence and toggle method | ca963f0 | app.js |
| 2 | Add toggle button to header and conditional SVG/indentation class in template | b95bf18 | app.xml |
| 3 | Add indentation-mode SCSS rules with per-depth padding | 4ca1ee6 | app.scss |

## What Was Built

A nesting mode toggle for the AI Debugger sidebar. Users can switch between:

- **Guide lines mode** (default, "lines"): SVG staircase depth lines are rendered, all rows have flat `padding-left: 28px` (existing behavior, no regression)
- **Indentation mode** ("indent"): SVG is hidden, rows get depth-based `padding-left` — 8px at depth 0, +16px per level (24px, 40px, 56px, 72px for depths 1-4)

The toggle button (pipe character `|` for lines mode, triple-bar `≡` for indent mode) appears as the first button in the sidebar header actions. Title attribute changes dynamically to label the switch destination. Preference persists across page refreshes via `localStorage.getItem/setItem("ai_debug.nestingMode")` wrapped in try/catch for private browsing compatibility.

Depth background tints (`.ai-depth-N` `background-color: rgba(...)`) are preserved in both modes — the indentation rules only override `padding-left`.

## Key Implementation Details

**app.js changes:**
- `nestingMode` added to `this.state` useState with IIFE initializer reading localStorage
- `toggleNestingMode()` method added alongside other user interaction methods

**app.xml changes:**
- Toggle button as first child of `.ai-tree-header-actions` with conditional Unicode icons and dynamic title
- SVG `t-if` extended: `sidebarNodes.length > 0 and state.nestingMode === 'lines'`
- `.ai-tree-content` div uses `t-attf-class` to conditionally apply `ai-indent-mode`

**app.scss changes:**
- `.ai-indent-mode` block with nested `.ai-tree-row` override and `@for $d from 1 through 4` loop for depth-specific padding
- `.ai-tree-nesting-toggle` extends `.ai-tree-action-btn` with monospace font and blue hover (not red danger)

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

**Created files:**
- N/A (no new files)

**Modified files:**
- [x] ai_debug/static/src/app/app.js — contains nestingMode in state + toggleNestingMode()
- [x] ai_debug/static/src/app/app.xml — contains toggle button, conditional SVG, conditional class
- [x] ai_debug/static/src/app/app.scss — contains .ai-indent-mode and .ai-tree-nesting-toggle

**Commits exist:**
- [x] ca963f0 — Task 1
- [x] b95bf18 — Task 2
- [x] 4ca1ee6 — Task 3

## Self-Check: PASSED
