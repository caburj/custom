# Phase 6: Sidebar Tree - Research

**Researched:** 2026-02-21
**Domain:** OWL reactive state management / tree UI / real-time bus event integration
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tree visual style**
- Comfortable density (~32-36px rows), like VS Code file explorer
- Distinct icons per level type (loop, iteration, tool call) for visual hierarchy
- Expand/collapse via chevron icon only — clicking the row text selects the item
- New loops appear expanded by default, showing iterations as they arrive

**Real-time update behavior**
- Running loops/iterations show an animated indicator (pulsing dot or spinner) that stops on completion
- Completed loops show a checkmark icon; failed loops show an error icon (replaces spinner)
- New items animate in with a subtle slide-in or fade-in effect
- Sidebar always auto-scrolls to show the latest arriving item

**Selection & highlighting**
- Clicking a loop node selects it AND expands it (single action to drill in)
- Selected item gets both a background fill and a left border accent for maximum visibility
- Ancestor nodes of the selected item show a faint background tint (breadcrumb trail)
- When a new loop arrives during an active selection, the new entry briefly flashes to draw attention, then settles
- Selection is never stolen by incoming events (SIDE-05)

**Loop entry labeling**
- Loop entries: agent name + model name (e.g. "AccountMove Agent · claude-3.5")
- Iteration entries: iteration number + duration (e.g. "Iteration 3 · 2.1s")
- Tool call entries: tool name + success/failure status icon (e.g. "execute_kw ✔")
- Sidebar has a "Traces" header bar with a clear/trash button to wipe all traces and reset

### Claude's Discretion

- Exact icon choices for each level type
- Animation timing and easing curves
- Exact color values for selection highlight, ancestor tint, and flash effect
- How to compute iteration duration from available bus payload data
- Sidebar width and resize behavior

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SIDE-01 | Sidebar shows one entry per agentic loop, labeled by agent name | `new_trace` payload has `agent_name` and `model_name`; one entry per unique `trace_id` |
| SIDE-02 | Expanding a loop shows its iterations (latest on top) | `iteration` payloads carry `trace_id`, `iteration_id`, `iteration_index`; reverse display via `[...iterations].reverse()` or insertion at front of array |
| SIDE-03 | Expanding an iteration shows its tool calls | `tool_call` payloads carry `iteration_id`, `tool_call_id`, `tool_name`, `success`; child of iteration node |
| SIDE-04 | Clicking any item in the tree selects it and updates the detail panel | `useState` selection state; `t-on-click` handler sets selected ID; detail area reads selection |
| SIDE-05 | New loops appear in the sidebar without stealing focus from current selection | Selection state is managed separately from trace data; bus event handlers only modify data, never `selection` |
</phase_requirements>

## Summary

Phase 6 builds a three-level reactive sidebar tree (Loop > Iteration > Tool Call) driven by four bus event types already emitted by Phase 5: `new_trace`, `iteration`, `tool_call`, and `loop_end`. The entire data store lives in JavaScript memory — no persistence, no server round-trips after the initial subscription.

The correct OWL data model is a reactive `Map<trace_id, TraceNode>` stored on the app component, where each `TraceNode` contains an `iterations: Map<iteration_id, IterationNode>` and each iteration contains a `toolCalls: Map<tool_call_id, ToolCallNode>`. OWL's reactive system fully supports `Map` as a reactive collection type — `.set()`, `.get()`, `.delete()`, and iteration via `[...map.keys()]` all trigger re-renders correctly. This is verified in OWL source code (`COLLECTION_RAW_TYPES = ["Set", "Map", "WeakMap"]`).

Selection state is a simple `useState({ selectedId: null, selectedType: null })` separate from trace data. Bus handlers write only to the trace Map; no handler ever touches selection. This is how SIDE-05 (stable selection under concurrent updates) is satisfied without any coordination logic.

**Primary recommendation:** Use OWL `reactive(new Map())` for the trace store, `useState` for selection, and `onPatched` (or `useEffect`) for auto-scroll after new items arrive. Implement as a single `AiDebugApp` component with inline helper methods — no sub-components needed for v1.1 given the bounded tree depth.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@odoo/owl` — `useState` | bundled in Odoo | Reactive selection state (selected ID + type) | Already used in `app.js`; built into OWL |
| `@odoo/owl` — `reactive` | bundled in Odoo | Reactive Map for trace/iteration/tool_call collections | OWL reactive proxy supports Map natively; triggers re-render on `.set()` / `.delete()` |
| `@odoo/owl` — `useRef` | bundled in Odoo | DOM reference for auto-scroll to newest item | Standard OWL hook; `ref.el.scrollIntoView()` after patch |
| `@odoo/owl` — `onPatched` | bundled in Odoo | Trigger auto-scroll after re-render when new items arrive | Fires after every DOM patch; use a flag to only scroll when new item added |
| `@odoo/owl` — `useEffect` | bundled in Odoo | Alternative to onPatched for dependency-driven scroll | `() => [traces.size]` as dep triggers effect when count changes |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| CSS `@keyframes` / `animation` | native | Slide-in / fade-in for new items; pulsing dot for running state | Already established in `app.scss`; add new keyframes for tree animations |
| CSS custom properties (variables) | native | Color tokens for selection highlight, ancestor tint, flash | Avoids magic numbers scattered through SCSS |
| Unicode symbols / CSS `::before` content | native | Status icons (spinner ○, checkmark ✓, error ✗) | No icon library needed; use Unicode or CSS shapes |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `reactive(new Map())` | `useState({ traces: {} })` plain object | Object works but loses insertion-order preservation; Map preserves arrival order naturally for stable sidebar ordering |
| `reactive(new Map())` | Array with `findIndex` for updates | Array requires O(n) scans for updates by trace_id; Map gives O(1) get/set |
| Flat `useState` object | Nested reactive Maps | Flat object requires full re-render on any change; nested Maps scope re-renders to changed subtree |
| Sub-components per level | Flat template with `t-foreach` | Sub-components add file/import overhead; for 3-level tree with bounded depth, inline template is simpler |

**Installation:** No new packages needed. All dependencies are already in the OWL bundle and the existing `ai_debug.assets` bundle.

## Architecture Patterns

### Recommended Project Structure

```
ai_debug/static/src/app/
├── app.js        # AiDebugApp component (expand to add trace store + selection)
├── app.xml       # Sidebar tree template (expand existing template)
└── app.scss      # Styles (expand existing styles with tree + selection rules)
```

No new files are needed. All Phase 6 work extends the three existing files.

### Data Model

```javascript
// Trace store: reactive Map — triggers re-render on .set() / .delete()
// Structure:
traces = reactive(new Map());
// traces[trace_id] = {
//   trace_id: string,
//   agent_name: string,
//   model_name: string,
//   status: 'running' | 'success' | 'error' | 'max_iterations',
//   started_at: Date,
//   ended_at: Date|null,
//   duration_ms: number|null,
//   expanded: boolean,         // UI state: is loop node expanded?
//   iterations: Map            // reactive Map<iteration_id, IterationNode>
// }
//
// iterations[iteration_id] = {
//   iteration_id: string,
//   trace_id: string,
//   iteration_index: number,
//   started_at: Date,
//   ended_at: Date|null,
//   has_error: boolean,
//   expanded: boolean,
//   toolCalls: Map             // reactive Map<tool_call_id, ToolCallNode>
// }
//
// toolCalls[tool_call_id] = {
//   tool_call_id: string,
//   iteration_id: string,
//   tool_name: string,
//   success: boolean,
// }
```

**Iteration duration computation:** The `iteration` bus event does not include `started_at` or duration. Compute duration at the app level by tracking when the first `iteration` event for that trace_id was received (iteration_index=1 gives approximate loop start). Since the loop is linear (one iteration at a time), `started_at` for each iteration can be approximated as the received timestamp of the previous iteration's event. For display as "Iteration 3 · 2.1s", track `receivedAt` on each iteration node and compute duration as `nextIteration.receivedAt - thisIteration.receivedAt`. The duration field in `loop_end` gives total loop duration. For running iterations (no next iteration yet), show a spinner instead of duration.

### Pattern 1: Reactive Map as Trace Store

**What:** Use `reactive(new Map())` to hold traces. OWL's reactive proxy wraps Map's `.set()` / `.get()` / `.delete()` / iteration methods with observer/notification hooks.

**When to use:** Any collection that grows dynamically and needs to trigger re-renders when items are added or modified.

**Verified in OWL source (`owl.js` line 1928, 2299-2314):**
```javascript
// OWL source confirms Map is in COLLECTION_RAW_TYPES
const COLLECTION_RAW_TYPES = ["Set", "Map", "WeakMap"];

// Map handler wraps all key operations with reactivity:
// .set() → notifyReactives(target, KEYCHANGES) + notifyReactives(target, key)
// .get() → observeTargetKey(target, key, callback)
// [...map.keys()] → observeTargetKey(target, KEYCHANGES, callback)
```

**Usage in component `setup()`:**
```javascript
// Source: OWL reactive Map pattern confirmed in codebase
import { Component, useState, reactive, onMounted, onWillUnmount, onPatched, useRef } from "@odoo/owl";

setup() {
    // Separate reactive Maps for the data tree
    this.traces = reactive(new Map());

    // Simple useState for selection (does NOT live in the Map)
    this.state = useState({
        selectedId: null,
        selectedType: null,   // 'trace' | 'iteration' | 'tool_call'
    });

    // ...bus subscriptions
}
```

**Usage in XML template:**
```xml
<!-- Iterate over Map keys — spread-to-array pattern used in Odoo production code -->
<!-- Source: web/static/src/search/search_panel/search_panel.xml line 230 -->
<t t-foreach="[...traces.keys()]" t-as="traceId" t-key="traceId">
    <t t-set="trace" t-value="traces.get(traceId)"/>
    <!-- render trace row -->
</t>
```

### Pattern 2: Bus Event Handlers Writing to Reactive Maps

**What:** Each bus notification type updates the appropriate Map entry. The reactive proxy triggers re-renders automatically.

**When to use:** Any component that needs to process streaming events and reflect them in a tree UI.

```javascript
// app.js — bus notification handlers
this._onNewTrace = (payload) => {
    // Creates a new trace entry; iterations Map is also reactive
    const iterations = reactive(new Map());
    this.traces.set(payload.trace_id, {
        trace_id: payload.trace_id,
        agent_name: payload.agent_name || 'Unknown Agent',
        model_name: payload.model_name || '',
        status: 'running',
        started_at: new Date(),
        ended_at: null,
        duration_ms: null,
        expanded: true,     // new loops start expanded
        iterations,
    });
    this._lastArrivedId = payload.trace_id;
    this._needsScroll = true;
};

this._onIteration = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    const toolCalls = reactive(new Map());
    trace.iterations.set(payload.iteration_id, {
        iteration_id: payload.iteration_id,
        trace_id: payload.trace_id,
        iteration_index: payload.iteration_index,
        has_error: !!payload.error,
        receivedAt: new Date(),
        expanded: false,
        toolCalls,
    });
    this._lastArrivedId = payload.iteration_id;
    this._needsScroll = true;
};

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
    });
};

this._onLoopEnd = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    trace.status = payload.termination_reason === 'success'
        ? 'success'
        : payload.termination_reason === 'max_iterations'
        ? 'max_iterations'
        : 'error';
    trace.ended_at = new Date();
    trace.duration_ms = payload.duration_ms;
    // NEVER modify this.state.selectedId here — SIDE-05
};
```

### Pattern 3: Stable Selection Under Concurrent Updates (SIDE-05)

**What:** Selection state lives in `useState`, trace data lives in reactive Maps. They are never coupled. Bus handlers only write to the Maps. Handlers never read or write `this.state.selectedId`.

**When to use:** Any real-time UI where background updates must not steal focus.

```javascript
// Selection is mutated ONLY by user click handlers, never by bus events
selectItem(id, type) {
    this.state.selectedId = id;
    this.state.selectedType = type;
    // If selecting a loop, also expand it
    if (type === 'trace') {
        const trace = this.traces.get(id);
        if (trace) trace.expanded = true;
    }
}

// Bus handlers NEVER touch this.state.selectedId
this._onNewTrace = (payload) => {
    // ...update this.traces only
    // Do NOT set this.state.selectedId = payload.trace_id
};
```

### Pattern 4: Auto-Scroll to Latest Item

**What:** After a new trace/iteration arrives, scroll the sidebar to show the newest item. Use `useRef` to get the sidebar container and call `scrollIntoView` on the last item element.

**When to use:** Any streaming list that should keep the latest item visible.

```javascript
// In setup():
this.sidebarRef = useRef("sidebar");
this._needsScroll = false;
this._lastArrivedId = null;

onPatched(() => {
    if (this._needsScroll && this._lastArrivedId && this.sidebarRef.el) {
        const el = this.sidebarRef.el.querySelector(
            `[data-node-id="${this._lastArrivedId}"]`
        );
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }
        this._needsScroll = false;
    }
});
```

```xml
<!-- Template: mark each node with data-node-id for scroll targeting -->
<div class="ai-tree-row" t-att-data-node-id="traceId" t-on-click="() => this.selectItem(traceId, 'trace')">
    ...
</div>
```

**Source:** Odoo uses `scrollIntoView` with same options in `settings_page.js:90` and `webclient.js:129`.

### Pattern 5: Running Status Visual Indicator

**What:** A trace/iteration with `status === 'running'` shows a pulsing dot (CSS animation). A completed trace shows ✓ or ✗.

**Implementation:**
- `status: 'running'` → pulsing dot via existing `.ai-debug-pulse-dot` CSS animation (already in `app.scss`)
- `status: 'success'` → ✓ character or Unicode `\u2713` in a `<span>`
- `status: 'error'` → ✗ or `\u2717`
- `status: 'max_iterations'` → `⏸` or similar

```xml
<span t-if="trace.status === 'running'" class="ai-debug-pulse-dot small"/>
<span t-elif="trace.status === 'success'" class="ai-tree-status success">✓</span>
<span t-elif="trace.status === 'error'" class="ai-tree-status error">✗</span>
<span t-elif="trace.status === 'max_iterations'" class="ai-tree-status warn">⏸</span>
```

### Pattern 6: Reverse Chronological Iteration Order (SIDE-02)

**What:** Iterations must appear latest-on-top within a loop. Map preserves insertion order (newest at end). Reverse display for rendering.

**When to use:** Any list where newest-first display is needed but data arrives oldest-first.

```xml
<!-- Reverse the iteration keys array for display -->
<t t-foreach="[...trace.iterations.keys()].reverse()" t-as="iterationId" t-key="iterationId">
    <t t-set="iteration" t-value="trace.iterations.get(iterationId)"/>
    ...
</t>
```

**Alternative:** Insert at front of array instead of Map. However, Map preserves the natural `trace_id → iteration_id → tool_call_id` parent lookup structure. Reversing the keys array for display is cheaper than maintaining a separate reverse-ordered structure.

### Pattern 7: Chevron Expand/Collapse

**What:** Chevron-only expand/collapse (row click selects, chevron click toggles expand). Mutation of `trace.expanded` or `iteration.expanded` on the reactive object triggers re-render.

```xml
<div class="ai-tree-row" t-att-class="{'selected': state.selectedId === traceId}">
    <span
        class="ai-tree-chevron"
        t-att-class="{'expanded': trace.expanded}"
        t-on-click.stop="() => this.toggleExpand(traceId, 'trace')"
    >›</span>
    <span class="ai-tree-label" t-on-click="() => this.selectItem(traceId, 'trace')">
        <t t-esc="trace.agent_name"/> · <t t-esc="trace.model_name"/>
    </span>
    ...status icon...
</div>
```

```javascript
toggleExpand(id, type) {
    if (type === 'trace') {
        const trace = this.traces.get(id);
        if (trace) trace.expanded = !trace.expanded;
    } else if (type === 'iteration') {
        // Need to find the iteration — trace_id is available from context
    }
}
```

**Note:** The `.stop` modifier on the chevron click prevents event bubbling to the row's select handler (`.stop` = `event.stopPropagation()`).

### Pattern 8: Flash Effect for New Arrivals

**What:** When a new loop arrives while another is selected, flash the new entry to draw attention. Implement by adding a CSS class `flash` to the new element, then removing it after the animation completes.

```javascript
this._onNewTrace = (payload) => {
    // ...create trace entry
    // After DOM updates (onPatched), add flash class and remove after animation
    this._flashId = payload.trace_id;
};

onPatched(() => {
    if (this._flashId) {
        const el = this.sidebarRef.el?.querySelector(`[data-node-id="${this._flashId}"]`);
        if (el) {
            el.classList.add('ai-tree-flash');
            setTimeout(() => el.classList.remove('ai-tree-flash'), 1200);
        }
        this._flashId = null;
    }
    // ...scroll logic
});
```

```scss
@keyframes ai-tree-flash {
    0% { background-color: rgba(137, 180, 250, 0.3); }  // brief blue flash
    100% { background-color: transparent; }
}

.ai-tree-row.ai-tree-flash {
    animation: ai-tree-flash 1.2s ease-out forwards;
}
```

### Pattern 9: Ancestor Tint (Breadcrumb Trail)

**What:** When an iteration or tool call is selected, its parent loop node gets a faint background tint. Compute this in a getter.

```javascript
get selectedTraceId() {
    if (this.state.selectedType === 'trace') return this.state.selectedId;
    if (this.state.selectedType === 'iteration') {
        // Find which trace owns this iteration
        for (const [traceId, trace] of this.traces) {
            if (trace.iterations.has(this.state.selectedId)) return traceId;
        }
    }
    if (this.state.selectedType === 'tool_call') {
        // Find which trace owns this tool_call's iteration
        for (const [traceId, trace] of this.traces) {
            for (const [, iter] of trace.iterations) {
                if (iter.toolCalls.has(this.state.selectedId)) return traceId;
            }
        }
    }
    return null;
}

get selectedIterationId() {
    if (this.state.selectedType === 'iteration') return this.state.selectedId;
    if (this.state.selectedType === 'tool_call') {
        for (const [, trace] of this.traces) {
            for (const [iterId, iter] of trace.iterations) {
                if (iter.toolCalls.has(this.state.selectedId)) return iterId;
            }
        }
    }
    return null;
}
```

```xml
<div class="ai-tree-row"
     t-att-class="{
         'selected': state.selectedId === traceId,
         'ancestor': selectedTraceId === traceId and state.selectedId !== traceId
     }">
```

### Pattern 10: Clear/Reset Button

**What:** "Traces" header bar with a trash button that clears all traces and resets selection.

```javascript
clearAll() {
    this.traces.clear();           // reactive Map.clear() notifies all observers
    this.state.selectedId = null;
    this.state.selectedType = null;
}
```

### Anti-Patterns to Avoid

- **Storing trace data in `useState`:** `useState` wraps plain objects; Map reactivity requires `reactive()`. Using `useState({ traces: {} })` with a plain object works but loses insertion-order and requires `Object.values()` instead of the cleaner Map API.
- **Mutating selection from bus handlers:** Any bus handler that sets `this.state.selectedId` will steal focus (violates SIDE-05). Bus handlers touch ONLY the trace Maps.
- **Using one flat Map for all nodes:** A flat `nodeMap[id]` requires parent pointer traversal for ancestor tint lookups and breaks the clear-by-trace-id operation. Keep the nested `traces → iterations → toolCalls` structure.
- **Re-creating the iterations Map on `iteration` event:** If `_onIteration` creates a new `reactive(new Map())` for toolCalls on every call, it will blow away existing toolCalls. Create `toolCalls` once per iteration entry.
- **Triggering scroll from bus handlers directly:** DOM is not updated until after the render cycle. Use `onPatched` with a `_needsScroll` flag; the DOM element will exist when `onPatched` fires.
- **Using `t-key` as an index (`_index`):** For bus-driven lists, always use the stable `trace_id`/`iteration_id`/`tool_call_id` as `t-key`. Index-based keys cause OWL to re-create DOM nodes when list order changes.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Map-based reactive state | Manual notification system with `useState` + array | `reactive(new Map())` | OWL's reactive proxy handles Map natively (verified in source: `COLLECTION_RAW_TYPES`) |
| Stable re-renders on Map update | Manually calling `render()` or using event bus | Let reactive Map proxy trigger re-renders | OWL tracks Map reads in template and re-renders affected subtrees automatically |
| Scroll-after-new-item | `setTimeout` in bus handler | `onPatched` with `_needsScroll` flag | `onPatched` fires after DOM is updated; `setTimeout` may fire before DOM update |
| Status icons | Icon library import | CSS characters / Unicode | App is already styled dark-theme with custom CSS; no Bootstrap/FontAwesome in standalone bundle |
| Animation on entry | JS-based animation (GSAP, etc.) | CSS `@keyframes` + class toggle | Already established pattern in `app.scss`; no JS animation library available in bundle |

**Key insight:** OWL's reactive system is specifically designed for this pattern — nested reactive Maps with bus-driven updates. The framework handles all the subscription and notification plumbing. The component only needs to write to the Map and OWL schedules re-renders.

## Common Pitfalls

### Pitfall 1: Selection Stolen by Bus Events

**What goes wrong:** When `_onNewTrace` or `_onLoopEnd` sets `this.state.selectedId`, the current selection disappears and the user loses their view context (violates SIDE-05).

**Why it happens:** Conflating "new data arrived" with "change what the user is looking at." These are different concerns.

**How to avoid:** Strict separation: bus handlers → data Maps only; click handlers → `state.selectedId` only. Code review should flag any write to `state.selectedId` outside of `selectItem()`.

**Warning signs:** In testing, triggering a second loop while iteration #1 of loop #1 is selected causes the view to jump to the new loop.

### Pitfall 2: Reactive Map Iteration in Template

**What goes wrong:** `t-foreach="traces"` fails because OWL's `t-foreach` expects an array, not a Map directly.

**Why it happens:** Map is not iterable in the same way as Array in OWL templates.

**How to avoid:** Use `[...traces.keys()]` in the `t-foreach` expression, then `traces.get(key)` inside the loop. This is the pattern used in Odoo production code (`search_panel.xml:230`):

```xml
<!-- CORRECT: spread Map keys to array -->
<t t-foreach="[...traces.keys()]" t-as="traceId" t-key="traceId">
    <t t-set="trace" t-value="traces.get(traceId)"/>
</t>

<!-- WRONG: direct Map iteration -->
<t t-foreach="traces" t-as="trace" t-key="trace.trace_id">
```

**Warning signs:** Template render errors mentioning `traces is not iterable` or incorrect iteration behavior.

### Pitfall 3: Re-Creating Nested Maps on Update

**What goes wrong:** On receiving an `iteration` event, the handler creates a new `reactive(new Map())` for `toolCalls` every time the trace is updated. Existing tool call entries are lost because the old Map reference is replaced.

**Why it happens:** Confusing "create if not exists" with "always create." The Map for `toolCalls` should only be created once when the iteration is first inserted.

**How to avoid:**
```javascript
this._onIteration = (payload) => {
    const trace = this.traces.get(payload.trace_id);
    if (!trace) return;
    // Only create if not already present
    if (!trace.iterations.has(payload.iteration_id)) {
        trace.iterations.set(payload.iteration_id, {
            iteration_id: payload.iteration_id,
            toolCalls: reactive(new Map()),  // created ONCE
            // ...
        });
    }
    // Update mutable fields on existing entry if needed
};
```

**Warning signs:** Tool calls disappear from the tree when a second iteration event arrives for the same trace.

### Pitfall 4: Scroll Triggering Before DOM Update

**What goes wrong:** `scrollIntoView` is called on an element that doesn't exist yet because the DOM hasn't been updated by OWL.

**Why it happens:** Bus handlers run synchronously when the bus notification arrives. The DOM update is scheduled asynchronously by OWL's batching mechanism.

**How to avoid:** Set a `_needsScroll = true` flag in the bus handler and do the actual scroll in `onPatched`, which fires after OWL has updated the DOM. This is the established Odoo pattern (`settings_page.js` uses `useEffect(() => ..., () => [this.settingsRef.el, this.state.selectedTab])` for the same reason).

**Warning signs:** `scrollIntoView()` throws "Cannot read property 'scrollIntoView' of null."

### Pitfall 5: Iteration Duration Computation

**What goes wrong:** The `iteration` bus payload does not include a `duration_ms` field. Attempting to display iteration duration from the payload shows `undefined`.

**Why it happens:** The Python instrumentation captures `started_at` and `duration_ms` only at the loop level (`loop_end` event), not per-iteration.

**How to avoid:** Track `receivedAt: new Date()` on each iteration node in the frontend (set when the `iteration` event is processed). Duration for iteration N = `iteration[N+1].receivedAt - iteration[N].receivedAt`. For the last/running iteration, show spinner instead of duration. Loop total duration comes from `loop_end.duration_ms`.

**Warning signs:** Iteration duration shows NaN or undefined.

### Pitfall 6: `t-key` Using Loop Variable `_index`

**What goes wrong:** Using `t-foreach="..." t-key="traceId_index"` causes OWL to re-create DOM nodes when insertion order changes (e.g., a trace at position 0 gets replaced by a new trace). This breaks CSS animations and causes scroll position to reset.

**Why it happens:** Index-based keys tell OWL "this is position 0" not "this is trace `abc123`". When a new trace arrives and the array shifts, OWL thinks the old DOM node at position 0 is now the new trace.

**How to avoid:** Always use the stable unique ID as `t-key`:
```xml
<t t-foreach="[...traces.keys()]" t-as="traceId" t-key="traceId">
```

### Pitfall 7: `this.traces` vs `this.state.traces`

**What goes wrong:** Putting the reactive Map inside `useState` (`useState({ traces: new Map() })`) instead of using `reactive()` directly. `useState` wraps the object in its own reactive proxy but Map's proxy handler (in `useState`) may not properly intercept all Map operations.

**Why it happens:** `useState` and `reactive` serve different purposes. `useState` is designed for plain objects and arrays; `reactive` with a Map argument creates the correct Map proxy handler.

**How to avoid:** Use `this.traces = reactive(new Map())` as a class instance property, not a key inside `useState`. Read it directly in templates as `traces` (accessible on `this` in OWL templates).

**Warning signs:** Map updates don't trigger re-renders; sidebar stays empty even when `this.traces.set(...)` is called.

## Code Examples

### Complete `setup()` structure

```javascript
// Source: OWL reactive Map + useState pattern; bus subscription from existing app.js
import { Component, useState, reactive, onMounted, onWillUnmount, onPatched, useRef } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class AiDebugApp extends Component {
    static template = "ai_debug.App";
    static props = {};
    static components = {};

    setup() {
        this.busService = useService("bus_service");

        // Trace data store — reactive Map, NOT inside useState
        this.traces = reactive(new Map());

        // Selection state — completely separate from trace data
        this.state = useState({
            connectionStatus: "connecting",
            selectedId: null,
            selectedType: null,   // 'trace' | 'iteration' | 'tool_call'
        });

        // Scroll tracking
        this.sidebarRef = useRef("sidebar");
        this._needsScroll = false;
        this._flashId = null;
        this._lastArrivedId = null;

        // Bus handlers
        this._onNewTrace = (payload) => { /* ... */ };
        this._onIteration = (payload) => { /* ... */ };
        this._onToolCall = (payload) => { /* ... */ };
        this._onLoopEnd = (payload) => { /* ... */ };
        this._subscribedTypes = ["new_trace", "iteration", "tool_call", "loop_end"];

        onMounted(async () => {
            this.busService.addEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
            for (const type of this._subscribedTypes) {
                this.busService.subscribe(type, this[`_on${type.split('_').map(w => w[0].toUpperCase() + w.slice(1)).join('')}`]);
            }
            await this.busService.addChannel("ai_debug");
        });

        onWillUnmount(() => {
            this.busService.removeEventListener("BUS:WORKER_STATE_UPDATED", this._onWorkerState);
            for (const type of this._subscribedTypes) {
                this.busService.unsubscribe(type, /* ... */);
            }
            this.busService.deleteChannel("ai_debug");
        });

        onPatched(() => {
            // Auto-scroll to newest item
            if (this._needsScroll && this._lastArrivedId && this.sidebarRef.el) {
                const el = this.sidebarRef.el.querySelector(`[data-node-id="${this._lastArrivedId}"]`);
                if (el) el.scrollIntoView({ behavior: "smooth", block: "nearest" });
                this._needsScroll = false;
            }
            // Flash new loop arrivals
            if (this._flashId && this.sidebarRef.el) {
                const el = this.sidebarRef.el.querySelector(`[data-node-id="${this._flashId}"]`);
                if (el) {
                    el.classList.add('ai-tree-flash');
                    setTimeout(() => el.classList.remove('ai-tree-flash'), 1200);
                }
                this._flashId = null;
            }
        });
    }
}
```

### Template structure skeleton

```xml
<!-- Source: OWL t-foreach with Map keys — pattern from search_panel.xml:230 -->
<t t-name="ai_debug.App">
    <div class="ai-debug-app">
        <header class="ai-debug-header">...</header>
        <div class="ai-debug-main">
            <aside class="ai-debug-sidebar" t-ref="sidebar">
                <!-- Traces header bar -->
                <div class="ai-tree-header">
                    <span>Traces</span>
                    <button class="ai-tree-clear" t-on-click="clearAll">🗑</button>
                </div>

                <!-- Empty state -->
                <div t-if="traces.size === 0" class="ai-debug-sidebar-empty">
                    <span class="ai-debug-pulse-dot"/>
                    <span>Listening for agentic loops...</span>
                </div>

                <!-- Loop entries (newest last in Map, display reversed with CSS or array reverse) -->
                <t t-foreach="[...traces.keys()].reverse()" t-as="traceId" t-key="traceId">
                    <t t-set="trace" t-value="traces.get(traceId)"/>
                    <!-- Loop row -->
                    <div class="ai-tree-row level-0 ai-tree-entry"
                         t-att-class="{
                             'selected': state.selectedId === traceId,
                             'ancestor': selectedTraceId === traceId and state.selectedId !== traceId
                         }"
                         t-att-data-node-id="traceId"
                         t-on-click="() => this.selectItem(traceId, 'trace')">
                        <span class="ai-tree-chevron" t-att-class="{'expanded': trace.expanded}"
                              t-on-click.stop="() => this.toggleExpand(traceId, 'trace')">›</span>
                        <span class="ai-tree-icon loop-icon">⬡</span>
                        <span class="ai-tree-label">
                            <t t-esc="trace.agent_name"/> · <t t-esc="trace.model_name"/>
                        </span>
                        <!-- Status indicator -->
                        <span t-if="trace.status === 'running'" class="ai-debug-pulse-dot small"/>
                        <span t-elif="trace.status === 'success'" class="ai-tree-status success">✓</span>
                        <span t-elif="trace.status === 'error'" class="ai-tree-status error">✗</span>
                    </div>

                    <!-- Iterations (when expanded) — latest on top -->
                    <t t-if="trace.expanded">
                        <t t-foreach="[...trace.iterations.keys()].reverse()" t-as="iterationId" t-key="iterationId">
                            <t t-set="iteration" t-value="trace.iterations.get(iterationId)"/>
                            <div class="ai-tree-row level-1 ai-tree-entry"
                                 t-att-class="{'selected': state.selectedId === iterationId}"
                                 t-att-data-node-id="iterationId"
                                 t-on-click="() => this.selectItem(iterationId, 'iteration')">
                                <span class="ai-tree-chevron" t-att-class="{'expanded': iteration.expanded}"
                                      t-on-click.stop="() => this.toggleExpandIteration(traceId, iterationId)">›</span>
                                <span class="ai-tree-icon iteration-icon">↺</span>
                                <span class="ai-tree-label">
                                    Iteration <t t-esc="iteration.iteration_index"/>
                                    <t t-if="iteration.has_error"> · error</t>
                                </span>
                            </div>

                            <!-- Tool calls (when iteration expanded) -->
                            <t t-if="iteration.expanded">
                                <t t-foreach="[...iteration.toolCalls.keys()]" t-as="toolCallId" t-key="toolCallId">
                                    <t t-set="tc" t-value="iteration.toolCalls.get(toolCallId)"/>
                                    <div class="ai-tree-row level-2 ai-tree-entry"
                                         t-att-class="{'selected': state.selectedId === toolCallId}"
                                         t-att-data-node-id="toolCallId"
                                         t-on-click="() => this.selectItem(toolCallId, 'tool_call')">
                                        <span class="ai-tree-icon tc-icon">⚙</span>
                                        <span class="ai-tree-label"><t t-esc="tc.tool_name"/></span>
                                        <span t-if="tc.success" class="ai-tree-status success">✔</span>
                                        <span t-else="" class="ai-tree-status error">✗</span>
                                    </div>
                                </t>
                            </t>
                        </t>
                    </t>
                </t>
            </aside>

            <main class="ai-debug-detail">
                <!-- Phase 7: detail panel content based on state.selectedId + state.selectedType -->
                <div t-if="!state.selectedId" class="ai-debug-detail-empty">
                    <p>Select a trace, iteration, or tool call to inspect it.</p>
                </div>
                <div t-else="">
                    <!-- Placeholder for Phase 7 -->
                    <p>Selected: <t t-esc="state.selectedType"/> <t t-esc="state.selectedId"/></p>
                </div>
            </main>
        </div>
    </div>
</t>
```

### SCSS additions for tree

```scss
// Tree row base
.ai-tree-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 12px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: #6c7086;
    border-bottom: 1px solid #313244;
}

.ai-tree-entry {
    display: flex;
    align-items: center;
    height: 34px;           // ~32-36px per locked decision
    cursor: pointer;
    gap: 4px;
    padding-right: 8px;
    transition: background-color 0.1s ease;

    &:hover {
        background-color: #2a2a3e;
    }

    &.selected {
        background-color: #2d3748;
        border-left: 3px solid #89b4fa;   // left border accent
    }

    &.ancestor {
        background-color: rgba(137, 180, 250, 0.05);   // faint tint
    }
}

// Indent levels
.ai-tree-row.level-0 { padding-left: 8px; }
.ai-tree-row.level-1 { padding-left: 28px; }
.ai-tree-row.level-2 { padding-left: 48px; }

// Chevron rotation
.ai-tree-chevron {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    font-size: 12px;
    color: #585b70;
    transform: rotate(0deg);
    transition: transform 0.15s ease;
    flex-shrink: 0;

    &.expanded {
        transform: rotate(90deg);
    }
}

// Flash animation for new arrivals
@keyframes ai-tree-flash {
    0% { background-color: rgba(137, 180, 250, 0.25); }
    100% { background-color: transparent; }
}

.ai-tree-row.ai-tree-flash {
    animation: ai-tree-flash 1.2s ease-out forwards;
}

// Slide-in for new entries
@keyframes ai-tree-slide-in {
    from { opacity: 0; transform: translateY(-4px); }
    to { opacity: 1; transform: translateY(0); }
}

.ai-tree-entry {
    animation: ai-tree-slide-in 0.15s ease-out;
}

// Status icons
.ai-tree-status {
    margin-left: auto;
    font-size: 12px;
    flex-shrink: 0;

    &.success { color: #a6e3a1; }
    &.error { color: #f38ba8; }
    &.warn { color: #f9e2af; }
}

// Small pulse dot for running indicator
.ai-debug-pulse-dot.small {
    width: 8px;
    height: 8px;
    margin-left: auto;
    flex-shrink: 0;
}

// Label truncation
.ai-tree-label {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 13px;
    color: #cdd6f4;
}

.ai-tree-icon {
    font-size: 11px;
    color: #585b70;
    flex-shrink: 0;
}

// Clear button
.ai-tree-clear {
    background: none;
    border: none;
    color: #585b70;
    cursor: pointer;
    padding: 2px 4px;
    font-size: 13px;
    line-height: 1;

    &:hover { color: #f38ba8; }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DB-backed list views (v1.0 `ai.debug.trace` model) | Frontend-only reactive Maps | MIGR-02 (Phase 4) | No server round-trips; all state in browser memory |
| Array-based state with `.push()` | `reactive(new Map())` | Phase 6 design | O(1) lookup by ID; insertion-order preserved |
| Full re-render on any update | OWL reactive proxy scoped re-renders | OWL built-in | Only components reading changed Map keys re-render |

**Deprecated/outdated:**
- v1.0 `ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool_call` ORM models: deleted in MIGR-02 (Phase 4). Do not reference these.

## Open Questions

1. **Should new loops display at top or bottom of sidebar?**
   - What we know: CONTEXT.md says "new loops appear expanded by default" but doesn't specify order. Bus events arrive chronologically. VS Code file explorer appends at bottom. Many debugger tools show newest at top.
   - What's unclear: User preference for newest-at-top vs newest-at-bottom for loop entries.
   - Recommendation: Newest-at-top (reverse Map keys) for loops, consistent with the "iterations in reverse chronological order" locked decision. Document this choice and it can be toggled.

2. **Slide-in animation vs no animation for new tool call entries**
   - What we know: Locked decision says "new items animate in with subtle slide-in or fade-in." Tool calls arrive quickly in bursts during a tool batch.
   - What's unclear: Whether animating each individual tool call in a batch looks good or creates visual noise.
   - Recommendation: Apply animation to loop and iteration entries (rare, meaningful). Make tool call entries appear without animation or with a very short 80ms fade. This is Claude's discretion to decide during implementation.

3. **OWL reactive Map — is mutation of nested fields reactive?**
   - What we know: `reactive(new Map())` makes the Map reactive. Setting a value in the Map (`map.set(key, obj)`) is reactive. However, mutating a field on the object already in the Map (`map.get(key).status = 'success'`) depends on whether that object is also wrapped reactively.
   - What's unclear: If `trace.status = 'success'` in `_onLoopEnd` triggers a re-render automatically.
   - Recommendation (confirmed from OWL source `basicProxyHandler` line 2136): Objects returned by `map.get()` are wrapped with `possiblyReactive(Reflect.get(...))` — they ARE reactive if they were put in the Map via `reactive()`. Since we call `trace.iterations.set(...)` where `trace.iterations` is already reactive, the returned object from `trace.iterations.get(key)` is wrapped as reactive. Mutating `trace.status` directly triggers a re-render. This is HIGH confidence from OWL source.

4. **`useRef("sidebar")` vs finding the element via `document.querySelector`**
   - Recommendation: Use `useRef("sidebar")` with `t-ref="sidebar"` on the `<aside>` element. This is the OWL-native pattern for accessing DOM elements and properly scopes the reference to the component instance.

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/owl/owl.js` lines 1928, 2104-2314 — reactive() implementation, COLLECTION_RAW_TYPES confirmed, Map proxy handler verified
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/owl/owl.js` lines 2385, 6160, 6212 — useState, useRef, useEffect implementations
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/lib/owl/owl.js` lines 6287-6323 — full exports list (onPatched, onWillPatch, useEffect, useRef, reactive, useState all confirmed exported)
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/search/search_panel/search_panel.xml:230` — `[...values.keys()]` pattern in `t-foreach` confirmed in production Odoo code
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/search/search_panel/search_panel.js:9` — `reactive` import from `@odoo/owl` confirmed
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.js` — existing bus subscription pattern (already subscribes to `new_trace`, `iteration`, `tool_call`, `loop_end`)
- `/Users/joseph/clones/odoo/custom/ai_debug/static/src/app/app.scss` — existing color palette, `@keyframes ai-debug-pulse`, SCSS nesting patterns
- `/Users/joseph/clones/odoo/custom/ai_debug/models/ai_session.py` — bus payload field names (`trace_id`, `agent_name`, `model_name`, `iteration_id`, `iteration_index`, `has_tool_calls`, `is_final`, `tool_call_id`, `tool_name`, `success`) confirmed from implementation
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/webclient/settings_form_view/settings/settings_page.js:42-54, 86-91` — `useRef` + `scrollIntoView` pattern confirmed

### Secondary (MEDIUM confidence)

- `webclient.js:129` — `el.scrollIntoView(true)` pattern in Odoo (simpler form, same API)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in OWL source and production Odoo code
- Architecture: HIGH — data model verified from bus payload field names (read directly from `ai_session.py`); reactive Map pattern verified in OWL source
- Pitfalls: HIGH — derived from OWL source code analysis and Odoo production patterns; not speculative
- Open questions 3 resolved to HIGH — traced through `possiblyReactive` in OWL source

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (OWL API is stable; `ai_session.py` payload fields are locked by Phase 5)
