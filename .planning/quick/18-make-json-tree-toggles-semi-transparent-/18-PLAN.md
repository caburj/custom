---
phase: quick-18
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
---

<objective>
Make JSON tree toggle buttons semi-transparent (opacity 0.35) by default, full opacity on hover.
</objective>

<tasks>
<task type="auto">
  <name>Add opacity transition to toggles</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>Add opacity: 0.35 and transition to .ai-json-toggle, opacity: 1 on hover.</action>
  <done>Toggles fade in on hover.</done>
</task>
</tasks>
