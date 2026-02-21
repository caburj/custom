---
phase: quick-12
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/tc_detail.js
  - ai_debug/static/src/app/detail/tc_detail.xml
autonomous: true
requirements: [QUICK-12]
must_haves:
  truths:
    - "Short string results (<= 300 chars) render inline as before with ai-detail-text-block"
    - "Long string results (> 300 chars) render truncated with max-height and overflow hidden"
    - "Clicking a truncated long result opens the full text in TextPopupDialog"
  artifacts:
    - path: "ai_debug/static/src/app/detail/tc_detail.js"
      provides: "resultIsLong getter and onResultClick handler"
    - path: "ai_debug/static/src/app/detail/tc_detail.xml"
      provides: "Conditional truncated preview vs full inline rendering"
  key_links:
    - from: "tc_detail.xml"
      to: "tc_detail.js"
      via: "resultIsLong getter controls which branch renders; t-on-click calls openTextPopup"
      pattern: "resultIsLong.*openTextPopup"
---

<objective>
Fix tool call Result rendering for long string results by adding truncation with click-to-expand.

Purpose: Long string results (like ai_get_fields pipe-delimited tables) currently dump the entire text inline with no max-height or overflow, making the Result section overwhelmingly long. This reuses the existing `ai-detail-text-preview` CSS class and `openTextPopup()` pattern already used in loop_detail.xml.

Output: Tool call string results > 300 chars show as truncated previews that open in TextPopupDialog on click; short results remain unchanged.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/tc_detail.js
@ai_debug/static/src/app/detail/tc_detail.xml
@ai_debug/static/src/app/detail/loop_detail.xml (reference pattern for ai-detail-text-preview + openTextPopup)
@ai_debug/static/src/app/app.scss (ai-detail-text-preview CSS already exists at lines 436-454)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add resultIsLong getter and conditional truncated/full rendering</name>
  <files>
    ai_debug/static/src/app/detail/tc_detail.js
    ai_debug/static/src/app/detail/tc_detail.xml
  </files>
  <action>
In tc_detail.js, add a `resultIsLong` getter that returns `true` when the result is NOT an object and `resultString.length > 300`. This matches JsonTree's TRUNCATION_THRESHOLD of 300.

```js
get resultIsLong() {
    return !this.resultIsObject && this.resultString.length > 300;
}
```

No other JS changes needed. The existing `openTextPopup(title, content, language)` method and `resultString` getter handle everything else. The popup will be opened with the title "Result", full `resultString` content, and language "markdown".

In tc_detail.xml, replace the current `t-else` block (lines 34-36):

```xml
<t t-else="">
    <pre class="ai-detail-text-block" t-esc="resultString"/>
</t>
```

With a conditional that checks `resultIsLong`:

```xml
<t t-else="">
    <t t-if="resultIsLong">
        <div class="ai-detail-text-preview"
             t-on-click="() => this.openTextPopup('Result', this.resultString, 'markdown')"
             t-esc="resultString"/>
    </t>
    <t t-else="">
        <pre class="ai-detail-text-block" t-esc="resultString"/>
    </t>
</t>
```

Key details:
- Use `<div class="ai-detail-text-preview">` (NOT `<pre>`) — this matches the exact pattern from loop_detail.xml lines 22-24 and 46-48.
- Pass full `resultString` via `t-esc` (the CSS class handles visual truncation via max-height:120px + overflow:hidden).
- The `ai-detail-text-preview` class already provides: cursor:pointer, max-height:120px, overflow:hidden, hover border highlight. No CSS changes needed.
- Short results (<= 300 chars) keep the existing `<pre class="ai-detail-text-block">` rendering — no behavior change.
  </action>
  <verify>
1. Open the AI Debug standalone app, trigger a tool call with a long string result (e.g., ai_get_fields).
2. Confirm the Result section shows truncated with max-height and overflow hidden.
3. Click on the truncated result — TextPopupDialog should open with full text.
4. Trigger a tool call with a short string result — confirm it renders inline as a `<pre>` block without truncation.
  </verify>
  <done>
Long string tool results (> 300 chars) render as clickable truncated previews using the ai-detail-text-preview class; clicking opens the full text in TextPopupDialog. Short string results render unchanged as ai-detail-text-block pre elements.
  </done>
</task>

</tasks>

<verification>
- Long string results truncated visually (max-height 120px, overflow hidden)
- Click on truncated result opens TextPopupDialog with full content
- Short string results render inline unchanged
- Object/array results still render via JsonTree (no regression)
</verification>

<success_criteria>
Tool call string results > 300 chars display as truncated clickable previews; short results and object results render as before.
</success_criteria>

<output>
After completion, create `.planning/quick/12-fix-tool-result-styling-add-truncation-a/12-SUMMARY.md`
</output>
