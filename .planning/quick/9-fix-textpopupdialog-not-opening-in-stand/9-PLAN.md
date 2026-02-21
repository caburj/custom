---
phase: quick-9
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/app.xml
autonomous: true
requirements: [QUICK-9]

must_haves:
  truths:
    - "Clicking truncated text in LoopDetail, IterationDetail, or ToolCallDetail opens a TextPopupDialog overlay"
    - "The dialog service resolves successfully (no try/catch fallback to null)"
    - "MainComponentsContainer is present in the DOM when the app renders"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "MainComponentsContainer import and component registration"
      contains: "MainComponentsContainer"
    - path: "ai_debug/static/src/app/app.xml"
      provides: "MainComponentsContainer element in template"
      contains: "<MainComponentsContainer/>"
  key_links:
    - from: "ai_debug/static/src/app/app.js"
      to: "@web/core/main_components_container"
      via: "ES module import"
      pattern: "import.*MainComponentsContainer.*main_components_container"
    - from: "ai_debug/static/src/app/app.xml"
      to: "dialog service overlay rendering"
      via: "MainComponentsContainer component in template"
      pattern: "MainComponentsContainer"
---

<objective>
Fix TextPopupDialog not opening in the standalone AI Debug app.

Purpose: The dialog service's `add()` method has no DOM target because the app template is missing `MainComponentsContainer` -- the Odoo component responsible for rendering dialogs, notifications, and other overlay components. Without it, `useService("dialog")` either fails silently (caught by try/catch) or `dialog.add(...)` has nowhere to mount.

Output: Working dialog popups when users click truncated text in any detail panel.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/app.xml
@ai_debug/static/src/app/detail/loop_detail.js
@ai_debug/static/src/app/detail/iter_detail.js
@ai_debug/static/src/app/detail/tc_detail.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add MainComponentsContainer to standalone app</name>
  <files>ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.xml</files>
  <action>
In app.js:
1. Add import: `import { MainComponentsContainer } from "@web/core/main_components_container";`
   Place it after the existing `@web/core/utils/hooks` import (keep Odoo framework imports grouped together, before local detail imports).
2. Add `MainComponentsContainer` to `static components` alongside LoopDetail, IterationDetail, ToolCallDetail.

In app.xml:
3. Add `<MainComponentsContainer/>` as the LAST child inside the root `<div class="ai-debug-app">`, after the closing `</div>` of `.ai-debug-main` but before the closing `</div>` of `.ai-debug-app`. This follows the exact same placement pattern used by pos_self_order, hr_attendance kiosk, and mrp_subcontracting portal standalone apps.

No changes needed to the detail components (loop_detail.js, iter_detail.js, tc_detail.js). Their existing try/catch around `useService("dialog")` is fine as defensive coding -- with MainComponentsContainer present, the dialog service will now resolve successfully and `this.dialog` will be a working service instance rather than null.
  </action>
  <verify>
1. Run `grep -n "MainComponentsContainer" ai_debug/static/src/app/app.js` -- should show import line and components registration line.
2. Run `grep -n "MainComponentsContainer" ai_debug/static/src/app/app.xml` -- should show the element in the template.
3. Visually inspect that the import path is exactly `@web/core/main_components_container` (not `@web/core/main_components_container/main_components_container` or any other variant).
  </verify>
  <done>
app.js imports MainComponentsContainer from the correct path and registers it in static components. app.xml includes the `<MainComponentsContainer/>` element inside the app root div. The dialog service will now have a DOM container to mount dialogs into, enabling TextPopupDialog to open when users click truncated text.
  </done>
</task>

</tasks>

<verification>
1. Confirm `MainComponentsContainer` appears in both app.js (import + components) and app.xml (template element)
2. The import path matches `@web/core/main_components_container` -- the canonical Odoo import used by all other standalone apps
3. Template placement is inside the root `.ai-debug-app` div, not nested inside `.ai-debug-main`
</verification>

<success_criteria>
- MainComponentsContainer is imported and registered in AiDebugApp
- MainComponentsContainer element is present in app.xml template
- No other files modified (detail components keep their existing try/catch pattern)
</success_criteria>

<output>
After completion, create `.planning/quick/9-fix-textpopupdialog-not-opening-in-stand/9-SUMMARY.md`
</output>
