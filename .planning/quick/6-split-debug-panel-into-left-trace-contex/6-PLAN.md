---
phase: quick
plan: 6
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/debug_panel/debug_panel.xml
  - ai_debug/static/src/debug_panel/debug_panel.js
  - ai_debug/static/src/debug_panel/debug_panel.scss
autonomous: true
requirements: [QUICK-6]

must_haves:
  truths:
    - "Debug panel displays a two-column layout: left panel with trace context, right panel with iterations timeline"
    - "Trace context (system prompt, RAG, tools) is always visible in the left panel when a trace is loaded — no collapsible toggle"
    - "Iterations timeline scrolls independently in the right panel"
    - "In listen mode (no trace), left panel shows a placeholder or empty state"
    - "Live trace auto-loads trace detail (instructions, rag_context, tools_definition) without user interaction"
  artifacts:
    - path: "ai_debug/static/src/debug_panel/debug_panel.xml"
      provides: "Two-column layout with ai-debug-body wrapper, left panel, right panel"
      contains: "ai-debug-body"
    - path: "ai_debug/static/src/debug_panel/debug_panel.js"
      provides: "Auto-loading trace detail via _loadTraceDetail(), no toggleTraceDetail"
    - path: "ai_debug/static/src/debug_panel/debug_panel.scss"
      provides: "Flex row body, 50/50 split panels with independent scroll"
      contains: "ai-debug-left-panel"
  key_links:
    - from: "debug_panel.js _switchToTraceChannel()"
      to: "_loadTraceDetail()"
      via: "fire-and-forget call after channel switch"
      pattern: "_loadTraceDetail"
    - from: "debug_panel.xml ai-debug-left-panel"
      to: "state.traceInfo"
      via: "always-rendered sections (no traceDetailExpanded gate)"
      pattern: "ai-debug-left-panel"
    - from: "debug_panel.xml t-ref timeline"
      to: "ai-debug-right-panel"
      via: "scroll ref on right panel container"
      pattern: "t-ref.*timeline"
---

<objective>
Restructure the debug panel from a stacked layout (collapsible trace context above timeline) to a two-column layout: left panel shows trace context (system prompt, RAG, tools) permanently, right panel shows iterations timeline.

Purpose: Trace context is critical reference material during debugging — hiding it behind a collapsible toggle adds friction. A side-by-side layout lets the user see both the agent's configuration and its execution simultaneously.

Output: Updated debug_panel.xml, debug_panel.js, debug_panel.scss with two-column layout.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/debug_panel/debug_panel.xml
@ai_debug/static/src/debug_panel/debug_panel.js
@ai_debug/static/src/debug_panel/debug_panel.scss
</context>

<tasks>

<task type="auto">
  <name>Task 1: Restructure JS — replace toggle with auto-load, clean state</name>
  <files>ai_debug/static/src/debug_panel/debug_panel.js</files>
  <action>
Modify the DebugPanel component in debug_panel.js:

1. **Remove `traceDetailExpanded` from state** (line 41). Keep `traceDetailLoading` — repurposed for left panel loading indicator.

2. **Remove `toggleTraceDetail` binding** from setup() (line 59: `this.toggleTraceDetail = this.toggleTraceDetail.bind(this);`).

3. **Replace `toggleTraceDetail()` method (lines 343-369) with `_loadTraceDetail()`:**
   ```js
   async _loadTraceDetail() {
       if (
           !this.state.traceId ||
           !this.state.traceInfo ||
           "instructions" in this.state.traceInfo ||
           this.state.traceDetailLoading
       ) {
           return;
       }
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
           // Non-fatal — left panel sections just show empty.
       } finally {
           this.state.traceDetailLoading = false;
       }
   }
   ```

4. **In `_switchToTraceChannel()` (line 120):**
   - Remove the line `this.state.traceDetailExpanded = false;` (line 133).
   - Remove `this.state.traceDetailLoading = false;` (line 134) — _loadTraceDetail handles its own state.
   - After `this.busService.addChannel(...)` (line 137), add a fire-and-forget call:
     ```js
     this._loadTraceDetail();
     ```

5. **Move `scrollRef` target:** The `t-ref="timeline"` will move to the right panel in the template. The JS useRef("timeline") on line 45 stays the same — OWL resolves it by the t-ref attribute in the template.
  </action>
  <verify>No syntax errors: open the file and visually confirm the method exists, state no longer has traceDetailExpanded, and _loadTraceDetail is called from _switchToTraceChannel.</verify>
  <done>toggleTraceDetail removed, _loadTraceDetail created and auto-called from _switchToTraceChannel, traceDetailExpanded removed from state.</done>
</task>

<task type="auto">
  <name>Task 2: Restructure XML template — two-column layout</name>
  <files>ai_debug/static/src/debug_panel/debug_panel.xml</files>
  <action>
Restructure the template in debug_panel.xml. The header and error state stay at the top (full width). Everything below gets wrapped in a new flex-row container.

Replace the TRACE CONTEXT block (lines 76-126) and TIMELINE block (lines 128-344) with this structure:

```xml
<!-- ===== BODY: TWO-COLUMN LAYOUT ===== -->
<div class="ai-debug-body">

  <!-- LEFT PANEL: Trace Context (always visible) -->
  <div class="ai-debug-left-panel">
    <t t-if="state.traceInfo and state.mode === 'trace'">
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
    </t>
    <t t-elif="state.mode === 'listen'">
      <div class="ai-debug-empty-state" style="padding: 24px;">Trace context will appear when a trace is attached.</div>
    </t>
  </div>

  <!-- RIGHT PANEL: Timeline -->
  <div class="ai-debug-right-panel" t-ref="timeline">
    [... keep the ENTIRE existing timeline content unchanged (listen mode waiting, trace mode waiting, iteration nodes rail-container, terminal state) ...]
  </div>

</div>
```

Key changes:
- Remove the entire collapsible trace context div (lines 76-126) — the toggle bar, the `t-if="state.traceDetailExpanded"` guard, the chevron icon.
- The left panel renders trace context sections directly with NO expand/collapse wrapper. The only conditional is `t-if="state.traceInfo and state.mode === 'trace'"`.
- Move `t-ref="timeline"` from the old `.ai-debug-timeline` div to the new `.ai-debug-right-panel` div (so scroll tracking targets the right panel).
- Remove the `class="ai-debug-timeline"` from the right panel div — use `class="ai-debug-right-panel"` instead. The timeline styles will be applied inside this container.
- The iteration content inside the right panel is UNCHANGED — keep all the rail-container, iteration nodes, tool calls, terminal state exactly as they are.
  </action>
  <verify>Open the XML file, confirm: (1) no reference to toggleTraceDetail or traceDetailExpanded, (2) ai-debug-body wraps left+right panels, (3) t-ref="timeline" is on ai-debug-right-panel, (4) left panel renders sections without collapsible toggle.</verify>
  <done>Template uses two-column layout with ai-debug-body > ai-debug-left-panel + ai-debug-right-panel. No collapsible toggle. Trace context always visible.</done>
</task>

<task type="auto">
  <name>Task 3: Update SCSS — flex row body, split panels, remove toggle styles</name>
  <files>ai_debug/static/src/debug_panel/debug_panel.scss</files>
  <action>
Update the SCSS in debug_panel.scss:

1. **Add `.ai-debug-body` rule** (new section after TRACE CONTEXT section, or replace the TRACE CONTEXT section header):
   ```scss
   .ai-debug-body {
       display: flex;
       flex-direction: row;
       flex: 1;
       overflow: hidden;
       min-height: 0; // Required for flex children to scroll independently
   }
   ```

2. **Add `.ai-debug-left-panel` rule:**
   ```scss
   .ai-debug-left-panel {
       width: 50%;
       overflow-y: auto;
       padding: 16px 20px;
       border-right: 1px solid #e5e7eb;
       background: #fff;
       min-height: 0;
   }
   ```

3. **Add `.ai-debug-right-panel` rule:**
   ```scss
   .ai-debug-right-panel {
       width: 50%;
       overflow-y: auto;
       padding: 16px 0 80px;
       min-height: 0;
   }
   ```

4. **Remove `.ai-debug-trace-context` rule** (line 205-208) — the outer wrapper is gone.

5. **Remove `.ai-debug-trace-context-toggle` rule** (lines 210-224) — no more toggle bar.

6. **Remove `.ai-debug-trace-context-hint` rule** (lines 226-230) — no more hint text.

7. **Update `.ai-debug-trace-context-body`** — remove it entirely (lines 232-234). The body wrapper no longer exists; sections render directly in left panel.

8. **Keep these rules unchanged** (they still apply inside the left panel):
   - `.ai-debug-trace-context-section` (lines 236-239)
   - `.ai-debug-trace-context-pre` (lines 241-254)
   - `.ai-debug-trace-context-count` (lines 256-259)

9. **Update `.ai-debug-timeline` rule** (lines 265-269):
   - Remove `flex: 1;` — no longer needed since the right panel handles sizing.
   - Remove `overflow-y: auto;` — the right panel handles scrolling.
   - Keep `padding: 16px 0 80px;` — OR remove this rule entirely if the padding is now on `.ai-debug-right-panel`.

   Actually, since the template no longer uses the class `ai-debug-timeline` (the right panel uses `ai-debug-right-panel`), this rule can be removed entirely or left as dead CSS. Safest: remove it to keep things clean.
  </action>
  <verify>Open the SCSS file, confirm: (1) ai-debug-body is a flex row, (2) left-panel and right-panel are 50% width with independent scroll, (3) no trace-context-toggle styles remain, (4) ai-debug-timeline rule is removed.</verify>
  <done>SCSS implements 50/50 split layout with independent scrolling. Toggle styles removed. Left panel has border-right separator and white background.</done>
</task>

</tasks>

<verification>
1. Open `/odoo/ai-debug?trace_id=N` for an existing trace — verify two-column layout appears
2. Left panel shows system prompt, RAG context (if present), and tools (if present) without needing to click anything
3. Right panel shows iteration timeline with scroll working independently
4. Open `/odoo/ai-debug` (listen mode) — left panel shows placeholder text, right panel shows listening spinner
5. Start a new AI conversation — debug panel auto-attaches and left panel auto-loads trace context
6. Both panels scroll independently
</verification>

<success_criteria>
- Two-column layout renders correctly (50/50 split)
- Trace context sections always visible when trace is loaded (no toggle)
- Live traces auto-fetch trace detail without user interaction
- Independent scrolling on both panels
- No references to toggleTraceDetail or traceDetailExpanded remain in any file
</success_criteria>

<output>
After completion, create `.planning/quick/6-split-debug-panel-into-left-trace-contex/6-SUMMARY.md`
</output>
