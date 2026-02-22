---
phase: quick
plan: 23
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/tc_detail.xml
  - ai_debug/static/src/app/detail/tc_detail.js
autonomous: true
requirements: [QUICK-23]

must_haves:
  truths:
    - "All four content sections (Arguments, Result, State Diff, Confirmation Info) appear as tabs in a single Notebook"
    - "Header (tool name, success/fail badge) and error banner remain above the tabs, not inside any tab"
    - "StateDiff is guarded with t-if so null/undefined state_before or state_after does not cause OWL props validation errors"
    - "CopyButton, JsonTree, text expansion, and popup functionality still work inside the Arguments and Result tabs"
  artifacts:
    - path: "ai_debug/static/src/app/detail/tc_detail.xml"
      provides: "Single Notebook with 4 tab slots: arguments, result, state_diff, confirmation"
      contains: "t-set-slot=\"arguments\""
    - path: "ai_debug/static/src/app/detail/tc_detail.js"
      provides: "stateBefore and stateAfter getter properties for template guard"
      exports: ["ToolCallDetail"]
  key_links:
    - from: "ai_debug/static/src/app/detail/tc_detail.xml"
      to: "ai_debug/static/src/app/detail/tc_detail.js"
      via: "template getters stateBefore, stateAfter used in t-if guard"
      pattern: "t-if=\"stateBefore or stateAfter\""
    - from: "ai_debug/static/src/app/detail/tc_detail.xml"
      to: "ai_debug/static/src/app/detail/state_diff.js"
      via: "StateDiff component with guarded props"
      pattern: "StateDiff t-if=.*before=.*after="
---

<objective>
Refactor the ToolCallDetail view from a mixed stacked+tabbed layout to a single Notebook (tabs) layout containing all four content sections: Arguments, Result, State Diff, and Confirmation Info. Also apply the StateDiff t-if guard pattern from quick task 22 to prevent OWL props validation errors.

Purpose: Consistent tabbed UI that does not vertically stack large JSON sections, and prevents StateDiff crashes when state data is null/undefined.
Output: Updated tc_detail.xml and tc_detail.js files.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/tc_detail.xml
@ai_debug/static/src/app/detail/tc_detail.js
@ai_debug/static/src/app/detail/iter_detail.xml (reference for StateDiff guard pattern and Notebook tab structure)
@ai_debug/static/src/app/detail/iter_detail.js (reference for stateBefore/stateAfter getter pattern)
@ai_debug/static/src/app/detail/state_diff.js (StateDiff props definition — accepts null)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add stateBefore/stateAfter getters to tc_detail.js</name>
  <files>ai_debug/static/src/app/detail/tc_detail.js</files>
  <action>
Add two getter properties to the ToolCallDetail class, following the same naming convention used in iter_detail.js but simpler since toolCall has state_before/state_after directly:

```js
get stateBefore() {
    return this.props.toolCall.state_before;
}

get stateAfter() {
    return this.props.toolCall.state_after;
}
```

Place these after the existing `resultIsLong` getter (around line 48). These getters are needed by the template t-if guard added in Task 2.
  </action>
  <verify>No syntax errors: `grep -c "get stateBefore" ai_debug/static/src/app/detail/tc_detail.js` returns 1.</verify>
  <done>tc_detail.js has stateBefore and stateAfter getter properties that return the toolCall's state_before and state_after values.</done>
</task>

<task type="auto">
  <name>Task 2: Refactor tc_detail.xml to single Notebook with 4 tabs and StateDiff guard</name>
  <files>ai_debug/static/src/app/detail/tc_detail.xml</files>
  <action>
Rewrite the template body inside the `ai-detail-view` div. Keep the existing header div (lines 6-11) and error banner (lines 46-49) ABOVE the Notebook. Replace the stacked Arguments section (lines 13-21), stacked Result section (lines 23-44), and the existing 2-tab Notebook (lines 52-72) with a single `<Notebook>` containing four tab slots.

The new structure should be:

1. Header div (unchanged — type badge, tool name, success/fail badge)
2. Error banner (unchanged — `t-if="props.toolCall.error"`)
3. Single `<Notebook>` with 4 slots:

**Slot "arguments"** (title: "Arguments"):
- Wrap in `ai-detail-section` div
- Section header with "Arguments" span and `<CopyButton content="() => this.argsJson"/>`
- `<JsonTree data="props.toolCall.args" onExpandText="(title, content) => this.openTextPopup(title, content, 'json')"/>`

**Slot "result"** (title: "Result"):
- Wrap in `ai-detail-section` div
- Section header with "Result" span and `<CopyButton content="() => this.resultString"/>`
- Same conditional rendering as current: `t-if="resultIsObject"` for JsonTree, else check `resultIsLong` for text-preview with click-to-expand, else plain `<pre>` block

**Slot "state_diff"** (title: "State Diff"):
- Wrap in `ai-detail-section` div
- Section header with "State Diff" span (no CopyButton)
- Apply the guard pattern from iter_detail.xml:
  ```xml
  <StateDiff t-if="stateBefore or stateAfter"
             before="stateBefore || {}"
             after="stateAfter || {}"/>
  <div t-else="" class="ai-diff-empty">
      <span>No state data available.</span>
  </div>
  ```

**Slot "confirmation"** (title: "Confirmation Info"):
- Keep identical to existing (placeholder message about v1.1 bus payloads)

All slot `isVisible` attributes set to `"true"`.

IMPORTANT: Do NOT change any class names, component attributes, or functional behavior. Only restructure the layout from stacked+tabbed to fully tabbed, and add the StateDiff guard.
  </action>
  <verify>
1. Verify XML is well-formed: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('ai_debug/static/src/app/detail/tc_detail.xml'); print('XML valid')"` prints "XML valid".
2. Verify 4 tab slots exist: `grep -c 't-set-slot' ai_debug/static/src/app/detail/tc_detail.xml` returns 4.
3. Verify StateDiff guard: `grep 'StateDiff t-if' ai_debug/static/src/app/detail/tc_detail.xml` matches the guarded pattern.
4. Verify no stacked sections remain outside Notebook: `grep -c 'ai-detail-section' ai_debug/static/src/app/detail/tc_detail.xml` should be 4 (one per tab, all inside Notebook).
  </verify>
  <done>tc_detail.xml has a single Notebook with 4 tabs (Arguments, Result, State Diff, Confirmation Info), header and error banner above the tabs, StateDiff guarded with t-if, and all existing functionality preserved.</done>
</task>

</tasks>

<verification>
1. XML parses without errors
2. Template has exactly one `<Notebook>` element with 4 `t-set-slot` children
3. No `ai-detail-section` divs exist outside the Notebook (only header and error banner above)
4. StateDiff uses `t-if="stateBefore or stateAfter"` guard with `|| {}` fallback
5. CopyButton still present in Arguments and Result tabs
6. JsonTree still used for args and object results
7. Text expansion (resultIsLong click handler) still present in Result tab
</verification>

<success_criteria>
- ToolCallDetail renders all content in a single 4-tab Notebook
- Arguments tab shows JsonTree with CopyButton
- Result tab shows JsonTree or text with CopyButton
- State Diff tab renders StateDiff safely (guarded) or shows "No state data available"
- Confirmation Info tab shows existing placeholder
- Header and error banner remain above the tabs
- No OWL props validation errors when state_before/state_after are null/undefined
</success_criteria>

<output>
After completion, create `.planning/quick/23-refactor-tool-call-detail-to-use-tabs-ar/23-SUMMARY.md`
</output>
