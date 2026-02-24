---
phase: quick
plan: 33
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.xml
  - ai_debug/static/src/app/app.scss
autonomous: true
requirements: []
must_haves:
  truths:
    - "Sidebar trace rows show agent name, model, duration, and tokens all on ONE line (the meta line)"
    - "The separate .ai-tree-metrics-line row is completely removed"
    - "Trace rows are visually compact — no extra vertical space from the removed line"
    - "Metrics only appear when data exists (duration > 0 or tokens > 0), same conditional as before"
  artifacts:
    - path: "ai_debug/static/src/app/app.xml"
      provides: "Inlined metrics in .ai-tree-meta-line, no .ai-tree-metrics-line element"
    - path: "ai_debug/static/src/app/app.scss"
      provides: "Updated .ai-tree-meta-line styles, removed .ai-tree-metrics-line rule"
  key_links:
    - from: "ai_debug/static/src/app/app.xml"
      to: "ai_debug/static/src/app/app.js"
      via: "getTraceTotals, formatDuration, formatTokens calls unchanged"
      pattern: "this\\.getTraceTotals|this\\.formatDuration|this\\.formatTokens"
---

<objective>
Inline the sidebar trace metrics (duration and token counts) into the agent name/model meta line, removing the separate metrics row.

Purpose: Make trace rows more compact by combining all metadata onto one line: "AgentName . model-name . 2.1s . 3.4k->1.2k tok"
Output: Updated app.xml template and app.scss styles; no JS changes needed (same getTraceTotals/formatDuration/formatTokens calls).
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.xml
@ai_debug/static/src/app/app.scss
@ai_debug/static/src/app/app.js (for getTraceTotals, formatDuration, formatTokens bindings — read-only)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Inline metrics into meta line and remove metrics row</name>
  <files>ai_debug/static/src/app/app.xml, ai_debug/static/src/app/app.scss</files>
  <action>
In app.xml, within the trace row template (the `t-if="node.type === 'trace'"` block), make these changes:

1. **Move `t-set="totals"` ABOVE the `.ai-tree-meta-line` span** (currently at line 115, move it before the meta-line span at line 112). It must be computed before the meta-line renders.

2. **Replace the `.ai-tree-meta-line` span** (currently line 112-114) with a new version that inlines the metrics. The new content should be:

```xml
<span class="ai-tree-meta-line">
    <t t-esc="node.trace.agent_name or 'Agent'"/> &#xB7; <t t-esc="node.trace.model_name or ''"/>
    <t t-if="totals.total_duration_ms > 0 or totals.total_tokens > 0">
        &#xB7; <t t-esc="this.formatDuration(totals.total_duration_ms)"/>
        <t t-if="totals.total_input > 0 and totals.total_output > 0">
            &#xB7; <t t-esc="this.formatTokens(totals.total_input)"/>&#x2192;<t t-esc="this.formatTokens(totals.total_output)"/>
        </t>
        <t t-elif="totals.total_tokens > 0">
            &#xB7; <t t-esc="this.formatTokens(totals.total_tokens)"/> tok
        </t>
    </t>
</span>
```

3. **Delete the entire `.ai-tree-metrics-line` block** (lines 116-125 — the `<span class="ai-tree-metrics-line" ...>` and everything inside it including the closing `</span>`).

In app.scss, make these changes:

4. **Delete the `.ai-tree-metrics-line` rule block** (lines 418-426).

5. **No changes needed to `.ai-tree-meta-line`** — the existing style (font-size: 11px, color: gray-600, overflow: hidden, text-overflow: ellipsis, white-space: nowrap) is exactly right for the combined single-line layout.

Do NOT modify app.js — the `getTraceTotals`, `formatDuration`, and `formatTokens` bindings remain unchanged.
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro && grep -c "ai-tree-metrics-line" ai_debug/static/src/app/app.xml ai_debug/static/src/app/app.scss | grep -v ":0$" | wc -l | tr -d ' ' | grep "^0$"</automated>
    <manual>Open the AI Debugger, verify trace rows show "Agent . model . duration . tokens" on one line beneath the query title, with no second metrics row.</manual>
  </verify>
  <done>Sidebar trace rows display agent name, model, duration, and token counts all on the meta line. The separate .ai-tree-metrics-line element and its CSS rule are fully removed. No JS changes.</done>
</task>

</tasks>

<verification>
- `grep -c "ai-tree-metrics-line" ai_debug/static/src/app/app.xml` returns 0
- `grep -c "ai-tree-metrics-line" ai_debug/static/src/app/app.scss` returns 0
- `grep -c "ai-tree-meta-line" ai_debug/static/src/app/app.xml` returns at least 1 (the inlined version)
- `grep "formatDuration\|formatTokens\|getTraceTotals" ai_debug/static/src/app/app.xml` shows these calls exist in the meta-line span
</verification>

<success_criteria>
Sidebar trace rows show all metadata (agent, model, duration, tokens) on a single line. The `.ai-tree-metrics-line` element and CSS rule no longer exist. Visual result: compact two-line trace rows (query title + combined meta line) instead of three-line rows.
</success_criteria>

<output>
After completion, create `.planning/quick/33-in-the-sidebar-inline-the-metrics-to-the/33-SUMMARY.md`
</output>
