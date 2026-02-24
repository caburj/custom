---
phase: quick-34
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.xml
autonomous: true
requirements: [QUICK-34]
must_haves:
  truths:
    - "Sidebar token display shows up arrow after input tokens and down arrow after output tokens"
    - "Format reads like '1.2k up-arrow 800 down-arrow' instead of '1.2k right-arrow 800'"
  artifacts:
    - path: "ai_debug/static/src/app/app.xml"
      provides: "Updated token display format in sidebar trace meta line"
      contains: "\\u2191.*\\u2193"
  key_links: []
---

<objective>
Change the sidebar token display format from "input->output" to "input^ output v" using Unicode arrows.

Purpose: Make the token direction clearer — up arrow for input (tokens sent to model), down arrow for output (tokens received back).
Output: Updated app.xml template with new arrow format.
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
  <name>Task 1: Change sidebar token format to use directional arrows</name>
  <files>ai_debug/static/src/app/app.xml</files>
  <action>
On line 118 of app.xml, change the token display from:

```xml
&#xB7; <t t-esc="this.formatTokens(totals.total_input)"/>&#x2192;<t t-esc="this.formatTokens(totals.total_output)"/>
```

To use up arrow (U+2191) after input and down arrow (U+2193) after output:

```xml
&#xB7; <t t-esc="this.formatTokens(totals.total_input)"/>&#x2191; <t t-esc="this.formatTokens(totals.total_output)"/>&#x2193;
```

This changes the visual from "1.2k->800" to "1.2k^ 800v" (using proper Unicode arrows).

Only this one line changes. The other token displays are either:
- Total-only (app.xml line 121, iter_detail.xml line 17) — no input/output distinction, keep "tok" suffix
- Table columns (loop_detail.xml) — already labeled with column headers, arrows not needed
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro &amp;&amp; grep -c '&#x2191;' ai_debug/static/src/app/app.xml &amp;&amp; grep -c '&#x2193;' ai_debug/static/src/app/app.xml &amp;&amp; ! grep '&#x2192;' ai_debug/static/src/app/app.xml</automated>
    <manual>Open AI Debugger, trigger a trace, verify sidebar shows "1.2k^ 800v" format with directional arrows</manual>
  </verify>
  <done>Sidebar token display uses up arrow after input tokens and down arrow after output tokens. No right arrow remains in token display.</done>
</task>

</tasks>

<verification>
- app.xml contains U+2191 (up arrow) for input tokens
- app.xml contains U+2193 (down arrow) for output tokens
- app.xml no longer contains U+2192 (right arrow) in token display context
- Other token displays (iter_detail.xml, loop_detail.xml) are unchanged
</verification>

<success_criteria>
Sidebar trace meta line displays token counts as "Xk^ Y v" with directional arrows indicating input (up) and output (down).
</success_criteria>

<output>
After completion, create `.planning/quick/34-change-token-display-format-to-use-up-do/34-SUMMARY.md`
</output>
