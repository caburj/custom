---
phase: quick-35
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.xml
autonomous: true
requirements: [QUICK-35]

must_haves:
  truths:
    - "Each sidebar iteration row shows the actual LLM call duration (duration_ms) not the wall-clock delta"
    - "Each sidebar iteration row shows input and output token counts with directional arrows"
    - "Iterations with no tokens (errored/still running) do not show token info"
    - "Iterations with zero duration_ms do not show a duration"
  artifacts:
    - path: "ai_debug/static/src/app/app.xml"
      provides: "Updated iteration row template with actual duration and token display"
      contains: "node.iter.duration_ms"
  key_links:
    - from: "ai_debug/static/src/app/app.xml"
      to: "format_metrics.js"
      via: "this.formatDuration and this.formatTokens bound on component"
      pattern: "this\\.formatDuration\\(node\\.iter\\.duration_ms\\)"
---

<objective>
Show actual iteration duration (duration_ms from the LLM provider) and input/output token counts in sidebar iteration rows.

Purpose: Currently the iteration row shows a wall-clock delta between consecutive iteration arrival times (getIterationDuration), which is misleading — it includes tool execution time and bus latency. The backend provides the actual LLM call duration in `duration_ms` on each iteration object. Similarly, each iteration has `tokens.input` and `tokens.output` that should be surfaced.

Output: Updated sidebar iteration row displaying actual LLM duration and in/out tokens.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.xml (sidebar template — iteration row at lines 134-164)
@ai_debug/static/src/app/app.js (component — formatDuration/formatTokens already bound at lines 112-113, getIterationDuration at line 772)
@ai_debug/static/src/app/format_metrics.js (formatTokens and formatDuration utilities)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Replace wall-clock duration with actual duration_ms and add token display to iteration rows</name>
  <files>ai_debug/static/src/app/app.xml</files>
  <action>
In app.xml, replace the iteration row's duration section (lines 154-160) with:

1. Replace the `getIterationDuration` call with a direct read of `node.iter.duration_ms`. The iteration object already has `duration_ms` (number, 0 for missing). Show it only when > 0 using `this.formatDuration(node.iter.duration_ms)`.

2. Add in/out token display after the duration, following the same pattern used in trace rows (lines 117-122). Show tokens only when `node.iter.tokens` exists and has nonzero input or output. Use the directional arrow format already established in trace meta-line: `formatTokens(input)` followed by up-arrow (&#x2191;) and `formatTokens(output)` followed by down-arrow (&#x2193;).

Specifically, replace lines 154-160 (the `t-set="duration"` block through the running pulse-dot elif) with:

```xml
<t t-if="node.iter.duration_ms > 0">
    <span class="ai-tree-label-dim"> &#xB7; <t t-esc="this.formatDuration(node.iter.duration_ms)"/></span>
</t>
<t t-elif="node.trace.status === 'running' and node.id === [...node.trace.iterations.keys()].pop()">
    <span class="ai-tree-label-dim"> &#xB7; <span class="ai-debug-pulse-dot tiny"/></span>
</t>
<t t-if="node.iter.tokens and (node.iter.tokens.input > 0 or node.iter.tokens.output > 0)">
    <span class="ai-tree-label-dim"> &#xB7; <t t-esc="this.formatTokens(node.iter.tokens.input)"/>&#x2191; <t t-esc="this.formatTokens(node.iter.tokens.output)"/>&#x2193;</span>
</t>
```

This removes the dependency on `getIterationDuration()` from the template. The method itself in app.js can remain (it does no harm and may be useful for other callers in the future).

Do NOT modify app.js or app.scss — no new methods or styles needed. `formatDuration`, `formatTokens` are already bound on the component instance. The `ai-tree-label-dim` class already provides the correct dimmed styling.
  </action>
  <verify>
    Open the AI Debugger in a browser, trigger an agentic loop (or load an archived trace). Verify:
    1. Iteration rows show duration like "1.2s" or "850ms" (the actual LLM call time, not the gap between iterations)
    2. Iteration rows show token counts like "3.4k↑ 1.2k↓" after the duration
    3. Running iterations with no duration yet show the pulsing dot (no duration number)
    4. Errored iterations with no tokens do not show token info
    Automated: `cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro && grep -c 'node.iter.duration_ms' ai_debug/static/src/app/app.xml && grep -c 'node.iter.tokens' ai_debug/static/src/app/app.xml`
  </verify>
  <done>Sidebar iteration rows display the actual LLM duration_ms (not wall-clock delta) and input/output token counts with directional arrows, matching the established trace-row format.</done>
</task>

</tasks>

<verification>
- `grep 'getIterationDuration' ai_debug/static/src/app/app.xml` returns NO matches (removed from template)
- `grep 'node.iter.duration_ms' ai_debug/static/src/app/app.xml` returns a match
- `grep 'node.iter.tokens' ai_debug/static/src/app/app.xml` returns a match
- `grep 'formatTokens' ai_debug/static/src/app/app.xml` returns matches in both trace and iteration sections
</verification>

<success_criteria>
- Iteration rows show actual LLM call duration from duration_ms field
- Iteration rows show input/output tokens with up/down arrows
- No regression in trace-level metrics display
- Running iterations still show pulse dot when no duration available
</success_criteria>

<output>
After completion, create `.planning/quick/35-show-actual-iteration-duration-and-in-ou/35-SUMMARY.md`
</output>
