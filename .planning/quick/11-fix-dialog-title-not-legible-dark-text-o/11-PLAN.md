---
phase: quick-11
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-11]

must_haves:
  truths:
    - "Dialog title text is clearly legible (light text) on the dark modal header"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Explicit .modal-title color rule inside .o_dialog .modal-header"
      contains: ".modal-title"
  key_links:
    - from: "ai_debug/static/src/app/app.scss"
      to: ".modal-title element in TextPopupDialog"
      via: "CSS specificity override"
      pattern: "\\.modal-title.*color.*#cdd6f4"
---

<objective>
Fix the dialog title being illegible (dark text on dark background) in TextPopupDialog.

Purpose: The `.modal-header` block sets `color: #cdd6f4` but Bootstrap's `.modal-title` class has its own explicit `color` property at higher specificity, resulting in dark text on the dark header background.
Output: Legible light-colored dialog title text.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.scss (lines 616-633 — dialog dark theme overrides)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add explicit .modal-title color rule to dialog dark theme overrides</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
In `ai_debug/static/src/app/app.scss`, inside the existing `.o_dialog .modal-header` block (lines 624-632), add an explicit `.modal-title` rule with `color: #cdd6f4`.

The `.modal-header` block currently has `color: #cdd6f4` set on itself, but Bootstrap's `.modal-title` class defines its own explicit `color` property which wins by specificity over inherited color. Adding `.modal-title { color: #cdd6f4; }` as a nested rule inside `.modal-header` produces the selector `.o_dialog .modal-header .modal-title` which has sufficient specificity to override Bootstrap.

The result should look like:

```scss
.modal-header {
    background-color: #181825;
    border-bottom-color: #313244;
    color: #cdd6f4;

    .modal-title {
        color: #cdd6f4;
    }

    .btn-close {
        filter: invert(1);
    }
}
```

Do NOT move or restructure the surrounding code. Only add the `.modal-title` nested rule.
  </action>
  <verify>
1. Grep the file to confirm the `.modal-title` rule exists inside the `.modal-header` block:
   `grep -A2 '.modal-title' ai_debug/static/src/app/app.scss`
2. Open the standalone app, trigger a TextPopupDialog (click a long text value in detail panel), and verify the dialog title is clearly legible light text on the dark header.
  </verify>
  <done>The `.modal-title` element inside `.o_dialog .modal-header` has `color: #cdd6f4` applied, making the dialog title text clearly legible against the dark header background.</done>
</task>

</tasks>

<verification>
- The dialog title text renders as light catppuccin text (#cdd6f4) on the dark header (#181825)
- No other dialog styling is broken by this change
</verification>

<success_criteria>
Dialog title in TextPopupDialog is clearly legible — light text on dark header background.
</success_criteria>

<output>
After completion, create `.planning/quick/11-fix-dialog-title-not-legible-dark-text-o/11-SUMMARY.md`
</output>
