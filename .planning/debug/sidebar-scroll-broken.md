---
status: resolved
trigger: "Sidebar tree cannot scroll when content overflows"
created: 2026-02-21T00:00:00Z
updated: 2026-02-21T00:00:00Z
---

## Current Focus

hypothesis: Root cause confirmed — see Resolution section
test: Static analysis of app.scss and app.xml
expecting: N/A
next_action: N/A (diagnosis complete, no fix requested)

## Symptoms

expected: Sidebar tree scrolls when many entries are present; `.ai-tree-header` (TRACES) stays pinned
actual: Content is cut off; no scrollbar appears; cannot scroll
errors: None (visual layout failure, no JS error)
reproduction: Load 4+ loops with iterations and tool calls expanded
started: After phase 06-02 introduced the pinned header restructure

## Eliminated

- hypothesis: `.ai-debug-sidebar` is still `overflow-y: auto` (reverting the header-pin change)
  evidence: app.scss line 74 confirms `overflow: hidden` — this is correct and intentional
  timestamp: 2026-02-21

- hypothesis: `.ai-tree-content` is missing `overflow-y: auto`
  evidence: app.scss lines 80-85 confirm `overflow-y: auto` is present on `.ai-tree-content`
  timestamp: 2026-02-21

- hypothesis: The `.ai-tree-content` wrapper div is missing from the XML
  evidence: app.xml line 28 confirms `<div class="ai-tree-content" t-ref="sidebar">` is present and the closing tag is on line 115
  timestamp: 2026-02-21

## Evidence

- timestamp: 2026-02-21
  checked: app.scss — `.ai-debug-sidebar` (lines 69-77)
  found: |
    display: flex;
    flex-direction: column;
    overflow: hidden;
    (width: 280px; min-width: 280px — fixed, not percentage)
  implication: Correct flex column setup. height is NOT explicitly set here; it relies on the
    parent flex container to constrain it.

- timestamp: 2026-02-21
  checked: app.scss — `.ai-debug-main` (lines 62-66)
  found: |
    display: flex;
    flex: 1;
    overflow: hidden;
  implication: `.ai-debug-main` is a flex row that takes all remaining vertical space below
    the header bar. This is correct for giving `.ai-debug-sidebar` a bounded height.

- timestamp: 2026-02-21
  checked: app.scss — `.ai-debug-app` (lines 1-11)
  found: |
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
  implication: Root container is correctly sized to viewport height.

- timestamp: 2026-02-21
  checked: app.scss — `.ai-tree-content` (lines 80-85)
  found: |
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  implication: `flex: 1` causes this element to grow to fill remaining space INSIDE its
    flex parent (`.ai-debug-sidebar`). `overflow-y: auto` is present. This looks correct
    on paper, BUT see root cause below.

- timestamp: 2026-02-21
  checked: app.xml — sidebar structure (lines 19-117)
  found: |
    <aside class="ai-debug-sidebar">
      <div class="ai-tree-header"> ... </div>
      <div class="ai-tree-content" t-ref="sidebar">
        <div t-if="traces.size === 0" class="ai-debug-sidebar-empty"> ... </div>
        <t t-foreach="[...traces.keys()]" ...>
          <!-- tree rows -->
        </t>
      </div>
    </aside>
  implication: DOM structure is correct. `.ai-tree-header` is outside `.ai-tree-content`,
    which is what the pinned-header pattern requires.

- timestamp: 2026-02-21
  checked: app.scss — `.ai-tree-content` — inner flex column direction
  found: |
    display: flex;
    flex-direction: column;
  implication: THIS IS THE ROOT CAUSE. See Resolution.

## Resolution

root_cause: |
  `.ai-tree-content` has `display: flex; flex-direction: column` applied to it.
  This makes it a flex container whose children are flex items laid out vertically.

  In a flex column container, children by default have `align-items: stretch` and
  `flex-shrink: 1`. Crucially, a flex container DOES NOT clip its children to its own
  height unless `overflow` is explicitly set on it. The parent's `overflow-y: auto` will
  only trigger a scrollbar when the content height exceeds the element's own height.

  The actual root cause is subtler: `.ai-tree-content` is itself a flex ITEM (inside
  `.ai-debug-sidebar` which is `display: flex; flex-direction: column`). The rule
  `flex: 1` means `flex-grow: 1; flex-shrink: 1; flex-basis: 0%`. With `flex-basis: 0%`,
  the element starts at zero height and grows to fill available space — but in a flex
  layout, `overflow-y: auto` on a flex item only activates when the item has a definite
  height.

  The specific failure mechanism:
  1. `.ai-tree-content` has `flex: 1` — it fills the remaining space in `.ai-debug-sidebar`
  2. `.ai-tree-content` also has `display: flex; flex-direction: column`
  3. Its children (the `.ai-tree-row` divs and the `<t t-foreach>` fragments) are direct
     flex items and will push the flex container to grow rather than overflow it
  4. When a flex container has `overflow-y: auto` but its children are flex items, the
     container's intrinsic height is calculated as the sum of its children — it expands to
     fit them, rather than clipping at its bounded size. This suppresses the scrollbar.

  In plain terms: **`display: flex` on `.ai-tree-content` causes it to grow to contain
  its children rather than scroll past them.** The children are rendered in an
  ever-growing flex column that simply pushes past the `.ai-debug-sidebar` boundary,
  which is invisible because `.ai-debug-sidebar` has `overflow: hidden`.

  The fix is to remove `display: flex; flex-direction: column` from `.ai-tree-content`,
  or to replace it with `display: block`. A plain block container with `flex: 1` and
  `overflow-y: auto` will correctly scroll when its content height exceeds its allocated
  height.

  Secondary contributing factor: the `.ai-tree-row` items have fixed `height: 34px` so
  their total height is deterministic and measurable — the layout engine CAN compute
  overflow. The flex container direction is the sole blocker.

fix: NOT APPLIED — diagnosis only
verification: NOT PERFORMED — diagnosis only
files_changed: []

## Suggested Fix

In `app.scss`, change `.ai-tree-content` from:

  ```scss
  .ai-tree-content {
      flex: 1;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
  }
  ```

  to:

  ```scss
  .ai-tree-content {
      flex: 1;
      overflow-y: auto;
      min-height: 0;   // required: allows flex item to shrink below its content height
  }
  ```

  The `min-height: 0` override is the standard fix for this pattern. By default, flex
  items have `min-height: auto`, which means they refuse to shrink below their content
  size. Adding `min-height: 0` allows the flex item to be bounded to its allocated height,
  which makes `overflow-y: auto` actually trigger.

  Removing `display: flex; flex-direction: column` is also necessary — plain block layout
  inside the scroll container is correct for a list of tree rows.
