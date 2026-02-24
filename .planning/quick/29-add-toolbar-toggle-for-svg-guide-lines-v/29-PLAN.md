---
phase: 29-toolbar-toggle-nesting-mode
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/app.xml
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [TOGGLE-01]

must_haves:
  truths:
    - "User can toggle between SVG guide lines and depth-based indentation in the sidebar"
    - "Indentation mode hides SVG guide lines and applies increasing padding-left per depth level"
    - "Guide lines mode shows SVG staircase lines with flat padding (current behavior)"
    - "Preference persists across page refreshes via localStorage"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "nestingMode state, localStorage read/write, toggle method"
      contains: "nestingMode"
    - path: "ai_debug/static/src/app/app.xml"
      provides: "Toggle button in header, conditional SVG rendering, conditional CSS class on tree content"
      contains: "nestingMode"
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Indentation padding rules per depth level"
      contains: "ai-indent-mode"
  key_links:
    - from: "ai_debug/static/src/app/app.xml"
      to: "ai_debug/static/src/app/app.js"
      via: "state.nestingMode read in template, toggleNestingMode click handler"
      pattern: "state\\.nestingMode|toggleNestingMode"
    - from: "ai_debug/static/src/app/app.xml"
      to: "ai_debug/static/src/app/app.scss"
      via: "ai-indent-mode class on .ai-tree-content conditionally applied"
      pattern: "ai-indent-mode"
    - from: "ai_debug/static/src/app/app.js"
      to: "localStorage"
      via: "Read on setup, write on toggle"
      pattern: "localStorage\\.(get|set)Item.*nestingMode"
---

<objective>
Add a toggle button to the sidebar header that switches between two nesting indicator modes:
1. **Guide lines** (default, current behavior): SVG staircase depth lines, flat padding on all rows
2. **Indentation**: Hide SVG guide lines, apply padding-left per depth level (0-4) for visual nesting

Purpose: Give users a choice between the decorative SVG guide lines and a simpler indentation-based hierarchy visualization. Some users prefer clean indentation over graphical lines.

Output: Modified app.js, app.xml, app.scss with toggle button, conditional rendering, and persisted preference.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/app.xml
@ai_debug/static/src/app/app.scss
@ai_debug/implementation-notes/depth-staircase-line.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add nestingMode state with localStorage persistence and toggle method</name>
  <files>ai_debug/static/src/app/app.js</files>
  <action>
In the `setup()` method of `AiDebugApp`:

1. Add `nestingMode` to the `this.state` useState object, initialized from localStorage:
   ```js
   nestingMode: (() => {
       try { return localStorage.getItem("ai_debug.nestingMode") || "lines"; }
       catch { return "lines"; }
   })(),
   ```
   Valid values: `"lines"` (SVG guide lines, default) or `"indent"` (padding-based indentation).

2. Add a `toggleNestingMode()` method to the class (alongside existing user interaction methods like `selectItem`, `toggleExpand`):
   ```js
   toggleNestingMode() {
       this.state.nestingMode = this.state.nestingMode === "lines" ? "indent" : "lines";
       try { localStorage.setItem("ai_debug.nestingMode", this.state.nestingMode); }
       catch { /* private browsing or quota — silently ignore */ }
   }
   ```

Important: Wrap localStorage access in try/catch because the app already handles ephemeral/private-browsing mode gracefully (see probeIDB pattern). The `nestingMode` state drives both the SVG visibility and the CSS class in the template.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented && grep -n "nestingMode" ai_debug/static/src/app/app.js | head -20</automated>
    <manual>Confirm nestingMode appears in state initialization and toggleNestingMode method exists</manual>
  </verify>
  <done>app.js has nestingMode in state (defaulting to "lines" from localStorage), and a toggleNestingMode() method that flips between "lines"/"indent" and persists to localStorage</done>
</task>

<task type="auto">
  <name>Task 2: Add toggle button to header and conditional SVG/indentation class in template</name>
  <files>ai_debug/static/src/app/app.xml</files>
  <action>
Three changes to the template:

1. **Toggle button in `.ai-tree-header-actions`** — Add a button BEFORE the existing export/import/delete buttons (since it's a view mode toggle, not a destructive action). Place it as the first child of `ai-tree-header-actions`:
   ```xml
   <button class="ai-tree-action-btn ai-tree-nesting-toggle"
           t-on-click="toggleNestingMode"
           t-att-title="state.nestingMode === 'lines' ? 'Switch to indentation' : 'Switch to guide lines'">
       <t t-if="state.nestingMode === 'lines'">&#x2502;</t>
       <t t-else="">&#x2261;</t>
   </button>
   ```
   The Unicode characters: `&#x2502;` is a vertical box-drawing line (representing guide lines mode), `&#x2261;` is the identical-to/triple-bar symbol (representing indentation mode). These are visually distinct and communicate the current state.

2. **Conditional SVG rendering** — Change the existing SVG `t-if` from:
   ```xml
   <svg t-if="sidebarNodes.length > 0"
   ```
   to:
   ```xml
   <svg t-if="sidebarNodes.length > 0 and state.nestingMode === 'lines'"
   ```
   This hides the SVG depth lines entirely when in indent mode.

3. **Conditional CSS class on `.ai-tree-content`** — Change:
   ```xml
   <div class="ai-tree-content" t-ref="sidebar">
   ```
   to:
   ```xml
   <div t-attf-class="ai-tree-content {{ state.nestingMode === 'indent' ? 'ai-indent-mode' : '' }}" t-ref="sidebar">
   ```
   The `ai-indent-mode` class activates the depth-based padding rules in SCSS.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented && grep -n "nestingMode\|ai-indent-mode\|toggleNestingMode\|nesting-toggle" ai_debug/static/src/app/app.xml</automated>
    <manual>Confirm toggle button appears in header, SVG has conditional nestingMode check, tree-content has conditional ai-indent-mode class</manual>
  </verify>
  <done>Template has a toggle button in the header actions, SVG only renders when nestingMode is "lines", and .ai-tree-content gets .ai-indent-mode class when nestingMode is "indent"</done>
</task>

<task type="auto">
  <name>Task 3: Add indentation-mode SCSS rules with per-depth padding</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
Add indentation mode styles. Place them after the existing depth color rules (after the `@each $depth, $color in $ai-depth-colors` block, around line 276).

1. **Indentation mode rules** — When `.ai-indent-mode` is on the `.ai-tree-content` container, override the flat padding with depth-based indentation:
   ```scss
   // Indentation nesting mode — replaces SVG guide lines with padding-left per depth
   .ai-indent-mode {
       .ai-tree-row {
           // Base padding (depth 0) — smaller since no SVG to clear
           padding-left: 8px;
       }

       // Progressive indentation: 16px per depth level
       @for $d from 1 through 4 {
           .ai-depth-#{$d} {
               padding-left: #{8 + $d * 16}px;
           }
       }
   }
   ```
   This produces: depth-0 = 8px, depth-1 = 24px, depth-2 = 40px, depth-3 = 56px, depth-4 = 72px. The existing `.ai-depth-N` background tints are preserved (they are defined separately and stack naturally).

2. **Toggle button styling** — Add after the `.ai-tree-action-btn` rules (around line 425):
   ```scss
   // Nesting mode toggle — visual distinction from destructive action buttons
   .ai-tree-nesting-toggle {
       font-family: "SF Mono", "Fira Code", "Consolas", monospace;
       font-size: 14px;
       font-weight: 600;

       &:hover:not(:disabled) {
           color: $o-action;
           background: rgba($o-action, 0.08);
       }
   }
   ```
   The hover color uses `$o-action` (blue) instead of `$o-danger` (red) since this is a mode toggle, not a destructive action.

Important: The existing `.ai-depth-N` background-color rules (lines 271-275) remain unchanged — they provide the subtle color tints regardless of nesting mode. The indentation rules ONLY override `padding-left`.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented && grep -n "ai-indent-mode\|ai-tree-nesting-toggle" ai_debug/static/src/app/app.scss</automated>
    <manual>Confirm .ai-indent-mode block exists with per-depth padding rules, and .ai-tree-nesting-toggle has proper hover styling</manual>
  </verify>
  <done>SCSS has .ai-indent-mode rules that override padding-left per depth (0-4), and .ai-tree-nesting-toggle hover uses blue action color instead of red danger color</done>
</task>

</tasks>

<verification>
1. Load the AI Debugger app in the browser
2. Verify the toggle button appears in the sidebar header (left of export/import/delete buttons)
3. Default state should show SVG guide lines (current behavior unchanged)
4. Click the toggle: SVG lines disappear, rows indent progressively by depth level
5. Click again: SVG lines reappear, rows return to flat padding
6. Refresh the page: the last selected mode persists
7. Test with subagent traces (depth > 0) to confirm indentation is visually clear
</verification>

<success_criteria>
- Toggle button is visible and functional in the sidebar header
- Guide lines mode matches current behavior exactly (no regression)
- Indentation mode hides SVG, applies progressive padding-left per depth
- Depth background tints are preserved in both modes
- Preference survives page refresh via localStorage
- Private browsing / ephemeral mode degrades gracefully (defaults to "lines", no errors)
</success_criteria>

<output>
After completion, create `.planning/quick/29-add-toolbar-toggle-for-svg-guide-lines-v/29-SUMMARY.md`
</output>
