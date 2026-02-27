---
phase: quick-39
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/text_popup.js
  - ai_debug/static/src/app/detail/text_popup.xml
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [QUICK-39]

must_haves:
  truths:
    - "Text popup dialog has a toolbar with a text-wrap toggle button and a copy button"
    - "Clicking the wrap toggle switches between wrapped (pre-wrap) and unwrapped (nowrap + horizontal scroll) display"
    - "Clicking the copy button copies the full raw text content to the clipboard"
    - "Wrap state defaults to wrapped (current behavior preserved)"
  artifacts:
    - path: "ai_debug/static/src/app/detail/text_popup.js"
      provides: "TextPopupDialog with useState for wrap toggle and copy-to-clipboard method"
      exports: ["TextPopupDialog"]
    - path: "ai_debug/static/src/app/detail/text_popup.xml"
      provides: "Template with toolbar containing wrap toggle and copy button"
      contains: "ai_debug.TextPopupDialog"
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Styles for popup toolbar and nowrap mode"
      contains: "ai-popup-toolbar"
  key_links:
    - from: "ai_debug/static/src/app/detail/text_popup.xml"
      to: "ai_debug/static/src/app/detail/text_popup.js"
      via: "OWL template binding for state.wrap and onCopy/toggleWrap handlers"
      pattern: "state\\.wrap|toggleWrap|onCopy"
---

<objective>
Add a toolbar to the TextPopupDialog with two controls: (1) a toggle button to switch between wrapped and unwrapped text display, and (2) a button to copy the full text content to the clipboard.

Purpose: When viewing large text blobs (system prompts, JSON payloads, tool results), users need to toggle text wrapping for readability vs horizontal scrolling for preserving formatting, and need a quick way to copy the full content.

Output: Updated TextPopupDialog component with toolbar, wrap toggle state, and copy button.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/text_popup.js
@ai_debug/static/src/app/detail/text_popup.xml
@ai_debug/static/src/app/app.scss

<interfaces>
From Odoo's Dialog component (web/static/src/core/dialog/dialog.js):
- Props: title (String), size (String: sm|md|lg|xl|fs), header (Boolean), footer (Boolean), slots: { default, header?, footer? }
- The Dialog renders a default slot as `<main class="modal-body">` content
- Footer slot available via `<t t-set-slot="footer">`

Current TextPopupDialog props:
```javascript
static props = {
    title: String,
    content: String,
    language: { type: String, optional: true },
    close: Function,
};
```

CopyButton from @web/core/copy_button/copy_button:
```javascript
static props = {
    className: { type: String, optional: true },
    copyText: { type: String, optional: true },
    content: { type: [String, Object, Function], optional: true },
    icon: { type: String, optional: true },
};
```
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add wrap toggle and copy button to TextPopupDialog</name>
  <files>
    ai_debug/static/src/app/detail/text_popup.js
    ai_debug/static/src/app/detail/text_popup.xml
    ai_debug/static/src/app/app.scss
  </files>
  <action>
**text_popup.js** — Update the component:

1. Import `useState` from `@odoo/owl` (add to existing import).
2. Import `CopyButton` from `@web/core/copy_button/copy_button`.
3. Add `CopyButton` to `static components = { Dialog, CopyButton }`.
4. In `setup()`, add reactive state: `this.state = useState({ wrap: true })` (default to wrapped, preserving current behavior).
5. Add a `toggleWrap()` method that flips `this.state.wrap`.
6. After Prism highlighting runs in `onMounted`, also update the `<pre>` element class based on initial wrap state (no action needed since CSS default will be `pre-wrap`).

**text_popup.xml** — Restructure the template:

Replace the current simple `<pre><code>` structure with a layout that has a toolbar above the code block. The toolbar goes INSIDE the Dialog default slot, above the `<pre>` block:

```xml
<t t-name="ai_debug.TextPopupDialog">
    <Dialog title="props.title" size="'xl'">
        <div class="ai-popup-toolbar">
            <button class="btn btn-sm"
                    t-attf-class="ai-popup-toolbar-btn {{ state.wrap ? 'active' : '' }}"
                    t-on-click="toggleWrap"
                    title="Toggle text wrapping">
                <i class="fa fa-align-left"/> Wrap
            </button>
            <CopyButton content="props.content"
                        className="'btn-sm ai-popup-toolbar-btn'"
                        copyText="'Copy'"
                        successText="'Copied!'"
                        icon="'fa-clone'"/>
        </div>
        <pre t-attf-class="ai-popup-content {{ state.wrap ? '' : 'ai-popup-nowrap' }}"><code t-ref="codeEl" t-attf-class="language-{{props.language or 'json'}}"/></pre>
    </Dialog>
</t>
```

**app.scss** — Add toolbar and nowrap styles. Place them after the existing `.ai-popup-content` rule (around line 899):

```scss
// Text popup toolbar (wrap toggle + copy button)
.ai-popup-toolbar {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 8px;
    padding-bottom: 8px;
    border-bottom: 1px solid $border-color;
}

.ai-popup-toolbar-btn {
    font-size: 12px;
    padding: 2px 8px;
    border: 1px solid $border-color;
    border-radius: 4px;
    background: transparent;
    color: $o-gray-600;
    cursor: pointer;
    transition: all 0.15s ease;

    &:hover {
        background: rgba($o-action, 0.08);
        color: $o-action;
        border-color: $o-action;
    }

    &.active {
        background: rgba($o-action, 0.12);
        color: $o-action;
        border-color: $o-action;
    }
}

// Unwrapped mode: no wrapping, horizontal scroll
.ai-popup-content.ai-popup-nowrap {
    white-space: pre;
    word-break: normal;
    overflow-x: auto;
}
```

NOTE: The existing `.ai-popup-content` already has `white-space: pre-wrap` and `word-break: break-word` which serves as the wrapped (default) state. The `.ai-popup-nowrap` modifier overrides these to `pre` and `normal` for unwrapped display with horizontal scrolling.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro && grep -q "useState" ai_debug/static/src/app/detail/text_popup.js && grep -q "toggleWrap" ai_debug/static/src/app/detail/text_popup.js && grep -q "CopyButton" ai_debug/static/src/app/detail/text_popup.js && grep -q "ai-popup-toolbar" ai_debug/static/src/app/detail/text_popup.xml && grep -q "ai-popup-nowrap" ai_debug/static/src/app/app.scss && echo "PASS" || echo "FAIL"</automated>
  </verify>
  <done>
    - TextPopupDialog has a toolbar with a "Wrap" toggle button and a "Copy" button
    - Clicking "Wrap" toggles between pre-wrap (default) and pre/nowrap with horizontal scroll
    - The "Wrap" button shows active styling when wrapping is enabled
    - Clicking "Copy" copies the full raw text to clipboard (via Odoo's CopyButton)
    - Default state is wrapped (preserves existing behavior)
    - Toolbar is visually separated from content by a border
  </done>
</task>

</tasks>

<verification>
1. Open the AI Debug standalone app
2. Select a trace/iteration/tool call with content
3. Click a truncated text preview to open TextPopupDialog
4. Verify toolbar appears with "Wrap" and "Copy" buttons
5. Verify text is wrapped by default (matches previous behavior)
6. Click "Wrap" toggle — text should switch to unwrapped with horizontal scroll for long lines
7. Click "Wrap" again — text should return to wrapped mode
8. Click "Copy" — clipboard should contain the full text content
</verification>

<success_criteria>
TextPopupDialog displays a toolbar with wrap toggle and copy button. Wrap toggle switches between `pre-wrap` (default) and `pre` with horizontal scroll. Copy button copies full raw text to clipboard via Odoo's CopyButton component.
</success_criteria>

<output>
After completion, create `.planning/quick/39-when-showing-the-popup-to-display-the-fu/39-SUMMARY.md`
</output>
