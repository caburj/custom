---
phase: quick-17
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-17]
---

<objective>
Make JSON tree toggle buttons (+/−) more subtle: lighter background with border instead of solid fill.
</objective>

<tasks>
<task type="auto">
  <name>Soften toggle button styling</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>Replace solid $o-gray-400 background with $o-gray-200 fill + 1px $o-gray-400 border. Soften text to $o-gray-500. Hover: action-tinted bg/border/text.</action>
  <done>Toggle buttons are subtle with light fill and border.</done>
</task>
</tasks>
