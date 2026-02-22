---
phase: 22-fix-statediff-props-validation-error-bef
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/iter_detail.xml
  - ai_debug/static/src/app/detail/state_diff.js
autonomous: true
requirements: [BUGFIX-22]

must_haves:
  truths:
    - "Clicking State Diff tab on an iteration with no tool calls does NOT throw OwlError"
    - "Clicking State Diff tab on an iteration WITH tool calls still shows the diff correctly"
    - "No OWL props validation errors appear in console when navigating imported traces in debug=assets mode"
  artifacts:
    - path: "ai_debug/static/src/app/detail/iter_detail.xml"
      provides: "Conditional rendering of StateDiff — only mounts component when state data exists"
      contains: "t-if"
    - path: "ai_debug/static/src/app/detail/state_diff.js"
      provides: "StateDiff prop types that accept null values to be safe against edge cases"
      contains: "optional"
  key_links:
    - from: "ai_debug/static/src/app/detail/iter_detail.xml"
      to: "ai_debug/static/src/app/detail/state_diff.js"
      via: "StateDiff component props before/after"
      pattern: "StateDiff"
---

<objective>
Fix the OWL props validation error when clicking the "State Diff" tab on iterations that have no state data.

Purpose: In debug=assets mode, OWL strictly validates component props. The StateDiff component receives `null` for `before`/`after` when iterations have no tool calls, but OWL requires these to be Objects if passed. This causes an OwlError that breaks the UI.

Output: StateDiff renders without errors regardless of whether state data exists.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/iter_detail.js
@ai_debug/static/src/app/detail/iter_detail.xml
@ai_debug/static/src/app/detail/state_diff.js
@ai_debug/static/src/app/detail/state_diff.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Guard StateDiff rendering and fix prop types</name>
  <files>
    ai_debug/static/src/app/detail/iter_detail.xml
    ai_debug/static/src/app/detail/state_diff.js
  </files>
  <action>
Two changes are needed to fix the OWL props validation error:

**1. In `iter_detail.xml` (line 46):** Conditionally render the StateDiff component so it only mounts when at least one of `stateBefore` or `stateAfter` is a real object. When neither exists, show the "No state data" message inline instead.

Replace:
```xml
<StateDiff before="stateBefore" after="stateAfter"/>
```

With:
```xml
<StateDiff t-if="stateBefore or stateAfter"
           before="stateBefore || {}"
           after="stateAfter || {}"/>
<div t-else="" class="ai-diff-empty">
    <span>No state data available.</span>
</div>
```

This ensures:
- StateDiff is never mounted with null/undefined props (avoids the OwlError entirely).
- When mounted, `before` and `after` are always objects (the `|| {}` fallback guarantees this even if only one side has data).
- The "No state data" message still displays for iterations without tool calls.

**2. In `state_diff.js` (lines 7-8):** As a defense-in-depth measure, also allow `null` in the prop type definition so that if any other caller ever passes null, it won't crash. Change:
```js
before: { type: Object, optional: true },
after: { type: Object, optional: true },
```
To:
```js
before: { type: [Object, { value: null }], optional: true },
after: { type: [Object, { value: null }], optional: true },
```

This tells OWL that `before` and `after` can be either an Object or the literal value `null`, and are also optional (can be omitted entirely).

Do NOT modify `iter_detail.js` — the getters returning `null` are fine; the template now handles it.
  </action>
  <verify>
1. Open the AI Debugger app with `?debug=assets` in the URL.
2. Import a trace file.
3. Click on an iteration that has no tool calls.
4. Click the "State Diff" tab — should show "No state data available." with NO console errors.
5. Click on an iteration that DOES have tool calls with state data.
6. Click the "State Diff" tab — should show the diff grid or "No state changes detected" as before.
7. Check browser console — no OwlError about invalid props.
  </verify>
  <done>
StateDiff tab renders without OwlError in debug=assets mode for all iterations, whether or not they have state data. Iterations with state show the diff; iterations without state show the empty message.
  </done>
</task>

</tasks>

<verification>
- No OwlError in console when clicking State Diff tab on any iteration in debug=assets mode
- State diff still works correctly for iterations that have tool calls with state data
- Empty state message appears for iterations without state data
</verification>

<success_criteria>
The OwlError "Invalid props for component 'StateDiff': 'before' is not a object, 'after' is not a object" no longer occurs when navigating traces in debug=assets mode.
</success_criteria>

<output>
After completion, create `.planning/quick/22-fix-statediff-props-validation-error-bef/22-SUMMARY.md`
</output>
