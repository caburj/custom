---
phase: quick-16
plan: 01
subsystem: ai_debug/json-tree
tags: [ui, xml, scss, json-tree, ux-fix]
key_files:
  modified:
    - ai_debug/static/src/app/detail/json_tree.xml
    - ai_debug/static/src/app/app.scss
metrics:
  completed: 2026-02-22
  tasks_completed: 1
  files_modified: 2
---

# Quick-16 Summary: Fix JSON tree UX issues

**One-liner:** Fixed 4 JSON tree issues: removed colon separator, replaced triangles with square +/- toggles, made Array(n)/{n keys} always visible, and made all strings clickable for full text expansion.

## Changes

### json_tree.xml
- Removed `:` character after all `ai-json-key` spans (both expandable and leaf rows)
- Replaced `▾`/`▸` triangle toggle characters with `−`/`+` (proper minus &#x2212; and plus)
- Removed `t-if="!state.expanded"` gate on `collapsedPreview` span — count indicator now always visible
- Merged `isLongString` and normal string branches — all strings now have `ai-json-truncated` class and `onClickLongString` handler, fixing the bug where CSS-truncated strings below the 300-char JS threshold were not clickable

### app.scss
- `.ai-json-row` gap increased from 4px to 6px for better key/value spacing without colon
- `.ai-json-toggle` restyled as 14x14px square button with `$o-gray-400` background, white text, 2px border-radius, hover changes to `$o-action`
- `.ai-json-toggle-placeholder` updated to match 14x14px dimensions

## Commit

- `e752ebe` — feat(quick-16): fix JSON tree: remove colon, square toggles, always-show count, clickable strings
