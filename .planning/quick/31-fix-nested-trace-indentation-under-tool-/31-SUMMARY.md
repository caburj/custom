---
phase: quick-31
plan: 01
subsystem: ai_debug/scss
tags: [indentation, scss, visual-hierarchy]
key-files:
  modified:
    - ai_debug/static/src/app/app.scss
decisions:
  - "Use 48px (3 * $ai-indent-step) per depth level so child trace at D1 (56px) clears parent tool-call at D0 (40px) with a full 16px gap"
metrics:
  duration: "< 5 minutes"
  completed: "2026-02-24"
  tasks: 1
  files: 1
---

# Phase quick-31 Plan 01: Fix Nested Trace Indentation Under Tool-Call Summary

Fixed the per-depth multiplier in `.ai-indent-mode` from 16px to 48px so child trace rows at depth N+1 are indented further right than tool-call rows at depth N.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Change per-depth multiplier from 16 to 48 in indentation mode SCSS | a1681f4 | ai_debug/static/src/app/app.scss |

## What Changed

The `@for $d from 1 through 4` loop inside `.ai-indent-mode` previously used `$d * 16` as the per-depth offset. This meant:

- D0 tc row: 40px
- D1 trace row: 8 + 1*16 = 24px  ← LESS than D0 tc (visually inverted)

After the fix (`$d * 48`):

- D0: trace=8, iter=24, tc=40 (unchanged)
- D1: trace=56, iter=72, tc=88
- D2: trace=104, iter=120, tc=136
- D3: trace=152, iter=168, tc=184
- D4: trace=200, iter=216, tc=232

D1 trace (56px) is now 16px past D0 tc (40px), giving one clear visual step of indentation at each depth boundary.

## Verification

```
grep -n "$d * 48" app.scss  # returns 3 lines (trace, iter, tc)
grep -n "$d * 16" app.scss  # returns 0 lines
```

Both checks passed.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- File modified: ai_debug/static/src/app/app.scss - FOUND
- Commit a1681f4 - FOUND
- `$d * 48` appears 3 times - CONFIRMED
- `$d * 16` appears 0 times - CONFIRMED
