---
phase: quick-7
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
  - ai_debug/static/src/app/detail/json_tree.xml
autonomous: true
requirements: []
must_haves:
  truths:
    - "Notebook tabs have no light background bleed — tab bar and tabs are fully dark themed"
    - "JSON tree indentation is compact and readable at depth 4+"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Dark theme notebook tab overrides and JSON tree styles"
    - path: "ai_debug/static/src/app/detail/json_tree.xml"
      provides: "Reduced indentation multiplier for JSON tree nodes"
  key_links: []
---

<objective>
Fix two cosmetic gaps from Phase 07 UAT: (1) Notebook tab styling bleeding light backgrounds in dark theme, and (2) JSON tree indentation being excessively large at deeper nesting levels.

Purpose: Polish the detail panel UI so it looks consistent with the dark theme at all levels of interaction.
Output: Updated SCSS overrides and XML template with tighter indentation.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.scss (lines 349-383 for notebook overrides, lines 461-517 for JSON tree)
@ai_debug/static/src/app/detail/json_tree.xml (line 5 for depth multiplier)
@.planning/phases/07-detail-panel/07-UAT.md (cosmetic gaps)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix Notebook tab dark theme bleed-through</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
In the `.ai-debug-detail .o_notebook` block (lines ~350-383), the `.nav-link` rule only sets `background-color: transparent` on the `.active` state. Bootstrap's default `.nav-tabs .nav-link` has a white/light background on hover and default states that bleeds through.

Fix by adding `background-color: transparent` to the base `.nav-link` rule (not just `.active`). Also add `background-color: transparent` to the `&:hover:not(.active)` state explicitly. This ensures no Bootstrap default background leaks into any tab state.

Additionally, the `.nav-tabs` container itself may have a Bootstrap-inherited `border-bottom` that conflicts. The existing `border-bottom: 1px solid #313244` override should handle this, but confirm the `.nav-link` items do not have a conflicting `border-color` from Bootstrap by ensuring `border-color: transparent` on the base `.nav-link`.

The updated `.nav-link` block should look like:
```scss
.nav-link {
    color: #6c7086;
    border: none;
    border-bottom: 2px solid transparent;
    background-color: transparent;
    padding: 8px 16px;
    font-size: 12px;

    &.active {
        color: #cdd6f4;
        background-color: transparent;
        border-bottom-color: #89b4fa;
    }

    &:hover:not(.active) {
        color: #a6adc8;
        background-color: transparent;
    }
}
```
  </action>
  <verify>Open the AI Debugger, select a trace, and visually confirm that the Notebook tab bar has no light/white background. The tabs should sit on the dark #181825 background with no bleed-through on default, hover, and active states.</verify>
  <done>All Notebook tab states (default, hover, active) render with transparent backgrounds on the dark #181825 tab bar. No light theme colors visible anywhere in the tab strip.</done>
</task>

<task type="auto">
  <name>Task 2: Reduce JSON tree indentation multiplier</name>
  <files>ai_debug/static/src/app/detail/json_tree.xml</files>
  <action>
In `json_tree.xml` line 5, change the padding-left calculation from `props.depth * 16` to `props.depth * 10`.

Current: `t-att-style="'padding-left:' + (props.depth * 16) + 'px'"`
New:     `t-att-style="'padding-left:' + (props.depth * 10) + 'px'"`

Rationale: At depth 5, old padding = 80px; new padding = 50px. The 10px multiplier keeps hierarchy visually clear while being compact enough that deeply nested structures (common in AI tool call args/results) remain readable without excessive horizontal scrolling.
  </action>
  <verify>Open the AI Debugger, select a tool call with nested JSON args. Expand nodes to depth 3-4. Confirm indentation is visually clear but noticeably more compact than before. At depth 4, padding should be 40px (not 64px).</verify>
  <done>JSON tree nodes indent by 10px per depth level. Deeply nested structures (depth 4+) remain readable without excessive horizontal space consumption.</done>
</task>

</tasks>

<verification>
1. Load the AI Debugger in the browser
2. Trigger a debug session so traces appear
3. Click a trace — verify the Notebook tabs (System Prompt, RAG Context, Tools Definition) have no light background bleed
4. Click an iteration — verify its Notebook tabs also render cleanly
5. Click a tool call with nested JSON args — verify indentation is compact at all nesting levels
</verification>

<success_criteria>
- Notebook tab bar is fully dark-themed in all states (default, hover, active) with no white/light bleed
- JSON tree indentation uses 10px per depth level, keeping deep structures compact and readable
- Both fixes are CSS/template only — no JS changes, no behavioral changes
</success_criteria>

<output>
After completion, create `.planning/quick/7-fix-the-cosmetic-gaps/7-SUMMARY.md`
</output>
