---
phase: quick-13
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [FIX-BG]
must_haves:
  truths:
    - "Short string tool results display with dark background matching the rest of the app"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: ".ai-detail-text-block with background-color"
      contains: "background-color: #181825"
  key_links: []
---

<objective>
Fix white background on `.ai-detail-text-block` elements (short string tool results) by adding the standard dark background color.

Purpose: Bootstrap's default `<pre>` background bleeds through as white/light on the dark-themed standalone app. One missing CSS property.
Output: Updated app.scss with background-color on .ai-detail-text-block
</objective>

<context>
@ai_debug/static/src/app/app.scss (lines 457-468, the .ai-detail-text-block rule)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add background-color to .ai-detail-text-block</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
    In the `.ai-detail-text-block` rule block (around line 457-468), add `background-color: #181825;` after the existing `padding: 8px;` line. This matches the standard dark background used by `.ai-diff-snapshot` and other dark-themed blocks in the same file (5 existing usages of #181825).
  </action>
  <verify>
    grep -A 12 'ai-detail-text-block' ai_debug/static/src/app/app.scss | grep 'background-color: #181825'
  </verify>
  <done>
    .ai-detail-text-block includes background-color: #181825 — short string results render with dark background instead of Bootstrap's default white.
  </done>
</task>

</tasks>

<verification>
grep confirms background-color: #181825 present inside .ai-detail-text-block rule.
</verification>

<success_criteria>
The .ai-detail-text-block CSS rule includes background-color: #181825, eliminating the white background on short string tool results.
</success_criteria>

<output>
After completion, create `.planning/quick/13-fix-white-background-on-short-string-res/13-SUMMARY.md`
</output>
