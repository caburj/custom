---
phase: quick-15
plan: 01
subsystem: ai_debug/json-tree
tags: [ui, scss, json-tree, dark-mode, styling]
dependency_graph:
  requires: []
  provides: [restyled-json-tree-widget]
  affects: [ai_debug/json-tree]
tech_stack:
  added: []
  patterns: [css-driven-depth-lines, pill-styled-keys, css-truncation]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/detail/json_tree.xml
    - ai_debug/static/src/app/app.scss
    - ai_debug/static/src/app/app.dark.scss
decisions:
  - Use CSS class (ai-json-nested) on depth > 0 nodes instead of inline padding-left style
  - Apply ai-json-value CSS truncation class to all leaf value spans for uniform single-line truncation
  - Dark mode depth line uses $o-gray-700 (vs $o-gray-300 light) for visibility on dark background
  - Key pill uses rgba($o-action, 0.08) light / rgba($o-action, 0.15) dark for subtle contrast
metrics:
  duration: ~5 minutes
  completed: 2026-02-22
  tasks_completed: 2
  files_modified: 3
---

# Phase quick-15 Plan 01: Restyle JSON Tree Widget Summary

**One-liner:** Restyled JSON tree with CSS-driven vertical depth lines (border-left), pill-styled key badges (rgba background + border-radius), single-line CSS-truncated values (overflow/ellipsis), and compact 1.35 line-height in light and dark modes.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Update XML template to remove inline padding and support CSS-driven depth | 844a6b1 | ai_debug/static/src/app/detail/json_tree.xml |
| 2 | Restyle SCSS for depth lines, key pills, value truncation, and compact spacing | afcfef5 | ai_debug/static/src/app/app.scss, ai_debug/static/src/app/app.dark.scss |

## What Was Built

### Task 1 — XML Template Update

In `json_tree.xml`:
- Replaced `class="ai-json-node" t-att-style="props.depth > 0 ? 'padding-left:12px' : false"` with `t-att-class="'ai-json-node' + (props.depth > 0 ? ' ai-json-nested' : '')"` — moves depth indentation from inline style to a CSS class
- Added `ai-json-value` class to all leaf value spans: `ai-json-string`, `ai-json-number`, `ai-json-boolean`, `ai-json-null` (including the `ai-json-truncated` long-string span)
- Added `ai-json-value` class to the collapsed `ai-json-preview` span in expandable nodes

### Task 2 — SCSS Restyle

In `app.scss` (JSON tree section, lines 431-505):
- `.ai-json-node`: reduced `line-height` from 1.6 to 1.35 for compact layout
- NEW `.ai-json-nested`: `margin-left: 6px; padding-left: 10px; border-left: 1px solid $o-gray-300` — vertical depth lines indicating nesting level
- `.ai-json-row`: reduced `min-height` from 20px to 17px; added `overflow: hidden` to contain truncated values
- `.ai-json-key`: added pill styling — `background-color: rgba($o-action, 0.08); padding: 0 4px; border-radius: 3px`
- NEW `.ai-json-value`: `overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0` — CSS-driven single-line truncation on all value spans

In `app.dark.scss`:
- Added `.ai-json-nested { border-left-color: $o-gray-700; }` — visible depth line on dark background
- Added `.ai-json-key { background-color: rgba($o-action, 0.15); }` — stronger pill opacity in dark mode

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check

**Files exist:**
- ai_debug/static/src/app/detail/json_tree.xml — MODIFIED
- ai_debug/static/src/app/app.scss — MODIFIED
- ai_debug/static/src/app/app.dark.scss — MODIFIED

**Commits exist:**
- 844a6b1 — Task 1 XML changes
- afcfef5 — Task 2 SCSS changes

## Self-Check: PASSED
