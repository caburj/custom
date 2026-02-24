---
phase: quick-31
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements:
  - QUICK-31
must_haves:
  truths:
    - "A child trace at depth 1 has more left padding than a tool-call row at depth 0"
    - "Indentation increases visibly with each depth level for all three row types"
    - "Depth-0 rows (trace=8px, iter=24px, tc=40px) are unchanged"
  artifacts:
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Corrected per-depth multiplier in .ai-indent-mode @for loop"
      contains: "$d * 48"
  key_links:
    - from: ".ai-depth-1.ai-tree-trace-row"
      to: "padding-left: 56px"
      via: "8 + 1*48 = 56"
      pattern: "\\$d \\* 48"
---

<objective>
Fix the per-depth multiplier in the `.ai-indent-mode` SCSS block so that nested child traces are indented further right than their parent tool-call rows.

Purpose: The current multiplier of 16px per depth means a child trace at depth 1 (24px) has LESS padding than a tool-call row at depth 0 (40px), making the hierarchy visually inverted.

Output: Updated `app.scss` where each depth level shifts by 48px (3 × $ai-indent-step), ensuring D1 trace (56px) sits one clear step past D0 tool-call (40px).
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Change per-depth multiplier from 16 to 48 in indentation mode SCSS</name>
  <files>ai_debug/static/src/app/app.scss</files>
  <action>
Replace the `@for` loop inside `.ai-indent-mode` (lines 296-307) with the corrected multiplier.

Current block (lines 296-307):
```scss
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
```

Replace with:
```scss
    // Progressive depth indentation: each depth level shifts by 3 steps (48px) so
    // a child trace at depth N+1 sits one step (16px) past the tool-call row at
    // depth N. Resulting values:
    //   D0: trace=8, iter=24, tc=40
    //   D1: trace=56, iter=72, tc=88
    //   D2: trace=104, iter=120, tc=136
    @for $d from 1 through 4 {
        .ai-depth-#{$d}.ai-tree-trace-row {
            padding-left: #{8 + $d * 48}px;
        }
        .ai-depth-#{$d}.ai-tree-iter-row {
            padding-left: #{8 + $d * 48 + 16}px;
        }
        .ai-depth-#{$d}.ai-tree-tc-row {
            padding-left: #{8 + $d * 48 + 32}px;
        }
    }
```

Only this block changes. The base `.ai-tree-row`, `.ai-tree-iter-row`, and `.ai-tree-tc-row` rules at depth 0 (lines 283-294) remain untouched.
  </action>
  <verify>
    <automated>grep -n "\$d \* 48" /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented/ai_debug/static/src/app/app.scss</automated>
    <manual>In the browser with indentation mode enabled and a multi-agent trace open, confirm that sub-agent trace rows are indented further right than the tool-call rows that spawned them.</manual>
  </verify>
  <done>The `@for` loop uses `$d * 48` as the multiplier. Grep confirms three matching lines (one per row type). No `$d * 16` patterns remain inside the loop.</done>
</task>

</tasks>

<verification>
grep -n "\$d \* 48" /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented/ai_debug/static/src/app/app.scss
# Expected: 3 lines containing "$d * 48"

grep -n "\$d \* 16" /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro-indented/ai_debug/static/src/app/app.scss
# Expected: 0 lines (no remaining $d * 16 inside the loop)
</verification>

<success_criteria>
- `$d * 48` appears exactly 3 times in app.scss (one per row type in the @for loop)
- `$d * 16` no longer appears in the file (old multiplier fully replaced)
- Depth-0 padding values (8px trace, 24px iter, 40px tc) are unchanged
- D1 trace padding (56px) exceeds D0 tc padding (40px) by 16px
</success_criteria>

<output>
After completion, create `.planning/quick/31-fix-nested-trace-indentation-under-tool-/31-SUMMARY.md`
</output>
