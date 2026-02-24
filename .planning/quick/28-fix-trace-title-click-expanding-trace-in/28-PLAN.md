---
phase: quick-28
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
autonomous: true
requirements: [QUICK-28]

must_haves:
  truths:
    - "Clicking the trace title (user_query text) opens the full-text dialog without expanding/collapsing the trace"
    - "Clicking the trace title when the trace is already expanded opens the dialog and leaves the trace expanded"
    - "Clicking the label area outside the title text still selects and expands the trace as before"
    - "Clicking the chevron still toggles expand/collapse as before"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "showFullQuery with stopPropagation to prevent bubble to selectItem"
      contains: "stopPropagation"
  key_links:
    - from: "ai_debug/static/src/app/app.xml line 100"
      to: "showFullQuery in app.js"
      via: "t-on-click with ev.stopPropagation"
      pattern: "stopPropagation"
---

<objective>
Fix bug where clicking a trace's title (user_query text) in the sidebar expands the trace in addition to opening the full-text dialog.

Purpose: The title click should only open the TextPopupDialog. The expand side-effect occurs because the click event bubbles from the inner `ai-tree-query-title` span up to the parent `ai-tree-label` span, which calls `selectItem()`. `selectItem('trace')` unconditionally sets `trace.expanded = true`, causing a collapsed trace to expand.

Output: Patched `showFullQuery` method that stops event propagation so the click does not reach `selectItem`.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/app.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Stop click propagation in showFullQuery to prevent trace expansion</name>
  <files>ai_debug/static/src/app/app.js</files>
  <action>
In `showFullQuery(_ev, query)` (around line 393), add `_ev.stopPropagation()` as the first line of the method body, BEFORE the early-return guard. This prevents the click from bubbling up to the parent `ai-tree-label` span's `selectItem` handler.

Change:
```js
showFullQuery(_ev, query) {
    if (!this.dialog || !query) return;
```

To:
```js
showFullQuery(ev, query) {
    ev.stopPropagation();
    if (!this.dialog || !query) return;
```

Note: Also rename `_ev` to `ev` since it is now used (the underscore prefix conventionally signals "unused parameter").

Do NOT modify `selectItem`, the template, or any other method. The template already passes `(ev)` to `showFullQuery` on line 100 of app.xml — no template changes needed.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro && grep -n "stopPropagation" ai_debug/static/src/app/app.js && grep -n "showFullQuery(ev," ai_debug/static/src/app/app.js</automated>
    <manual>In the AI Debugger, with a collapsed trace that has a user_query title: (1) Click the title text — dialog should open, trace should remain collapsed. (2) Expand the trace via chevron, click the title again — dialog should open, trace should stay expanded. (3) Click the label area outside the title — trace should select and expand as before.</manual>
  </verify>
  <done>showFullQuery calls ev.stopPropagation() before any other logic; clicking a trace title opens the dialog without triggering selectItem (and thus without expanding a collapsed trace)</done>
</task>

</tasks>

<verification>
- `grep -n "stopPropagation" ai_debug/static/src/app/app.js` returns the line inside showFullQuery
- `grep -n "_ev" ai_debug/static/src/app/app.js` does NOT match showFullQuery (parameter renamed to `ev`)
- No other methods in app.js were modified
</verification>

<success_criteria>
- Clicking the trace title in the sidebar opens the full-text popup dialog without expanding/collapsing the trace
- All other click behaviors (chevron expand/collapse, label select, checkbox toggle) remain unchanged
</success_criteria>

<output>
After completion, create `.planning/quick/28-fix-trace-title-click-expanding-trace-in/28-SUMMARY.md`
</output>
