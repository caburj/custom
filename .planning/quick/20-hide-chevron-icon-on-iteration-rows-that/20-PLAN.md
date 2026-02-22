---
phase: quick-20
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.xml
autonomous: true
requirements: [QUICK-20]

must_haves:
  truths:
    - "Iteration rows with zero tool calls show no chevron icon"
    - "Iteration rows with one or more tool calls show a clickable chevron"
    - "Clicking the chevron on iterations with tool calls still toggles expand/collapse"
    - "Alignment of iteration labels remains consistent whether chevron or placeholder is shown"
  artifacts:
    - path: "ai_debug/static/src/app/app.xml"
      provides: "Conditional chevron rendering on iteration rows"
      contains: "iteration.toolCalls.size"
  key_links:
    - from: "ai_debug/static/src/app/app.xml"
      to: "iteration.toolCalls"
      via: "OWL template conditional rendering"
      pattern: "toolCalls\\.size"
---

<objective>
Hide the chevron (expand/collapse arrow) on iteration rows in the sidebar tree when the iteration has no nested tool calls.

Purpose: Currently all iteration rows display a chevron even when they have nothing to expand. This is misleading UX — a chevron implies expandable children exist.
Output: Updated app.xml template with conditional chevron rendering.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Conditionally render chevron on iteration rows based on toolCalls.size</name>
  <files>ai_debug/static/src/app/app.xml</files>
  <action>
In the Level 1 iteration row block (around lines 112-114), replace the unconditional chevron span with a conditional:

- When `iteration.toolCalls.size > 0`: render the existing `ai-tree-chevron` span with its click handler and expanded class binding (unchanged behavior).
- When `iteration.toolCalls.size === 0`: render an `ai-tree-chevron-placeholder` span instead (same as tool call leaf nodes at level-2 use on line 137). This maintains horizontal alignment without showing a misleading arrow.

The change is purely in the XML template. Use `t-if` / `t-else` around the two span variants:

```xml
<span t-if="iteration.toolCalls.size > 0"
      class="ai-tree-chevron"
      t-att-class="{'expanded': iteration.expanded}"
      t-on-click.stop="() => this.toggleExpand(traceId, iterationId)">&#x203A;</span>
<span t-else="" class="ai-tree-chevron-placeholder"/>
```

Do NOT modify app.js or app.scss — no logic or style changes needed. The `ai-tree-chevron-placeholder` class already exists in the stylesheet (line 264-269 of app.scss) and provides the correct 16x16 invisible spacer.
  </action>
  <verify>
1. Open the AI Debugger app in the browser.
2. Find an iteration row that has no tool calls nested under it — confirm no chevron arrow is visible, but the text alignment matches other rows.
3. Find an iteration row that has tool calls — confirm the chevron is visible and clicking it expands/collapses the tool call children.
4. Verify no console errors in the browser dev tools.
  </verify>
  <done>Iteration rows without tool calls display a blank placeholder instead of a chevron. Iteration rows with tool calls display a functional chevron that toggles expand/collapse. Horizontal alignment is consistent across all iteration rows.</done>
</task>

</tasks>

<verification>
- Iteration rows with `toolCalls.size === 0` show no arrow icon
- Iteration rows with `toolCalls.size > 0` show a clickable chevron that toggles child visibility
- All iteration labels remain horizontally aligned (placeholder occupies same 16px width as chevron)
- No JS console errors
</verification>

<success_criteria>
Chevron only appears on iteration rows that have expandable tool call children. Empty iterations show a placeholder spacer maintaining alignment.
</success_criteria>

<output>
After completion, create `.planning/quick/20-hide-chevron-icon-on-iteration-rows-that/20-SUMMARY.md`
</output>
