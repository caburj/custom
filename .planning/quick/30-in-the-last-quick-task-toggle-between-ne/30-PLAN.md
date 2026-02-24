---
phase: 30-indent-mode-tool-call-nesting
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: [INDENT-01]

must_haves:
  truths:
    - "In indentation mode, tool call rows are visually indented deeper than their parent iteration row"
    - "In indentation mode, iteration rows are visually indented deeper than their parent trace row"
    - "Guide lines mode (SVG) is unchanged — no regression"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Per-row-type indent offsets inside .ai-indent-mode"
      contains: "ai-tree-iter-row"
  key_links:
    - from: "ai_debug/static/src/app/app.scss"
      to: "ai_debug/static/src/app/app.xml"
      via: ".ai-indent-mode .ai-tree-iter-row and .ai-tree-tc-row classes already present on rows"
      pattern: "ai-tree-iter-row|ai-tree-tc-row"
---

<objective>
Fix the indentation mode so that tool calls and iterations show proper visual nesting hierarchy, not flat alignment with their parent trace.

Currently, in indent mode, trace/iteration/tool-call rows all share the same `node.depth` value (by design for SVG mode), which means they get identical `padding-left`. The fix adds CSS-only offsets inside `.ai-indent-mode` so that iteration rows indent one step past their trace, and tool call rows indent two steps past their trace.

Purpose: Make the indentation mode actually useful as a hierarchy indicator. Without this, all rows at the same depth level look flat and the nesting relationship between trace > iteration > tool call is invisible.

Output: Modified app.scss with sub-row indentation offsets in the `.ai-indent-mode` block.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.scss
@ai_debug/static/src/app/app.xml
@ai_debug/static/src/app/app.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add per-row-type indent offsets in .ai-indent-mode SCSS block</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
Modify the existing `.ai-indent-mode` block (lines 278-290 in app.scss) to add sub-row indentation for iteration and tool call rows.

The current block sets padding-left based on `ai-depth-N` classes, but all row types (trace, iter, tc) within a trace share the same depth class. In indent mode, we need additional offsets per row type to create the visual hierarchy:

- Trace rows: base indent (current behavior, no change)
- Iteration rows (`.ai-tree-iter-row`): +16px extra (one indent step deeper than trace)
- Tool call rows (`.ai-tree-tc-row`): +32px extra (two indent steps deeper than trace)

Replace the existing `.ai-indent-mode` block with:

```scss
// Indentation nesting mode — replaces SVG guide lines with padding-left per depth
// Within each trace, iterations indent one step past their trace row,
// and tool calls indent two steps past their trace row.
$ai-indent-step: 16px;

.ai-indent-mode {
    .ai-tree-row {
        // Base padding (depth 0 trace) — smaller since no SVG to clear
        padding-left: 8px;
    }

    // Sub-row offsets: iterations +1 step, tool calls +2 steps past trace
    .ai-tree-iter-row {
        padding-left: #{8 + 16}px;  // 24px
    }
    .ai-tree-tc-row {
        padding-left: #{8 + 32}px;  // 40px
    }

    // Progressive depth indentation: each depth level adds 16px to all row types
    @for $d from 1 through 4 {
        .ai-depth-#{$d}.ai-tree-trace-row {
            padding-left: #{8 + $d * 16}px;
        }
        .ai-depth-#{$d}.ai-tree-iter-row {
            padding-left: #{8 + $d * 16 + 16}px;
        }
        .ai-depth-#{$d}.ai-tree-tc-row {
            padding-left: #{8 + $d * 16 + 32}px;
        }
    }
}
```

This produces the hierarchy (at depth 0):
- Trace: 8px
- Iteration: 24px (+16)
- Tool call: 40px (+32)

And at depth 1 (subagent):
- Trace: 24px
- Iteration: 40px
- Tool call: 56px

The extra specificity of `.ai-depth-N.ai-tree-*-row` ensures the compound selector wins over the base `.ai-tree-row` rule. Guide lines mode is completely unaffected because `.ai-indent-mode` is only applied when `nestingMode === 'indent'`.

Important: Do NOT change app.js or app.xml. This is a CSS-only fix. The `node.depth` values staying flat within a trace is correct for SVG mode; we only override padding in indent mode via CSS specificity.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented && grep -A 25 "ai-indent-mode" ai_debug/static/src/app/app.scss | head -30</automated>
    <manual>In browser with indent mode active: iteration rows should be visibly indented past trace rows, and tool call rows should be visibly indented past iteration rows. SVG guide lines mode should look exactly as before.</manual>
  </verify>
  <done>In indentation mode, the visual hierarchy is: trace < iteration (+16px) < tool call (+32px) at every depth level. Guide lines mode is unchanged.</done>
</task>

</tasks>

<verification>
1. Load the AI Debugger app in the browser
2. Switch to indentation mode via the toggle button
3. Expand a trace with iterations and tool calls
4. Confirm: iteration rows are indented one step deeper than the trace row
5. Confirm: tool call rows are indented two steps deeper than the trace row
6. If subagent traces exist (depth > 0), confirm the same relative hierarchy at each depth level
7. Switch back to guide lines mode
8. Confirm: SVG lines render as before, all rows have flat 28px padding (no regression)
</verification>

<success_criteria>
- Indent mode shows clear visual hierarchy: trace > iteration > tool call
- Each row type is offset by 16px from the prior level
- All depth levels (0-4) maintain the same relative offsets
- Guide lines mode is completely unaffected
- No changes to app.js or app.xml
</success_criteria>

<output>
After completion, create `.planning/quick/30-in-the-last-quick-task-toggle-between-ne/30-SUMMARY.md`
</output>
