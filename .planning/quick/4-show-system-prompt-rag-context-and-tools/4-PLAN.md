---
phase: quick
plan: 4
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/debug_panel/debug_panel.js
  - ai_debug/static/src/debug_panel/debug_panel.xml
  - ai_debug/static/src/debug_panel/debug_panel.scss
autonomous: true
requirements: [QUICK-4]

must_haves:
  truths:
    - "User can expand a 'Trace Context' section to see system prompt, RAG context, and tools"
    - "System prompt displays as preformatted text"
    - "Tools definition renders via JsonTree component"
    - "Sections with empty data are hidden (not shown as blank)"
    - "Trace context loads eagerly for direct-link mode and on-demand for live mode"
  artifacts:
    - path: "ai_debug/static/src/debug_panel/debug_panel.js"
      provides: "traceDetailExpanded state, _loadTraceDetail method, toggle method"
    - path: "ai_debug/static/src/debug_panel/debug_panel.xml"
      provides: "Collapsible Trace Context section between header and timeline"
    - path: "ai_debug/static/src/debug_panel/debug_panel.scss"
      provides: "Styles for trace context section"
  key_links:
    - from: "debug_panel.xml"
      to: "debug_panel.js"
      via: "toggleTraceDetail method and traceDetailExpanded state"
      pattern: "toggleTraceDetail|traceDetailExpanded"
    - from: "debug_panel.js _loadTraceDetail"
      to: "ai.debug.trace ORM"
      via: "orm.read for instructions, rag_context, tools_definition"
      pattern: "orm\\.read.*instructions.*rag_context.*tools_definition"
---

<objective>
Show system prompt (instructions), RAG context, and tools_definition in the live debug panel UI as a collapsible "Trace Context" section.

Purpose: These fields are already stored on ai.debug.trace but the panel never fetches or displays them. Users need to see what instructions, context, and tools the LLM received.
Output: Updated debug_panel.js/xml/scss with a new collapsible section between header and timeline.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/debug_panel/debug_panel.js
@ai_debug/static/src/debug_panel/debug_panel.xml
@ai_debug/static/src/debug_panel/debug_panel.scss
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add trace detail state, lazy-load method, and eager-load in _loadTrace</name>
  <files>ai_debug/static/src/debug_panel/debug_panel.js</files>
  <action>
1. Add `traceDetailExpanded: false` and `traceDetailLoading: false` to the `useState` object in `setup()`.

2. Bind `this.toggleTraceDetail = this.toggleTraceDetail.bind(this)` in `setup()`.

3. In `_loadTrace()`, add `"instructions", "rag_context", "tools_definition"` to the fields array in the `orm.read` call (line ~147). After `this.state.traceInfo = traceRecord;`, the traceInfo object will already contain these fields from the initial read. No second round-trip needed for direct-link mode.

4. In `_switchToTraceChannel()`, reset trace detail state: set `this.state.traceDetailExpanded = false` and `this.state.traceDetailLoading = false`. The traceInfo set here (from bus payload) will NOT have instructions/rag/tools — that is expected.

5. Add method `toggleTraceDetail()`:
   ```js
   async toggleTraceDetail() {
       this.state.traceDetailExpanded = !this.state.traceDetailExpanded;
       // Lazy-load if expanding and traceInfo lacks these fields (live mode).
       if (
           this.state.traceDetailExpanded &&
           this.state.traceId &&
           this.state.traceInfo &&
           !("instructions" in this.state.traceInfo) &&
           !this.state.traceDetailLoading
       ) {
           this.state.traceDetailLoading = true;
           try {
               const [detail] = await this.orm.read(
                   "ai.debug.trace",
                   [this.state.traceId],
                   ["instructions", "rag_context", "tools_definition"],
               );
               if (detail) {
                   Object.assign(this.state.traceInfo, detail);
               }
           } catch {
               // Non-fatal — section just shows empty.
           } finally {
               this.state.traceDetailLoading = false;
           }
       }
   }
   ```

Place the method in the "Expand/collapse with lazy detail fetch" section alongside `toggleIteration` and `toggleToolCall`.
  </action>
  <verify>No syntax errors: `grep -c "toggleTraceDetail" ai_debug/static/src/debug_panel/debug_panel.js` returns at least 2 (bind + method). Verify `instructions` appears in the `_loadTrace` orm.read fields array.</verify>
  <done>debug_panel.js has traceDetailExpanded state, toggleTraceDetail method with lazy-load, and _loadTrace eagerly fetches the three fields.</done>
</task>

<task type="auto">
  <name>Task 2: Add collapsible Trace Context section to template and style it</name>
  <files>ai_debug/static/src/debug_panel/debug_panel.xml, ai_debug/static/src/debug_panel/debug_panel.scss</files>
  <action>
**XML (debug_panel.xml):**

Insert a new block between the `<!-- ===== ERROR STATE ===== -->` section (after line 74, before `<!-- ===== TIMELINE ===== -->` on line 77). This goes INSIDE `div.o_ai_debug_panel`, between the error block and the timeline div.

```xml
<!-- ===== TRACE CONTEXT (collapsible) ===== -->
<t t-if="state.traceInfo and state.mode === 'trace'">
  <div class="ai-debug-trace-context">
    <div class="ai-debug-trace-context-toggle" t-on-click="toggleTraceDetail">
      <i t-att-class="state.traceDetailExpanded ? 'fa fa-chevron-down' : 'fa fa-chevron-right'"/>
      <span>Trace Context</span>
      <span class="ai-debug-trace-context-hint">(system prompt, RAG, tools)</span>
    </div>

    <t t-if="state.traceDetailExpanded">
      <div class="ai-debug-trace-context-body">
        <t t-if="state.traceDetailLoading">
          <div class="ai-debug-loading"><i class="fa fa-spinner fa-spin"/> Loading trace context...</div>
        </t>
        <t t-else="">
          <!-- System Prompt / Instructions -->
          <t t-if="state.traceInfo.instructions">
            <div class="ai-debug-trace-context-section">
              <div class="ai-debug-section-label">System Prompt</div>
              <pre class="ai-debug-trace-context-pre" t-esc="state.traceInfo.instructions"/>
            </div>
          </t>

          <!-- RAG Context -->
          <t t-if="state.traceInfo.rag_context">
            <div class="ai-debug-trace-context-section">
              <div class="ai-debug-section-label">RAG Context</div>
              <pre class="ai-debug-trace-context-pre" t-esc="state.traceInfo.rag_context"/>
            </div>
          </t>

          <!-- Tools Definition -->
          <t t-if="state.traceInfo.tools_definition and state.traceInfo.tools_definition.length">
            <div class="ai-debug-trace-context-section">
              <div class="ai-debug-section-label">
                Tools
                <span class="ai-debug-trace-context-count">(<t t-esc="state.traceInfo.tools_definition.length"/>)</span>
              </div>
              <JsonTree value="state.traceInfo.tools_definition" maxDepth="1"/>
            </div>
          </t>

          <!-- Nothing to show -->
          <t t-if="!state.traceInfo.instructions and !state.traceInfo.rag_context and (!state.traceInfo.tools_definition or !state.traceInfo.tools_definition.length)">
            <div class="ai-debug-empty-state">No trace context data recorded.</div>
          </t>
        </t>
      </div>
    </t>
  </div>
</t>
```

**SCSS (debug_panel.scss):**

Add the following block inside `.o_ai_debug_panel { ... }`, after the "ERROR / WAITING STATES" section and before the "TIMELINE" section (around line 200):

```scss
// =========================================================
// TRACE CONTEXT (collapsible)
// =========================================================

.ai-debug-trace-context {
    border-bottom: 1px solid #e5e7eb;
    background: #fff;
}

.ai-debug-trace-context-toggle {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 20px;
    cursor: pointer;
    font-size: 12px;
    font-weight: 600;
    color: #374151;
    transition: background-color 0.15s;

    &:hover { background-color: #f3f4f6; }

    .fa { font-size: 10px; color: #9ca3af; width: 12px; text-align: center; }
}

.ai-debug-trace-context-hint {
    font-weight: 400;
    color: #9ca3af;
    font-size: 11px;
}

.ai-debug-trace-context-body {
    padding: 0 20px 12px;
}

.ai-debug-trace-context-section {
    margin-bottom: 12px;
    &:last-child { margin-bottom: 0; }
}

.ai-debug-trace-context-pre {
    font-family: inherit;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-word;
    background: #f3f4f6;
    padding: 10px 12px;
    border-radius: 4px;
    color: #374151;
    max-height: 300px;
    overflow-y: auto;
    margin: 0;
    border: 1px solid #e5e7eb;
}

.ai-debug-trace-context-count {
    font-weight: 400;
    color: #9ca3af;
}
```
  </action>
  <verify>Open `/odoo/ai-debug?trace_id=N` (any existing trace ID). Verify:
1. A "Trace Context" toggle bar appears between header and timeline
2. Clicking it expands to show System Prompt as preformatted text
3. RAG Context section only appears if data is non-empty
4. Tools section renders with JsonTree and shows tool count
5. Section is collapsed by default</verify>
  <done>Collapsible "Trace Context" section renders between header and timeline. System prompt shows as pre block, RAG context conditionally shows as pre block, tools render via JsonTree. Empty sections are hidden. Collapsed by default.</done>
</task>

</tasks>

<verification>
1. Direct-link mode (`?trace_id=N`): Trace Context section visible, expandable, shows all three fields in one round-trip (check Network tab — single orm.read call includes instructions/rag_context/tools_definition).
2. Live mode (no trace_id, wait for new trace): Trace Context toggle visible after trace attaches. Expanding triggers a lazy-load ORM call. Fields populate after load.
3. Empty data: If a trace has no instructions/rag/tools, expanding shows "No trace context data recorded."
4. Visual: Section has consistent styling with the rest of the panel (monospace font, same color scheme).
</verification>

<success_criteria>
- Trace Context section is collapsed by default
- Expanding shows system prompt, RAG context, and tools (when present)
- Empty fields are hidden; all-empty shows empty state message
- Direct-link mode: no extra round-trip (fields loaded with initial trace read)
- Live mode: lazy-loads on first expand
- No regressions to existing iteration/tool call expand/collapse behavior
</success_criteria>

<output>
After completion, create `.planning/quick/4-show-system-prompt-rag-context-and-tools/4-SUMMARY.md`
</output>
