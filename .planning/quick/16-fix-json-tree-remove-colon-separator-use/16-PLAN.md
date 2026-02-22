---
phase: quick-16
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/json_tree.xml
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-16]
---

<objective>
Fix 4 issues with the JSON tree widget:
1. Remove colon (:) separator between key and value
2. Replace triangle toggles (▾/▸) with square +/- buttons
3. Show Array(n) / {n keys} count indicator even when expanded
4. Make ALL string values clickable to open full text dialog (not just isLongString)
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/json_tree.js
@ai_debug/static/src/app/detail/json_tree.xml
@ai_debug/static/src/app/app.scss
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix all 4 JSON tree issues in XML template and SCSS</name>
  <files>ai_debug/static/src/app/detail/json_tree.xml, ai_debug/static/src/app/app.scss</files>
  <action>
**In `ai_debug/static/src/app/detail/json_tree.xml`:**

1. **Remove colon separators** — On line 15, change:
   ```xml
   <span class="ai-json-key" t-esc="props.label"/>:
   ```
   to:
   ```xml
   <span class="ai-json-key" t-esc="props.label"/>
   ```
   Do this BOTH in the expandable section (line 15) AND the leaf section (line 38).

2. **Replace triangle toggles with +/−** — On lines 11-12, change:
   ```xml
   <t t-if="state.expanded">&#x25BE;</t>
   <t t-else="">&#x25B8;</t>
   ```
   to:
   ```xml
   <t t-if="state.expanded">&#x2212;</t>
   <t t-else="">+</t>
   ```
   (&#x2212; is the proper minus sign −)

3. **Show count indicator always (not just when collapsed)** — Remove the `t-if="!state.expanded"` condition from the preview span. Change line 17-19 from:
   ```xml
   <t t-if="!state.expanded">
       <span class="ai-json-preview ai-json-value" t-esc="collapsedPreview"/>
   </t>
   ```
   to just:
   ```xml
   <span class="ai-json-preview ai-json-value" t-esc="collapsedPreview"/>
   ```
   (Always visible — when expanded it serves as a type/count indicator)

4. **Make ALL strings clickable** — In the leaf node section, merge the isLongString and normal string branches. Replace:
   ```xml
   <t t-if="isLongString">
       <span class="ai-json-string ai-json-value ai-json-truncated" t-on-click="onClickLongString"
             t-esc="displayValue" title="Click to expand"/>
   </t>
   <t t-elif="type === 'string'">
       <span class="ai-json-string ai-json-value" t-esc="displayValue"/>
   </t>
   ```
   with a single branch:
   ```xml
   <t t-if="type === 'string'">
       <span class="ai-json-string ai-json-value ai-json-truncated" t-on-click="onClickLongString"
             t-esc="displayValue" title="Click to expand"/>
   </t>
   ```
   This makes every string value clickable to open the popup dialog, which is essential since CSS truncation can hide content on strings shorter than the JS threshold.

**In `ai_debug/static/src/app/app.scss`:**

5. **Style toggle as square button** — Replace the `.ai-json-toggle` rule (around line 478) with:
   ```scss
   .ai-json-toggle {
       cursor: pointer;
       user-select: none;
       width: 14px;
       height: 14px;
       flex-shrink: 0;
       display: inline-flex;
       align-items: center;
       justify-content: center;
       font-size: 11px;
       font-weight: 600;
       line-height: 1;
       background-color: $o-gray-400;
       color: white;
       border-radius: 2px;

       &:hover { background-color: $o-action; }
   }
   ```

6. **Update toggle placeholder to match new toggle size** — Replace `.ai-json-toggle-placeholder` (around line 489) with:
   ```scss
   .ai-json-toggle-placeholder {
       display: inline-block;
       width: 14px;
       height: 14px;
       flex-shrink: 0;
   }
   ```

7. **Add gap between key pill and value** — Add `gap: 6px;` to `.ai-json-row` (change from 4px to 6px) to give more breathing room between key and value now that colon is removed.
  </action>
  <verify>
- No `:` characters appear after ai-json-key spans in the template
- Toggle uses − (&#x2212;) and + instead of ▾ and ▸
- collapsedPreview span has no t-if condition (always visible)
- All string values use ai-json-truncated class with onClickLongString handler
- .ai-json-toggle is styled as a small square button
  </verify>
  <done>All 4 issues fixed: no colon separator, square +/- toggles, always-visible count, all strings clickable.</done>
</task>

</tasks>

<verification>
- JSON tree shows no colon between keys and values
- Toggle buttons are square with +/- icons
- Array(n) and {n keys} indicators visible when expanded
- Clicking any CSS-truncated string opens the full text popup dialog
</verification>

<success_criteria>
All 4 reported issues are fixed. The JSON tree renders cleanly without colons, with square toggle buttons, always-visible type/count indicators, and clickable strings for full text expansion.
</success_criteria>

<output>
After completion, create `.planning/quick/16-fix-json-tree-remove-colon-separator-use/16-SUMMARY.md`
</output>
