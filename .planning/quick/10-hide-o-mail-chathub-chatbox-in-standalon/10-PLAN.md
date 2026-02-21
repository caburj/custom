---
phase: quick-10
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-10]
must_haves:
  truths:
    - "The ChatHub floating chatbox is not visible in the standalone ai-debug app"
    - "No mail chat UI elements (ChatHub, ChatBubble) overlay the debug app content"
    - "The mail bus service continues to function (no JS errors from hiding UI)"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: "CSS rule hiding mail chat widgets inside .ai-debug-app"
      contains: "o-mail-ChatHub"
  key_links: []
---

<objective>
Hide the mail module's ChatHub floating chatbox that appears in the standalone AI Debug app.

Purpose: quick-9 added MainComponentsContainer to enable dialog rendering, but it also renders
the mail ChatHub (floating "Ask AI" chatbox) which is inappropriate for the standalone debugger.
A CSS-only fix scoped to .ai-debug-app hides chat widgets without touching JS or breaking bus.

Output: Updated app.scss with chat-hiding rule
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.scss
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add CSS rule to hide mail chat widgets in standalone app</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
At the end of the `.ai-debug-app` root block (after the `font-size: 14px;` line, before the
closing brace), add a nested rule that hides mail chat UI elements:

```scss
    // Hide mail ChatHub and chat bubbles — MainComponentsContainer renders them
    // but they are not relevant in the standalone debugger app
    .o-mail-ChatHub,
    .o-mail-ChatBubble {
        display: none !important;
    }
```

This uses `display: none !important` because the mail module's own styles set display explicitly.
The nesting inside `.ai-debug-app` scopes it so normal backend chat is unaffected.
  </action>
  <verify>
Open the file and confirm:
1. The rule is nested inside `.ai-debug-app { ... }`
2. Both `.o-mail-ChatHub` and `.o-mail-ChatBubble` are targeted
3. `display: none !important` is used
4. A comment explains WHY the rule exists
  </verify>
  <done>
The `.ai-debug-app` block contains a nested CSS rule that hides `.o-mail-ChatHub` and
`.o-mail-ChatBubble` with `display: none !important`, preventing any mail chat UI from
rendering visually in the standalone debugger app.
  </done>
</task>

</tasks>

<verification>
- app.scss parses without syntax errors (valid SCSS nesting)
- The hiding rule is scoped inside `.ai-debug-app` (does not affect backend)
- Both ChatHub and ChatBubble selectors are covered
</verification>

<success_criteria>
The mail ChatHub floating chatbox no longer appears in the standalone AI Debug app at /ai-debug.
The mail bus service still functions without JS errors (CSS hiding does not interfere with JS).
</success_criteria>

<output>
After completion, create `.planning/quick/10-hide-o-mail-chathub-chatbox-in-standalon/10-SUMMARY.md`
</output>
