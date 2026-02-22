---
phase: quick-15
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/json_tree.xml
  - ai_debug/static/src/app/app.scss
  - ai_debug/static/src/app/app.dark.scss
autonomous: true
requirements: [QUICK-15]

must_haves:
  truths:
    - "Nested JSON nodes show vertical depth lines (border-left) indicating nesting level"
    - "JSON keys render as pill/badge shapes with subtle background and rounded corners"
    - "Long string values are CSS-truncated to single line with ellipsis, filling remaining row width"
    - "Tree is visually more compact than before (reduced line-height and min-height)"
    - "Dark mode still renders correctly with appropriate depth line and pill colors"
  artifacts:
    - path: "ai_debug/static/src/app/detail/json_tree.xml"
      provides: "Template without inline padding-left, depth handled by CSS"
      contains: "ai-json-node"
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Restyled JSON tree with depth lines, key pills, value truncation, compact spacing"
      contains: "ai-json-node"
    - path: "ai_debug/static/src/app/app.dark.scss"
      provides: "Dark mode overrides for depth line color and key pill background"
      contains: "ai-json-key"
  key_links:
    - from: "ai_debug/static/src/app/detail/json_tree.xml"
      to: "ai_debug/static/src/app/app.scss"
      via: "CSS classes on .ai-json-node nested structure"
      pattern: "ai-json-node"
---

<objective>
Restyle the JSON tree widget to have vertical depth lines, pill-styled keys, CSS-driven single-line value truncation, and compact spacing.

Purpose: Make the JSON tree visually resemble a jQuery tree plugin style — information-dense, depth-aware via vertical lines, with clean key/value separation.
Output: Updated XML template and SCSS styles for the JSON tree widget.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/json_tree.js
@ai_debug/static/src/app/detail/json_tree.xml
@ai_debug/static/src/app/app.scss
@ai_debug/static/src/app/app.dark.scss
</context>

<tasks>

<task type="auto">
  <name>Task 1: Update XML template to remove inline padding and support CSS-driven depth</name>
  <files>ai_debug/static/src/app/detail/json_tree.xml</files>
  <action>
In `ai_debug/static/src/app/detail/json_tree.xml`:

1. Remove the inline style from the root div. Change:
   `<div class="ai-json-node" t-att-style="props.depth > 0 ? 'padding-left:12px' : false">`
   to:
   `<div t-att-class="'ai-json-node' + (props.depth > 0 ? ' ai-json-nested' : '')">`

   This adds an `ai-json-nested` class on child nodes (depth > 0) so CSS can apply border-left depth lines and left padding/margin uniformly, instead of inline styles.

2. On the `.ai-json-row` div for leaf nodes (the `<t t-else="">` branch, around line 35), make the row a flex container that can truncate its value. The row div already has `class="ai-json-row"` which is correct. No structural change needed here — the CSS will handle truncation on the value spans.

3. Wrap each value span (string, number, boolean, null) in the leaf branch with an additional class `ai-json-value` for targeted CSS truncation. Change each value span to include the extra class:
   - `<span class="ai-json-string ai-json-value ai-json-truncated" ...>` (for long strings — keep existing classes too)
   - `<span class="ai-json-string ai-json-value" ...>` (for normal strings)
   - `<span class="ai-json-number ai-json-value" ...>` (for numbers)
   - `<span class="ai-json-boolean ai-json-value" ...>` (for booleans)
   - `<span class="ai-json-null ai-json-value" ...>` (for null)

   Also add `ai-json-value` to the collapsed preview span in the expandable branch:
   - `<span class="ai-json-preview ai-json-value" ...>`

Do NOT change the JS file. Do NOT alter any t-on-click handlers, props, or component logic.
  </action>
  <verify>
Visually inspect the XML to confirm:
- No inline `style=` attributes remain on `.ai-json-node`
- `ai-json-nested` class is conditionally applied when `depth > 0`
- All value spans have the `ai-json-value` class added
- All existing classes, event handlers, and t-esc bindings are preserved
  </verify>
  <done>Template has ai-json-nested class for depth > 0 nodes, ai-json-value class on all value spans, and no inline padding styles.</done>
</task>

<task type="auto">
  <name>Task 2: Restyle SCSS for depth lines, key pills, value truncation, and compact spacing</name>
  <files>ai_debug/static/src/app/app.scss, ai_debug/static/src/app/app.dark.scss</files>
  <action>
In `ai_debug/static/src/app/app.scss`, replace the entire JSON tree viewer section (lines 431-487, from the `// JSON tree viewer` comment through `.ai-json-truncated`) with the following restyled rules:

```scss
// JSON tree viewer
.ai-json-node {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 12px;
    line-height: 1.35;
}

// Nested nodes get vertical depth lines and indentation via CSS
.ai-json-nested {
    margin-left: 6px;
    padding-left: 10px;
    border-left: 1px solid $o-gray-300;
}

.ai-json-row {
    display: flex;
    align-items: baseline;
    gap: 4px;
    min-height: 17px;
    overflow: hidden;
}

.ai-json-key {
    color: $o-action;
    flex-shrink: 0;
    background-color: rgba($o-action, 0.08);
    padding: 0 4px;
    border-radius: 3px;
}

.ai-json-value {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
}

.ai-json-string { color: $o-success; }
.ai-json-number { color: $o-gray-700; }
.ai-json-boolean { color: $o-main-code-color; }
.ai-json-null { color: $o-gray-500; font-style: italic; }

.ai-json-preview {
    color: $o-gray-500;
    font-style: italic;
}

.ai-json-toggle {
    cursor: pointer;
    color: $o-gray-500;
    user-select: none;
    width: 12px;
    flex-shrink: 0;
    text-align: center;

    &:hover { color: $o-action; }
}

.ai-json-toggle-placeholder {
    display: inline-block;
    width: 12px;
    flex-shrink: 0;
}

.ai-json-truncated {
    cursor: pointer;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-decoration-color: $o-gray-500;

    &:hover {
        color: $o-gray-900;
        text-decoration-color: $o-action;
    }
}
```

Key changes from the original:
- `.ai-json-node` line-height reduced from 1.6 to 1.35
- NEW `.ai-json-nested` rule: `margin-left: 6px; padding-left: 10px; border-left: 1px solid $o-gray-300;` for vertical depth lines
- `.ai-json-row` min-height reduced from 20px to 17px, added `overflow: hidden`
- `.ai-json-key` gains pill styling: `background-color: rgba($o-action, 0.08); padding: 0 4px; border-radius: 3px;`
- NEW `.ai-json-value` rule for CSS truncation: `overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0;`
- All other rules (toggle, placeholder, truncated, colors) preserved as-is

In `ai_debug/static/src/app/app.dark.scss`, add dark mode overrides for the new depth line and key pill styles. After the existing `.ai-json-null` rule (line 19), add:

```scss
// Dark mode: depth lines and key pills
.ai-json-nested { border-left-color: $o-gray-700; }
.ai-json-key { background-color: rgba($o-action, 0.15); }
```

These ensure the depth line is visible (lighter gray on dark bg would be invisible) and the key pill has slightly stronger opacity in dark mode for contrast.
  </action>
  <verify>
1. Open the AI debugger in the browser and navigate to a detail view that shows a JSON tree with nested objects/arrays.
2. Confirm vertical depth lines appear as thin gray lines on the left edge of nested node groups.
3. Confirm keys appear as subtle pills (rounded background behind key text).
4. Confirm long string values are truncated with ellipsis on a single line.
5. Confirm the overall tree is visually more compact (tighter line spacing).
6. Toggle dark mode and confirm depth lines and key pills remain visible and styled appropriately.
7. Confirm expand/collapse toggle still works, including Alt+click recursive expand/collapse.
8. Confirm clicking a truncated long string still opens the text popup dialog.
  </verify>
  <done>JSON tree renders with vertical depth lines on nested nodes, pill-styled keys, CSS-truncated values, and compact spacing in both light and dark modes.</done>
</task>

</tasks>

<verification>
- JSON tree widget renders with vertical depth lines indicating nesting depth
- Keys display as pills with subtle background color and rounded corners
- Long values are CSS-truncated to single line with ellipsis
- Tree spacing is more compact (line-height ~1.35, min-height 17px)
- Dark mode renders correctly with visible depth lines and key pills
- All interactive features preserved: expand/collapse, Alt+click recursive, long string popup
</verification>

<success_criteria>
The JSON tree widget visually matches the design spec: vertical depth lines for nesting, pill-styled keys, single-line CSS-truncated values, and compact dense layout. Both light and dark modes work correctly. No functional regressions in expand/collapse or text popup behavior.
</success_criteria>

<output>
After completion, create `.planning/quick/15-restyle-json-tree-widget-with-vertical-d/15-SUMMARY.md`
</output>
