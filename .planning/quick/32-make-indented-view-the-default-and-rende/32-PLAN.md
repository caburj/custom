---
phase: quick-32
plan: "01"
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-32]

must_haves:
  truths:
    - "Indentation mode is the default when no localStorage preference exists"
    - "Existing users with localStorage set to 'lines' keep their preference"
    - "In indentation mode, thin vertical guide lines appear at each depth boundary showing nesting hierarchy"
    - "Vertical lines use the same depth color palette as the existing SVG staircase lines"
    - "Toggle still switches between SVG guide lines mode and indentation mode"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "Default nestingMode changed from 'lines' to 'indent'"
      contains: "indent"
    - path: "ai_debug/static/src/app/app.scss"
      provides: "CSS vertical guide lines in .ai-indent-mode for depth visualization"
      contains: "ai-indent-depth-line"
  key_links:
    - from: "ai_debug/static/src/app/app.js"
      to: "ai_debug/static/src/app/app.scss"
      via: "nestingMode state drives 'ai-indent-mode' class on .ai-tree-content"
      pattern: "ai-indent-mode"
---

<objective>
Make indentation mode the default nesting view and add CSS vertical guide lines at each nesting depth level to visually communicate the tree hierarchy without requiring the SVG staircase overlay.

Purpose: The indentation mode is the superior UX (cleaner, less visual noise) but currently defaults to SVG lines mode. Additionally, indentation mode lacks visual depth indicators — the padding alone may not clearly communicate nesting relationships. Thin colored vertical lines at each depth boundary solve this.

Output: Updated default + CSS depth guide lines in indentation mode.
</objective>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/app.scss
@ai_debug/static/src/app/app.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Change default nestingMode to 'indent' and add CSS vertical depth guide lines</name>
  <files>ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.scss</files>
  <action>
**app.js** (one-line change):

In the `nestingMode` state initializer (line ~71), change the fallback default from `"lines"` to `"indent"`:
```js
nestingMode: (() => {
    try { return localStorage.getItem("ai_debug.nestingMode") || "indent"; }
    catch { return "indent"; }
})(),
```

This preserves existing users' localStorage preference but defaults new users to indentation mode.

**app.scss** — Add CSS vertical guide lines inside the `.ai-indent-mode` block:

Use `::before` pseudo-elements on depth-colored rows to render thin vertical lines that visually connect rows at each depth level. The approach:

1. Define a mixin or nested rule inside `.ai-indent-mode` that places a `::before` pseudo-element on every `.ai-tree-row` that has a depth class (`.ai-depth-1` through `.ai-depth-4`).

2. For each depth level N (1 through 4), render N vertical guide lines — one for each ancestor depth. Each line is positioned at the horizontal offset corresponding to that ancestor's indentation level. This creates a "staircase" of vertical lines showing all nesting context.

3. Use the `$ai-depth-colors` map to color each vertical line according to its depth level.

Implementation approach — use `::before` pseudo-elements with `box-shadow` for multiple vertical lines:

For each depth level $d (1 through 4), the `.ai-depth-#{$d}` row gets a `::before` pseudo-element that is:
- `position: absolute; top: 0; bottom: 0; width: 1px;`
- The `left` position is set to the midpoint of that depth's indentation zone
- Use `box-shadow` to stack multiple vertical lines (one per ancestor depth)

Specifically, for depth $d, we need vertical lines at positions corresponding to depths 1 through $d. Each line sits at the left edge of that depth's indentation zone. The indentation formula from quick-31 is:
- D0 trace starts at 8px
- Each depth adds 48px
- So depth $d trace starts at 8 + $d * 48

A vertical line for ancestor depth $a should appear at roughly `8 + $a * 48 - 8` = `$a * 48` pixels from the left edge (midway in the gap between parent tc-row padding and child trace-row padding).

Use this SCSS pattern inside `.ai-indent-mode`:

```scss
// Vertical depth guide lines — thin colored lines showing nesting hierarchy
// Each depth level gets lines for all ancestor depths, creating a visual staircase
@for $d from 1 through 4 {
    $colors: (#3b82f6, #14b8a6, #a855f7, #f59e0b, #f43f5e);

    .ai-depth-#{$d} {
        position: relative;

        &::before {
            content: '';
            position: absolute;
            top: 0;
            bottom: 0;
            width: 0;
            pointer-events: none;
            z-index: 1;
            // Build box-shadow with one 1px vertical line per ancestor depth
            // Each shadow at x-offset = (ancestor_depth * 48) px from left edge
            $shadows: ();
            @for $a from 1 through $d {
                $x: $a * 48;
                $c: nth($colors, $a + 1);  // +1 because depth 0 = blue (index 1), depth 1 = teal (index 2)
                $shadows: append($shadows, #{$x}px 0 0 0 rgba($c, 0.3), comma);
            }
            left: 0;
            box-shadow: $shadows;
        }
    }
}
```

This renders:
- Depth 1 rows: 1 teal line at x=48
- Depth 2 rows: 2 lines — teal at x=48, purple at x=96
- Depth 3 rows: 3 lines — teal at x=48, purple at x=96, amber at x=144
- Depth 4 rows: 4 lines — teal at x=48, purple at x=96, amber at x=144, rose at x=192

The lines are semi-transparent (0.3 opacity) so they provide visual guidance without overwhelming the content. They span the full height of each row, creating continuous vertical guides that connect parent and child rows.

Note: The guide lines should ONLY appear inside `.ai-indent-mode` — the SVG staircase handles this in lines mode.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented && grep -n '"indent"' ai_debug/static/src/app/app.js | head -5 && grep -c 'ai-depth-.*::before' ai_debug/static/src/app/app.scss && grep -n 'box-shadow' ai_debug/static/src/app/app.scss | head -5</automated>
    <manual>Open AI Debugger, verify: (1) defaults to indentation mode on fresh browser, (2) vertical colored lines visible at each depth level when subagent traces are nested, (3) toggling to lines mode hides CSS lines and shows SVG staircase, (4) toggling back to indent mode restores CSS lines</manual>
  </verify>
  <done>
    - Default nesting mode is 'indent' (not 'lines') for new users
    - Users with existing localStorage preference retain their choice
    - Indentation mode shows thin colored vertical guide lines at each depth boundary
    - Lines use depth-appropriate colors (teal for D1, purple for D2, amber for D3, rose for D4)
    - Lines only render inside .ai-indent-mode (not in SVG lines mode)
    - Toggle button continues to switch between both modes correctly
  </done>
</task>

</tasks>

<verification>
- `grep -n '"indent"' ai_debug/static/src/app/app.js` shows the new default on both the localStorage read line and the catch fallback
- `grep -c '"lines"' ai_debug/static/src/app/app.js` returns 0 (no more "lines" as default — only in toggleNestingMode comparison)
- `grep 'box-shadow' ai_debug/static/src/app/app.scss` shows the depth guide line shadows
- SCSS compiles without errors (no syntax issues in the @for loop with box-shadow generation)
</verification>

<success_criteria>
- Fresh browser (no localStorage) opens AI Debugger in indentation mode
- Nested subagent traces show colored vertical guide lines at each depth level
- Toggle button switches modes correctly in both directions
- SVG lines mode remains fully functional (no regression)
</success_criteria>

<output>
After completion, create `.planning/quick/32-make-indented-view-the-default-and-rende/32-SUMMARY.md`
</output>
