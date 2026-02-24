---
phase: quick-32
plan: "01"
subsystem: ai_debug/sidebar
tags: [ui, indentation-mode, css, defaults]
dependency_graph:
  requires: [quick-29, quick-30, quick-31]
  provides: [default-indent-mode, css-depth-guide-lines]
  affects: [ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.scss]
tech_stack:
  added: []
  patterns: [css-box-shadow-for-multiple-lines, scss-for-loop-shadow-accumulation]
key_files:
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.scss
decisions:
  - "Use box-shadow with multiple offset shadows to render multiple vertical lines without extra DOM nodes"
  - "Semi-transparent 0.3 opacity keeps lines subtle — visual guidance without overwhelming content"
  - "SCSS @for loop with $shadows accumulation generates correct box-shadow list per depth level"
metrics:
  duration: 81s
  completed: 2026-02-24
---

# Phase quick-32 Plan 01: Make Indented View Default + CSS Depth Guide Lines Summary

**One-liner:** Changed nestingMode default from 'lines' to 'indent' and added CSS vertical staircase guide lines via box-shadow pseudo-elements in indentation mode.

## What Was Built

Changed the default nesting mode so new users see indentation mode immediately, while preserving localStorage preferences for existing users. Added thin colored vertical guide lines in indentation mode using `::before` pseudo-elements with stacked `box-shadow` offsets — one line per ancestor depth level, using the established depth color palette (teal/purple/amber/rose).

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Change default nestingMode to 'indent' and add CSS vertical depth guide lines | 6a07093 | app.js, app.scss |

## Decisions Made

1. **box-shadow for multiple lines:** Rather than rendering N separate DOM elements, a single `::before` pseudo-element with stacked `box-shadow` values produces all vertical guide lines for a depth level. This is clean and avoids markup pollution.

2. **0.3 opacity:** Keeps lines subtle — they provide visual hierarchy guidance without competing with row content.

3. **SCSS accumulator pattern:** `$shadows: append($shadows, ..., comma)` builds the box-shadow list inside a `@for` loop, one entry per ancestor depth. This generates exactly the right shadow list per depth level at compile time.

4. **Colors follow depth palette:** Depth 1 = teal (#14b8a6) at x=48, depth 2 adds purple (#a855f7) at x=96, depth 3 adds amber (#f59e0b) at x=144, depth 4 adds rose (#f43f5e) at x=192. Matches existing `$ai-depth-colors` map and SVG staircase line colors.

5. **Lines only in .ai-indent-mode:** The entire `@for` block is nested inside `.ai-indent-mode`, so vertical CSS lines are completely absent in SVG lines mode — no regression risk.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

```
grep -n '"indent"' ai_debug/static/src/app/app.js
# Line 71: localStorage.getItem(...) || "indent"
# Line 72: catch { return "indent"; }
# Line 420: toggle comparison ("lines" ? "indent" : "lines") — unchanged

grep -c '"lines"' ai_debug/static/src/app/app.js
# Returns 1 — only the toggle comparison, not used as default

grep 'box-shadow' ai_debug/static/src/app/app.scss
# Shows the depth guide line shadow declarations

grep -c 'ai-indent-depth-line' ai_debug/static/src/app/app.scss
# Returns 1 — present in comment marker
```

## Self-Check: PASSED

- [x] `ai_debug/static/src/app/app.js` exists with `"indent"` as default
- [x] `ai_debug/static/src/app/app.scss` exists with `ai-indent-depth-line` comment and `box-shadow` depth guide lines
- [x] Commit 6a07093 exists
