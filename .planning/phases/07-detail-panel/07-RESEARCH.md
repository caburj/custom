# Phase 7: Detail Panel - Research

**Researched:** 2026-02-21
**Domain:** OWL component composition, tab UI, JSON tree rendering, dialog/popup, clipboard, diff visualization
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Payload rendering**
- Long text content (system prompts, RAG context, long string values in JSON) renders as a truncated preview; clicking opens a popup/dialog showing the full content with markdown/syntax highlighting
- Structured data (tool args, tool results, tools definitions, raw LLM responses) renders as a collapsible tree viewer (like browser DevTools JSON viewer)
- Within tree viewers, long text leaf values get the same truncated + popup treatment as standalone long text
- Every data section has a copy-to-clipboard button on the section header (copies raw content)

**Panel layout per node type**
- **Loop detail:** Tabbed layout — System Prompt | RAG Context | Tools Definition
- **Iteration detail:** Tabbed layout — Messages Sent | Raw Response | State Diff
- **Tool call detail:** Args and Result stacked at the top (the core pair), then State Diff and Confirmation Info available as tabs below
- Each detail view has a header showing node type + name (e.g., "Loop: ai_session", "Tool Call: execute_kw")

**State diff visualization**
- Side-by-side diff layout: Before column | After column
- Color-coded: green backgrounds for additions, red for removals, yellow/amber for changes
- When no state changes exist, show full state snapshot with no diff highlights (still inspectable)
- State diffs render inline in their tab — no popup treatment (typically compact enough)

**Empty & session states**
- When no traces exist: sidebar shows "No traces yet", detail panel shows "Listening for agentic loops..."
- When traces exist but nothing selected: auto-select the most recent trace so the detail panel is never empty once data arrives
- New traces arriving never steal focus from current selection (consistent with SIDE-05)
- No ephemeral data indicator — developers understand session scope

### Claude's Discretion

- Exact popup/dialog component implementation
- Tab component choice and styling
- Tree viewer implementation approach
- Truncation thresholds for long text previews
- Exact color values for diff highlights
- Loading/transition states between selections

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DETL-01 | Selecting a loop shows system prompt, RAG context, and tools definition | `new_trace` payload has `instructions`, `tools` (serialized), `state_snapshot`; currently NOT stored in trace Map (Phase 7 must add these fields) |
| DETL-02 | Selecting an iteration shows messages sent, raw response, state diff, and final message | `iteration` payload has `messages_sent`, `raw_response`, `is_final`; NOT stored currently; `state_before`/`state_after` not in iteration payload (state diff comes from tool_call payloads) |
| DETL-03 | Selecting a tool call shows arguments, result, state diff, and confirmation info | `tool_call` payload has `args`, `result`, `success`, `error`, `state_before`, `state_after`, `call_id`; NOT stored currently |
| SESS-01 | All trace data lives in frontend memory only (no database persistence) | Already implemented — reactive Maps in browser; Phase 7 just adds more payload fields to existing Maps |
| SESS-02 | Refreshing the browser clears all trace data | Already implemented by design — browser refresh destroys JS heap; no localStorage or IndexedDB used |
| SESS-03 | App shows "Listening for agentic loops..." when no traces exist | Already implemented in `app.xml` — `t-if="!state.selectedId and traces.size === 0"` block; Phase 7 must keep this and add auto-select behavior |
</phase_requirements>

## Summary

Phase 7 wires the detail panel: clicking any sidebar node (loop, iteration, tool call) populates the right pane with type-appropriate content drawn from the bus payload. The work has three layers: (1) data layer — extend the bus payload handlers in `app.js` to store the full payload fields needed for display; (2) UI layer — build three distinct detail views (loop, iteration, tool call) with tab-based layouts, a JSON tree viewer, a truncated-text-with-popup pattern for long content, and a side-by-side diff view; (3) session behavior — add auto-select of the most recent trace when data arrives.

The Odoo web bundle already includes all necessary building blocks: `Notebook` component for tabs (`@web/core/notebook/notebook`), `Dialog` component + `dialog` service for popups (`@web/core/dialog/dialog`), `CopyButton` for clipboard (`@web/core/copy_button/copy_button`), and `Prism.js` for syntax highlighting (available in `web/static/lib/prismjs/`). The JSON tree viewer must be hand-built as a recursive OWL component since Odoo has no existing reusable collapsible JSON viewer — the DevTools-style pattern is a well-understood recursive component pattern. State diffs are purely a CSS-styled table or two-column layout since `diff_match_patch` (available in Odoo) is overkill for a before/after JSON object comparison; a simple key-diff algorithm suffices.

The critical insight: the current `_onNewTrace`, `_onIteration`, and `_onToolCall` handlers in `app.js` store only sidebar-rendering fields. Phase 7 must add `instructions`, `tools`, `state_snapshot` to trace entries; `messages_sent`, `raw_response`, `is_final` to iteration entries; and `args`, `result`, `success`, `error`, `state_before`, `state_after` to tool call entries.

**Primary recommendation:** Build 3-4 focused sub-components (`LoopDetail`, `IterationDetail`, `ToolCallDetail`, `JsonTree`) in new files alongside `app.js`, use `Notebook` for tabs, use `dialog` service for content popups, use `CopyButton` for clipboard, and use Prism for syntax highlighting in long text popups. Extend the bus handlers in `app.js` to store full payload data.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@odoo/owl` — `Component`, `useState`, `useRef`, `onWillUpdateProps` | bundled in Odoo | Sub-component base class + local state for tab selection, tree expand/collapse | Already used in `app.js`; built into OWL |
| `@web/core/notebook/notebook` — `Notebook` | Odoo web core | Tabbed layout for all three detail views | Verified in Odoo: `form_renderer.js:2` uses it; template at `notebook.xml` shows slot-based API |
| `@web/core/dialog/dialog` — `Dialog` | Odoo web core | Full-content popup when user clicks truncated long text | Verified: `dialog.js`, `dialog_service.js`, `dialog.xml` all present; `useService("dialog")` then `this.dialog.add(MyDialog, props)` |
| `@web/core/copy_button/copy_button` — `CopyButton` | Odoo web core | Section-header copy-to-clipboard button | Verified: `copy_button.js`, `copy_button.xml` present; `browser.navigator.clipboard.writeText` with tooltip feedback |
| `Prism.js` | bundled in Odoo (`web/static/lib/prismjs/`) | Syntax highlighting for code/JSON in popups | Verified: used in `html_editor` module; `Prism.highlight(value, Prism.languages[lang], lang)` returns sanitized HTML |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| CSS custom properties + `@keyframes` | native | Color tokens for diff highlights (green/red/amber), collapsible tree transitions | Consistent with existing `app.scss` patterns |
| `dialog` service (`useService("dialog")`) | Odoo web core | Programmatically open popup dialogs | Use for full-content popups when user clicks truncated text |
| `JSON.stringify(obj, null, 2)` | browser built-in | Serialize JSON for copy-to-clipboard and full-text display | No library needed for serialization |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Odoo `Notebook` component | Custom tab bar with `useState` | Custom tab simpler but loses Odoo's a11y handling and keyboard nav; `Notebook` is 1 import away |
| `dialog` service + `Dialog` component | `<div class="modal">` hand-rolled | Custom modal skips focus-trap, escape-key handling, backdrop; dialog service handles all of this |
| `CopyButton` component | `navigator.clipboard.writeText` + raw button | CopyButton already has tooltip-on-success pattern; reuse avoids re-implementing the same UX |
| Custom JSON tree | `json-tree`, `react-json-tree` | External libraries not available in Odoo bundle; recursive OWL component is ~50 lines and fully controllable |
| `diff_match_patch` | Key-by-key object diff algorithm | `diff_match_patch` is for string diffs; state diffs are JSON object diffs where the meaningful unit is a changed key/value, not a character. A custom key-diff is more appropriate and is ~30 lines |

**Installation:** No new packages needed. `Notebook`, `Dialog`, `CopyButton`, and `Prism` are already in the `ai_debug.assets` bundle (which includes `web.assets_backend` via `('include', 'web.assets_backend')` in `__manifest__.py`).

## Architecture Patterns

### Recommended Project Structure

```
ai_debug/static/src/app/
├── app.js               # AiDebugApp — extend bus handlers to store full payload data; add auto-select logic
├── app.xml              # Main template — wire detail panel t-if/t-elif/t-else for selectedType
├── app.scss             # Global styles — extend with detail panel layout, diff highlight classes
├── detail/
│   ├── loop_detail.js   # LoopDetail component — tabs: System Prompt | RAG Context | Tools Definition
│   ├── loop_detail.xml
│   ├── iter_detail.js   # IterationDetail component — tabs: Messages Sent | Raw Response | State Diff
│   ├── iter_detail.xml
│   ├── tc_detail.js     # ToolCallDetail component — Args/Result stacked, tabs: State Diff | Confirmation Info
│   ├── tc_detail.xml
│   ├── json_tree.js     # JsonTree recursive component — collapsible key-value tree with truncation
│   ├── json_tree.xml
│   ├── text_popup.js    # TextPopupDialog — full-content popup with Prism highlighting
│   └── text_popup.xml
```

The `ai_debug.assets` bundle already loads all `app/**/*.{scss,xml,js}` recursively, so adding `app/detail/` files requires no manifest changes.

### Data Layer: Extending Bus Handlers

The current handlers store minimal data for sidebar rendering. Phase 7 requires extending all three handlers to store display data:

**_onNewTrace — add to trace entry:**
```javascript
// Currently missing from trace object:
instructions: payload.instructions,      // system prompt string
tools: payload.tools,                    // array of tool definition objects
state_snapshot: payload.state_snapshot,  // object: loop-start state
// rag_context is NOT in new_trace — it arrives via messages_sent in the iteration payload
// (RAG context is injected as messages, not a separate field)
```

**_onIteration — add to iteration entry:**
```javascript
// Currently missing from iteration object:
messages_sent: payload.messages_sent,    // array of message objects
raw_response: payload.raw_response,      // object: LLM metadata/response
is_final: payload.is_final,             // bool: is this the last iteration?
error: payload.error,                    // string|null: error message if failed
```

**_onToolCall — add to toolCall entry:**
```javascript
// Currently missing from tool call object:
args: payload.args,                      // object: tool arguments
result: payload.result,                  // any: tool result (or error string)
error: payload.error,                    // string|null
state_before: payload.state_before,      // object: state snapshot before batch
state_after: payload.state_after,        // object: state snapshot after batch
call_id: payload.call_id,               // string: LLM's original call ID
```

### Auto-Select Pattern (SESS-03 / CONTEXT.md decision)

When a new trace arrives and nothing is currently selected, auto-select it. This must happen in the bus handler — but the decision says "New traces arriving never steal focus from current selection." Resolution: auto-select ONLY when `this.state.selectedId === null`.

```javascript
this._onNewTrace = (payload) => {
    // ... create trace entry (existing) ...
    // Auto-select if nothing is currently selected
    if (this.state.selectedId === null) {
        this.state.selectedId = payload.trace_id;
        this.state.selectedType = "trace";
    }
};
```

This is the only bus handler that may write to `state.selectedId`, and only when it's null. This satisfies the CONTEXT.md decision ("auto-select the most recent trace") while preserving SIDE-05 (never steal active selection).

### Pattern 1: Notebook (Tab) Component

**What:** Odoo's `Notebook` component renders a tabbed layout. Slots define tabs by name; tab titles are set via `t-set-slot`.

**Import:** `import { Notebook } from "@web/core/notebook/notebook";`

**Template usage (slot-based API):**
```xml
<Notebook>
    <t t-set-slot="system_prompt" title="System Prompt" isVisible="true">
        <!-- tab content -->
    </t>
    <t t-set-slot="rag_context" title="RAG Context" isVisible="true">
        <!-- tab content -->
    </t>
    <t t-set-slot="tools" title="Tools Definition" isVisible="true">
        <!-- tab content -->
    </t>
</Notebook>
```

**Source:** Verified in `notebook.js` and `notebook.xml`. The Notebook renders as `<div class="o_notebook ...">` with Bootstrap-styled nav tabs. The slot name becomes the page ID; `title` sets the tab label; `isVisible` controls whether the tab appears.

**Warning:** The `Notebook` uses Bootstrap nav-tabs classes (`o_notebook`, `nav-tabs`, `nav-link`, `tab-pane`). These styles are provided by `web.assets_backend` which is already included in `ai_debug.assets`. No additional CSS import needed.

### Pattern 2: Dialog Service for Full-Content Popups

**What:** When a user clicks on a truncated long text preview, open a full-screen or large modal dialog showing the full content with syntax highlighting.

**Setup in component:**
```javascript
import { useService } from "@web/core/utils/hooks";
import { TextPopupDialog } from "./detail/text_popup";

setup() {
    this.dialog = useService("dialog");
}

openPopup(title, content, language = "markdown") {
    this.dialog.add(TextPopupDialog, { title, content, language });
}
```

**TextPopupDialog component:**
```javascript
import { Component, onMounted, useRef } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";

export class TextPopupDialog extends Component {
    static template = "ai_debug.TextPopupDialog";
    static components = { Dialog };
    static props = {
        title: String,
        content: String,
        language: { type: String, optional: true },
        close: Function,
    };

    setup() {
        this.codeRef = useRef("codeEl");
        onMounted(() => {
            const el = this.codeRef.el;
            if (!el) return;
            // Use textContent for safe plain-text rendering first
            el.textContent = this.props.content;
            // Prism.highlight returns sanitized HTML from a controlled source (our own bus payloads)
            // Prism output is escaped and safe to insert; the content is developer-controlled debug data
            const lang = this.props.language || "plaintext";
            if (window.Prism && Prism.languages[lang]) {
                const highlighted = Prism.highlight(
                    this.props.content,
                    Prism.languages[lang],
                    lang
                );
                // Prism.highlight output contains only <span> elements with class attributes
                // from Prism's internal tokenizer — no user-supplied HTML is passed through
                el.textContent = "";
                const pre = document.createElement("span");
                pre.className = "language-" + lang;
                // Safe: Prism output is generated by Prism's tokenizer, not from user HTML input
                pre.textContent = highlighted; // fallback: use textContent by default
                // If Prism produces valid output, insert via createRange for safety
                // Alternative: keep textContent and skip highlighting if XSS is a concern
                el.appendChild(pre);
            }
        });
    }
}
```

**Note on Prism and content safety:** The content displayed in the popup comes from bus payloads (system prompts, tool args, LLM responses) authored by Odoo developers configuring AI agents. This is developer-controlled data in a developer tool, not user-submitted content. Prism's output is generated from its own tokenizer using `<span>` elements with CSS class names. Standard practice in Odoo (verified in `syntax_highlighting_utils.js`) is to assign Prism's output to `innerHTML` of a `pre` element because it is controlled tokenizer output, not arbitrary HTML. For this tool, using `textContent` first (plain text fallback) with an optional highlighted rendering path is the safest approach.

**Template:**
```xml
<Dialog title="props.title" size="'xl'" footer="false">
    <pre class="ai-popup-content"><code t-ref="codeEl"/></pre>
</Dialog>
```

**Source:** `dialog.js`, `dialog_service.js`, `dialog.xml` verified. The `close` prop is injected by the dialog service automatically.

### Pattern 3: CopyButton Component

**What:** Reusable clipboard copy button that shows a tooltip on success.

**Import:** `import { CopyButton } from "@web/core/copy_button/copy_button";`

**Usage in template:**
```xml
<div class="ai-detail-section-header">
    <span>System Prompt</span>
    <CopyButton content="() => props.trace.instructions" successText="'Copied!'" icon="'fa-copy'"/>
</div>
```

The `content` prop accepts a function returning the string to copy. `CopyButton` handles `navigator.clipboard.writeText` and shows a popover tooltip on success.

**Source:** `copy_button.js:27-48`, `copy_button.xml` verified.

### Pattern 4: Recursive JSON Tree Component

**What:** A collapsible tree viewer for JSON objects/arrays, similar to browser DevTools. Built as a recursive OWL component since nothing equivalent exists in Odoo.

**Structure:**
```javascript
// json_tree.js
export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { JsonTree };  // self-reference enables recursive rendering
    static props = {
        data: true,          // any JSON value
        label: { type: String, optional: true },
        depth: { type: Number, optional: true },
    };
    static defaultProps = { depth: 0 };

    setup() {
        this.state = useState({
            expanded: this.props.depth < 2,
        });
    }

    get type() {
        if (this.props.data === null) return "null";
        if (Array.isArray(this.props.data)) return "array";
        return typeof this.props.data;
    }

    get isExpandable() {
        return this.type === "object" || this.type === "array";
    }

    get childCount() {
        if (!this.isExpandable) return 0;
        return Array.isArray(this.props.data)
            ? this.props.data.length
            : Object.keys(this.props.data || {}).length;
    }

    get entries() {
        if (this.type === "array") return this.props.data.map((v, i) => [String(i), v]);
        if (this.type === "object") return Object.entries(this.props.data || {});
        return [];
    }

    get isLongString() {
        return this.type === "string" && this.props.data.length > TRUNCATION_THRESHOLD;
    }

    get displayString() {
        if (this.isLongString) return this.props.data.slice(0, TRUNCATION_THRESHOLD) + "...";
        return this.props.data;
    }
}
```

The component calls itself recursively in the template using `t-key` on each child for stable OWL rendering:
```xml
<t t-foreach="component.entries" t-as="entry" t-key="entry[0]">
    <div class="ai-json-row">
        <span class="ai-json-key" t-esc="entry[0]"/>:
        <JsonTree data="entry[1]" depth="props.depth + 1"/>
    </div>
</t>
```

**CRITICAL:** `JsonTree` must list itself in `static components = { JsonTree }` to enable recursive rendering. This is a valid OWL pattern.

**Truncation threshold:** Leaf string values longer than 300 characters are shown truncated with a "click to expand" trigger that opens `TextPopupDialog`.

### Pattern 5: State Diff Visualization

**What:** Side-by-side Before/After columns, color-coded by change type.

**Algorithm (no library needed):**
```javascript
// Simple key-diff — compares two flat-or-nested objects at the top level
computeDiff(before, after) {
    const b = before || {};
    const a = after || {};
    const allKeys = new Set([...Object.keys(b), ...Object.keys(a)]);
    return [...allKeys].map(key => {
        const bVal = b[key];
        const aVal = a[key];
        if (!(key in b)) return { key, type: "added", before: undefined, after: aVal };
        if (!(key in a)) return { key, type: "removed", before: bVal, after: undefined };
        const changed = JSON.stringify(bVal) !== JSON.stringify(aVal);
        return { key, type: changed ? "changed" : "unchanged", before: bVal, after: aVal };
    });
}
```

**Template:**
```xml
<div class="ai-diff-grid">
    <div class="ai-diff-header">Before</div>
    <div class="ai-diff-header">After</div>
    <t t-foreach="diffRows" t-as="row" t-key="row.key">
        <div class="ai-diff-cell" t-att-class="'ai-diff-' + row.type">
            <span class="ai-diff-key" t-esc="row.key"/>: <t t-esc="formatValue(row.before)"/>
        </div>
        <div class="ai-diff-cell" t-att-class="'ai-diff-' + row.type">
            <span class="ai-diff-key" t-esc="row.key"/>: <t t-esc="formatValue(row.after)"/>
        </div>
    </t>
</div>
```

For the "no changes" case: render only the after-snapshot as a single-column view with no color coding.

### Pattern 6: Detail Panel Routing in Main Template

The `app.xml` `<main>` block must route to the correct detail component based on `state.selectedType`. The selected node's data must be looked up from the trace Maps.

```xml
<main class="ai-debug-detail">
    <!-- Empty state: no traces at all -->
    <div t-if="traces.size === 0" class="ai-debug-detail-empty">
        <span class="ai-debug-pulse-dot large"/>
        <p>Listening for agentic loops...</p>
        <p class="ai-debug-detail-hint">Trigger an AI action in Odoo to see live trace data here.</p>
    </div>
    <!-- Loop detail -->
    <LoopDetail t-elif="state.selectedType === 'trace'"
                t-key="state.selectedId"
                trace="getSelectedTrace()"/>
    <!-- Iteration detail -->
    <IterationDetail t-elif="state.selectedType === 'iteration'"
                     t-key="state.selectedId"
                     iteration="getSelectedIteration()"/>
    <!-- Tool call detail -->
    <ToolCallDetail t-elif="state.selectedType === 'tool_call'"
                    t-key="state.selectedId"
                    toolCall="getSelectedToolCall()"/>
</main>
```

Using `t-key="state.selectedId"` ensures OWL destroys and recreates the detail component when selection changes (clean state, no stale tab positions from previous selection).

Getter methods in `app.js`:
```javascript
getSelectedTrace() {
    return this.traces.get(this.state.selectedId) || null;
}

getSelectedIteration() {
    for (const trace of this.traces.values()) {
        if (trace.iterations.has(this.state.selectedId)) {
            return trace.iterations.get(this.state.selectedId);
        }
    }
    return null;
}

getSelectedToolCall() {
    for (const trace of this.traces.values()) {
        for (const iter of trace.iterations.values()) {
            if (iter.toolCalls.has(this.state.selectedId)) {
                return iter.toolCalls.get(this.state.selectedId);
            }
        }
    }
    return null;
}
```

### Pattern 7: RAG Context Location

**Important:** The `new_trace` payload does NOT include a separate `rag_context` field. RAG context is injected as messages (typically a system or user message containing retrieved documents) into the first iteration's `messages_sent`. The "RAG Context" tab in Loop detail should extract the RAG-context message from the first iteration's `messages_sent`.

**Resolution:** Look at the `messages_sent` array in the first iteration (iteration_index=1). Since `instructions` (the system prompt) is sent separately in `new_trace`, any additional system messages in `messages_sent` are RAG context injected by the AI session.

The safest implementation: the "RAG Context" tab in Loop detail displays all system messages from the first iteration's `messages_sent` where `msg.role === "system"` and the content differs from `trace.instructions`. If no first iteration has arrived yet, show "No RAG context captured yet — waiting for first iteration."

**Access from LoopDetail component:**
```javascript
get ragContextMessages() {
    const firstIter = [...this.props.trace.iterations.values()][0];
    if (!firstIter) return null;
    return firstIter.messages_sent.filter(
        m => m.role === "system" && m.content !== this.props.trace.instructions
    );
}
```

### Pattern 8: Detail Panel Header

Each detail view has a header bar (type + name):
```xml
<div class="ai-detail-header">
    <span class="ai-detail-type-badge">Loop</span>
    <span class="ai-detail-name" t-esc="props.trace.agent_name"/>
    <span class="ai-detail-model" t-esc="props.trace.model_name"/>
</div>
```

This header is separate from (above) the `Notebook` tab area.

### Anti-Patterns to Avoid

- **Storing full payload in sidebar Map nodes without need:** All payload data is already received in bus events. Store it in the Map entries at event time. Do NOT try to re-fetch it.
- **Using `Notebook` with `pages` prop (programmatic API):** The slot-based API is simpler for static tab definitions. The `pages` prop is for dynamic tab lists.
- **Recursive JsonTree without `t-key`:** Each recursive level must have a stable `t-key` to avoid OWL re-creating the entire tree on re-render.
- **Inserting arbitrary user-supplied content as HTML:** All content displayed comes from the bus payloads of the AI agentic loop (developer-controlled data). Use OWL's `t-esc` for plain text fields. For Prism-highlighted output, insert via DOM methods only if the source is Prism's own tokenizer output.
- **Putting `dialog` service in sub-components when uncertain:** Sub-components can use `useService("dialog")` independently. If dialog service is unavailable, implement a simple CSS-overlay popup as a fallback.
- **Forgetting `t-key` on the detail panel's top-level component:** Without `t-key="state.selectedId"`, switching from one trace to another of the same type will reuse the component instance, leaving the Notebook on the previously-active tab and showing stale `useState` values.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Tab UI | Custom div-based tabs with manual active state | `Notebook` from `@web/core/notebook/notebook` | Odoo's Notebook handles keyboard a11y, `defaultPage`, and tab switching; already in bundle |
| Clipboard copy with feedback | `navigator.clipboard.writeText` + custom tooltip | `CopyButton` from `@web/core/copy_button/copy_button` | CopyButton already handles both `writeText` and `write` (for non-string content), plus tooltip-on-success via `Popover` |
| Full-content popup modal | `<div class="modal" ...>` with manual backdrop/ESC | `Dialog` component + `dialog` service | Dialog handles focus trap, ESC key, backdrop click, and stacking for multiple dialogs |
| Syntax highlighting | Custom regex colorizer | `Prism.js` (already in bundle) | Prism covers markdown, JSON, Python, XML; already loaded via `web.assets_backend` |
| String diff | Character-level diffing | Key-level JSON object diff | State diffs are object-level (added/removed/changed keys), not string-level edits |

**Key insight:** Everything needed for Phase 7 is already in the Odoo web bundle. The only truly custom code is the recursive `JsonTree` component and the `computeDiff` key-level diff algorithm.

## Common Pitfalls

### Pitfall 1: Full Payload Data Not Stored

**What goes wrong:** Detail panel tries to access `iteration.messages_sent` but it's `undefined` because the `_onIteration` handler only stored `iteration_id`, `iteration_index`, `has_error`, `receivedAt`, `expanded`, `toolCalls`.

**Why it happens:** The Phase 6 handler stored only what was needed for the sidebar. Phase 7 must extend the stored data.

**How to avoid:** In Phase 7 plan step 1, extend all three bus handlers to include the full payload fields needed for display before building any UI.

**Warning signs:** Console errors when accessing message arrays or argument objects from selected nodes.

### Pitfall 2: RAG Context Not Available from Loop Payload

**What goes wrong:** Loop detail "RAG Context" tab shows nothing because `new_trace` payload has no `rag_context` field. Developer attempts to add it to the Python instrumentation.

**Why it happens:** RAG context is not a separate Python variable — it's injected as messages into the conversation. The `new_trace` event only has the static initialization data (instructions, tools, initial state).

**How to avoid:** Display RAG context from the first iteration's `messages_sent` (filter for system messages beyond the initial `instructions`). Show a "waiting" state if no iteration has arrived yet. Do NOT modify the Python instrumentation.

**Warning signs:** Temptation to open `ai_session.py` and add a `rag_context` field.

### Pitfall 3: `t-key` Missing on Detail Components Causes Stale State

**What goes wrong:** Selecting "Iteration 1" shows the Messages Sent tab. Selecting "Iteration 2" still shows the same tab — the `Notebook`'s `state.currentPage` is preserved from the previous render.

**Why it happens:** OWL reuses the component instance when the component type doesn't change and `t-key` is absent or stable. The `useState` inside `Notebook` retains its value.

**How to avoid:** Use `t-key="state.selectedId"` on the detail component in the template. This forces OWL to destroy and recreate the component when the selected item changes, resetting all internal state.

### Pitfall 4: Recursive OWL Component Without Self-Reference

**What goes wrong:** `JsonTree` tries to recursively render itself but OWL can't find the component class because it's not listed in `static components`.

**Why it happens:** OWL's template compiler requires all sub-components to be declared in `static components`. Recursive components must reference themselves.

**How to avoid:**
```javascript
export class JsonTree extends Component {
    static components = { JsonTree };  // self-reference for recursion
}
```

**Warning signs:** Template compilation error "Component JsonTree not found in components registry."

### Pitfall 5: Dialog Service Not Available in Standalone App

**What goes wrong:** `useService("dialog")` throws "Service 'dialog' is not available" in the AI debug standalone app.

**Why it happens:** The `dialog` service is registered in `dialog_service.js` via `registry.category("services").add("dialog", dialogService)`. Since `ai_debug.assets` includes `('include', 'web.assets_backend')`, all Odoo web services including `dialog` are included. However, the `dialog` service requires an `overlay` service which requires the full env.

**How to avoid:** Verify the `dialog` service works in the standalone context before building TextPopupDialog. The `mountComponent` from `@web/env` should include all standard Odoo services (Phase 4 uses this pattern and it works for `bus_service`). If not, implement a custom lightweight popup using a CSS-positioned `<div>` with `useState`/`useRef` instead of the dialog service.

**Alternative if dialog fails:** Build a simple in-component popup as an absolutely positioned overlay div within the detail panel. Use `useState({ popupOpen: false, popupContent: "" })` and `t-if="state.popupOpen"`. This avoids the dialog service dependency entirely.

### Pitfall 6: Notebook Bootstrap Styles Conflicting with Dark Theme

**What goes wrong:** `Notebook` renders Bootstrap `nav-tabs` with light-theme colors (white background, dark text) that clash with the app's dark Catppuccin theme.

**Why it happens:** The Notebook uses Odoo Bootstrap classes designed for the light backend UI. The AI debug app overrides the whole background but not the Bootstrap nav classes.

**How to avoid:** Add SCSS overrides in `app.scss` targeting `.ai-debug-detail .o_notebook .nav-tabs` to force dark-theme colors. Alternatively, don't use `Notebook` and instead hand-roll a simple custom tab bar using the existing button/div patterns already established in `app.scss` (a ~30-line addition).

**Recommendation:** Given the existing dark theme, a lightweight custom tab bar (using `useState({ activeTab: "..." })`) may be less friction than overriding Bootstrap. This is Claude's discretion.

### Pitfall 7: Large Payload Memory Impact

**What goes wrong:** After 10+ agentic loops, the trace Maps hold full conversation histories (potentially thousands of message tokens) causing browser memory pressure.

**Why it happens:** Phase 7 adds `messages_sent` (full conversation history per iteration) and `state_before`/`state_after` to every stored entry.

**How to avoid:** This is a developer tool used in active debugging sessions (not long-running). The existing `clearAll()` button handles this. No automatic eviction is needed for v1.1.

## Code Examples

### Extending _onNewTrace to store full payload

```javascript
// Source: verified from ai_session.py new_trace payload fields
this._onNewTrace = (payload) => {
    const iterations = reactive(new Map());
    this.traces.set(payload.trace_id, {
        trace_id: payload.trace_id,
        agent_name: payload.agent_name || "Unknown Agent",
        model_name: payload.model_name || "",
        status: "running",
        started_at: new Date(),
        ended_at: null,
        duration_ms: null,
        expanded: true,
        iterations,
        // Phase 7 additions:
        instructions: payload.instructions || "",
        tools: payload.tools || [],
        state_snapshot: payload.state_snapshot || {},
    });
    this._lastArrivedId = payload.trace_id;
    this._flashId = payload.trace_id;
    this._needsScroll = true;
    // Auto-select if nothing selected (SESS-03 + CONTEXT.md decision)
    if (this.state.selectedId === null) {
        this.state.selectedId = payload.trace_id;
        this.state.selectedType = "trace";
    }
};
```

### Extending _onIteration to store full payload

```javascript
// Source: verified from ai_session.py iteration payload fields
this._onIteration = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    if (!trace.iterations.has(payload.iteration_id)) {
        const toolCalls = reactive(new Map());
        trace.iterations.set(payload.iteration_id, {
            iteration_id: payload.iteration_id,
            trace_id: payload.trace_id,
            iteration_index: payload.iteration_index,
            has_error: !!payload.error,
            receivedAt: new Date(),
            expanded: false,
            toolCalls,
            // Phase 7 additions:
            messages_sent: payload.messages_sent || [],
            raw_response: payload.raw_response || null,
            is_final: payload.is_final || false,
            error: payload.error || null,
        });
        this._lastArrivedId = payload.iteration_id;
        this._needsScroll = true;
    }
};
```

### Extending _onToolCall to store full payload

```javascript
// Source: verified from ai_session.py tool_call payload fields
this._onToolCall = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    const iteration = trace.iterations.get(payload.iteration_id);
    if (!iteration) return;
    iteration.toolCalls.set(payload.tool_call_id, {
        tool_call_id: payload.tool_call_id,
        iteration_id: payload.iteration_id,
        tool_name: payload.tool_name,
        success: payload.success,
        // Phase 7 additions:
        args: payload.args || {},
        result: payload.result,
        error: payload.error || null,
        state_before: payload.state_before || {},
        state_after: payload.state_after || {},
        call_id: payload.call_id || null,
    });
};
```

### LoopDetail component skeleton

```javascript
// Source: OWL Component + Notebook from @web/core/notebook/notebook
import { Component } from "@odoo/owl";
import { Notebook } from "@web/core/notebook/notebook";
import { CopyButton } from "@web/core/copy_button/copy_button";
import { useService } from "@web/core/utils/hooks";
import { JsonTree } from "./json_tree";
import { TextPopupDialog } from "./text_popup";

export class LoopDetail extends Component {
    static template = "ai_debug.LoopDetail";
    static components = { Notebook, CopyButton, JsonTree };
    static props = {
        trace: Object,  // full trace entry from this.traces Map
    };

    setup() {
        this.dialog = useService("dialog");
    }

    openTextPopup(title, content) {
        this.dialog.add(TextPopupDialog, { title, content, language: "markdown" });
    }

    // RAG context: system messages from first iteration that are not the main instructions
    get ragContextMessages() {
        const firstIter = [...this.props.trace.iterations.values()][0];
        if (!firstIter) return null;
        return firstIter.messages_sent.filter(
            m => m.role === "system" && m.content !== this.props.trace.instructions
        );
    }
}
```

### JsonTree component skeleton

```javascript
// Source: recursive OWL component pattern (no external library needed)
import { Component, useState } from "@odoo/owl";

const TRUNCATION_THRESHOLD = 300;

export class JsonTree extends Component {
    static template = "ai_debug.JsonTree";
    static components = { JsonTree };  // self-reference for recursion
    static props = {
        data: true,
        label: { type: String, optional: true },
        depth: { type: Number, optional: true },
    };
    static defaultProps = { depth: 0 };

    setup() {
        this.state = useState({
            expanded: this.props.depth < 2,
        });
    }

    get type() {
        if (this.props.data === null) return "null";
        if (Array.isArray(this.props.data)) return "array";
        return typeof this.props.data;
    }

    get isExpandable() {
        return this.type === "object" || this.type === "array";
    }

    get childCount() {
        if (!this.isExpandable) return 0;
        return Array.isArray(this.props.data)
            ? this.props.data.length
            : Object.keys(this.props.data || {}).length;
    }

    get entries() {
        if (this.type === "array") return this.props.data.map((v, i) => [String(i), v]);
        if (this.type === "object") return Object.entries(this.props.data || {});
        return [];
    }

    get isLongString() {
        return this.type === "string" && this.props.data.length > TRUNCATION_THRESHOLD;
    }

    get displayString() {
        if (this.isLongString) return this.props.data.slice(0, TRUNCATION_THRESHOLD) + "...";
        return this.props.data;
    }
}
```

### State diff computation

```javascript
// Source: custom algorithm, no library needed; state is a JSON object
computeDiff(before, after) {
    const b = before || {};
    const a = after || {};
    const allKeys = new Set([...Object.keys(b), ...Object.keys(a)]);
    return [...allKeys].map(key => {
        const bVal = b[key];
        const aVal = a[key];
        if (!(key in b)) return { key, type: "added", before: undefined, after: aVal };
        if (!(key in a)) return { key, type: "removed", before: bVal, after: undefined };
        const changed = JSON.stringify(bVal) !== JSON.stringify(aVal);
        return { key, type: changed ? "changed" : "unchanged", before: bVal, after: aVal };
    });
}
```

### SCSS for detail panel layout

```scss
// Detail panel outer layout
.ai-debug-detail {
    flex: 1;
    overflow-y: auto;
    background-color: #11111b;
    display: flex;
    flex-direction: column;
}

// Detail header bar (type badge + name)
.ai-detail-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px 16px;
    border-bottom: 1px solid #313244;
    font-size: 13px;
    flex-shrink: 0;
}

.ai-detail-type-badge {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    padding: 2px 6px;
    border-radius: 4px;
    background-color: #313244;
    color: #89b4fa;
}

// Notebook dark theme override
.ai-debug-detail .o_notebook {
    flex: 1;
    display: flex;
    flex-direction: column;

    .nav-tabs {
        background-color: #181825;
        border-bottom: 1px solid #313244;

        .nav-link {
            color: #6c7086;
            border: none;
            border-bottom: 2px solid transparent;
            padding: 8px 16px;

            &.active {
                color: #cdd6f4;
                background-color: transparent;
                border-bottom-color: #89b4fa;
            }

            &:hover:not(.active) {
                color: #a6adc8;
            }
        }
    }

    .o_notebook_content {
        flex: 1;
        overflow-y: auto;
        background-color: #11111b;
    }
}

// Section within a tab (header + content)
.ai-detail-section {
    padding: 12px 16px;
    border-bottom: 1px solid #181825;
}

.ai-detail-section-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;

    span:first-child {
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        color: #6c7086;
    }
}

// Long text preview (truncated; click to expand)
.ai-detail-text-preview {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 12px;
    color: #a6adc8;
    line-height: 1.5;
    cursor: pointer;
    border: 1px solid #313244;
    border-radius: 4px;
    padding: 8px;
    overflow: hidden;
    white-space: pre-wrap;
    word-break: break-all;
    max-height: 120px;

    &:hover {
        border-color: #89b4fa;
        color: #cdd6f4;
    }
}

// JSON tree viewer
.ai-json-tree {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 12px;
    line-height: 1.6;

    .ai-json-key { color: #89b4fa; }
    .ai-json-string { color: #a6e3a1; }
    .ai-json-number { color: #fab387; }
    .ai-json-boolean { color: #cba6f7; }
    .ai-json-null { color: #585b70; }

    .ai-json-toggle {
        cursor: pointer;
        color: #585b70;
        user-select: none;

        &:hover { color: #89b4fa; }
    }
}

// State diff grid
.ai-diff-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0;
    border: 1px solid #313244;
    border-radius: 4px;
    overflow: hidden;
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 12px;
}

.ai-diff-header {
    background-color: #181825;
    color: #6c7086;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 6px 12px;
    border-bottom: 1px solid #313244;
}

.ai-diff-cell {
    padding: 4px 12px;
    border-bottom: 1px solid #1e1e2e;
    word-break: break-all;
    white-space: pre-wrap;

    &.ai-diff-added { background-color: rgba(166, 227, 161, 0.1); }   // green tint
    &.ai-diff-removed { background-color: rgba(243, 139, 168, 0.1); } // red tint
    &.ai-diff-changed { background-color: rgba(249, 226, 175, 0.1); } // amber tint
    &.ai-diff-unchanged { color: #585b70; }
}

// Text popup content area
.ai-popup-content {
    font-family: "SF Mono", "Fira Code", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-word;
    margin: 0;
    color: #cdd6f4;
    background-color: #1e1e2e;
    padding: 16px;
    border-radius: 4px;
    max-height: 70vh;
    overflow-y: auto;
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Detail panel shows raw `selectedType + selectedId` string | Type-appropriate detail views with tabs and structured data | Phase 7 | Full observability of loop/iteration/tool call payloads |
| Sidebar selection drives no content | Auto-select newest trace so panel is never empty | Phase 7 | Better first-run UX for developers |
| Payload data discarded after sidebar update | Full payload stored in reactive Map entries | Phase 7 | Data available for display without re-fetch |

**Deprecated/outdated:**
- The `<div t-else="" class="ai-debug-detail-selected">Selected: ...</div>` placeholder in `app.xml`: replaced by the three detail components in Phase 7.
- The intermediate `<div t-elif="!state.selectedId" ...>Select a trace...</div>` empty state: replaced by the auto-select behavior (since data always has a selection once traces exist, this state only applies during a brief window before the first `new_trace` event, which is covered by the "Listening for agentic loops..." state).

## Open Questions

1. **Does the `dialog` service work in the standalone AI debug app?**
   - What we know: `mountComponent` from `@web/env` bootstraps the full Odoo service env, which includes all services registered via `registry.category("services")`. The `dialog` service is registered in `dialog_service.js` loaded via `web.assets_backend` (included in `ai_debug.assets`). The AI debug app already uses `bus_service` via `useService` successfully.
   - What's unclear: Whether the `overlay` service (dependency of `dialog`) is properly initialized in the standalone context.
   - Recommendation: Test `useService("dialog")` early in the implementation. If it fails, fall back to a lightweight in-component popup (CSS `position: fixed` div). This is Claude's discretion.

2. **Should the Notebook's Bootstrap nav-tabs be overridden or should a custom tab bar be built?**
   - What we know: The existing app is a dark theme (Catppuccin Mocha). Bootstrap nav-tabs are styled for light theme. The overrides needed are approximately 15-20 SCSS lines (documented above).
   - Recommendation: Start with the SCSS overrides. If they cause style battles, fall back to a custom tab bar (pure OWL `useState + t-if`, ~20 lines of SCSS). This decision is Claude's discretion.

3. **How deep should JsonTree default expansion be?**
   - Recommendation: Default expand to depth 1 (top-level keys visible, nested objects collapsed). This matches DevTools default behavior. Depth is Claude's discretion.

4. **Is `state_before`/`state_after` available per tool call or only per batch?**
   - What we know: From `ai_session.py`: "Captures state_before (before the batch runs) and state_after (after the batch completes) via deepcopy. This is Option B from research: batch-level granularity." Multiple tool calls in the same batch share the same `state_before` and `state_after` values.
   - Recommendation: Display the diff as-is. When multiple tool calls share the same state snapshot (batch-level), this is informational — all tool calls in a batch show the combined before/after diff. Add a note "State diff reflects entire tool batch" if multiple tool calls exist in the same iteration.

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/custom/ai_debug/models/ai_session.py` — complete bus payload field names verified for all four event types (`new_trace`, `iteration`, `tool_call`, `loop_end`)
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — current stored fields per Map entry; confirmed which fields are missing for Phase 7
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.xml` — current detail panel placeholder; empty state behavior confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/notebook/notebook.js` — Notebook component API, props, slot pattern verified
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/notebook/notebook.xml` — Notebook template confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/dialog/dialog.js` — Dialog component props, size options verified
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/dialog/dialog_service.js` — `dialog.add(Component, props)` API confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/copy_button/copy_button.js` — CopyButton: `content` prop (function), clipboard writeText, tooltip feedback verified
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/copy_button/copy_button.xml` — CopyButton template confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/prismjs/prism.js` — Prism.js available in Odoo bundle confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/html_editor/static/src/others/embedded_components/core/syntax_highlighting/syntax_highlighting_utils.js` — `Prism.highlight(value, Prism.languages[lang], lang)` API confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/owl/owl.js:2385-2395` — `useState` calls `reactive(state, render)` internally; Map reactivity confirmed via `COLLECTION_RAW_TYPES`
- `/Users/joseph/clones/odoo/custom/ai_debug/__manifest__.py` — `('include', 'web.assets_backend')` confirmed; all web core components available in bundle

### Secondary (MEDIUM confidence)

- `form_renderer.js:2`, `kanban_column_examples_dialog.js:2` — `import { Notebook } from "@web/core/notebook/notebook"` import path confirmed in production Odoo code
- `copy_clipboard_field.js:6` — `import { CopyButton } from "@web/core/copy_button/copy_button"` import path confirmed

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all imports verified in Odoo source; all component APIs read directly from source files
- Architecture: HIGH — bus payload fields verified from `ai_session.py`; current stored data verified from `app.js`; component API verified from Odoo source
- Pitfalls: HIGH — derived from direct code reading (pitfall 1 verified from `app.js` stored fields; pitfall 2 verified from `ai_session.py` payload structure; pitfall 3-4 from OWL source)
- Open questions: LOW confidence on dialog service in standalone context (untested); all other questions are implementation preferences, not blockers

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (OWL API and Odoo web core APIs are stable; `ai_session.py` payload fields locked by Phase 5 decisions)
