# Phase 15: Sidebar Rendering and Color Display — Research

**Researched:** 2026-02-23
**Domain:** OWL template restructuring, CSS tree nesting, SCSS guide lines, computed getters
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Scope reduction:** COLR-03, COLR-04, COLR-05 are deferred until Phase 14 ships (blocked on color assignment + IDB persistence). Phase 15 delivers TREE-01, TREE-02, TREE-03, TREE-04 only.

**Nesting visual treatment (TREE-01, TREE-02)**
- Subagent traces use the full two-line trace format (query title + agent·model meta line) at all nesting depths — identical to root traces, just indented
- Fixed ~20px left-padding increment per nesting level (no diminishing or capping)
- Thin vertical guide lines (VS Code / file-explorer style) connect parents to children
- Text truncation happens naturally via CSS ellipsis; no special handling for deep nesting

**Flat-within-trace layout (TREE-03)**
- Iterations remain collapsible groups with chevrons (expand/collapse hides or shows their tool calls)
- Tool calls render at the **same indent** as their parent iteration — not further indented
- Iteration rows use icon-based distinction from tool call rows (different prefix icon)
- Iteration rows show aggregate status: "Iteration N · X calls · Xs" (call count + timing)

**Subagent trace placement**
- Subagent traces appear at the **same indent level** as tool calls within the parent trace (not indented further under the spawning tool call)
- Visually distinguished by being full two-line trace rows among single-line tool call rows
- The spawning tool call has no special treatment — tree nesting conveys the parent-child relationship

**Collapse behavior (TREE-04)**
- Collapsing a trace hides all of its descendants: iterations, tool calls, and any nested subagent traces recursively
- Collapse state is per-row via the existing chevron mechanism

### Claude's Discretion
- Exact guide line styling (color, opacity, dash vs solid)
- Icon choices for iteration vs tool call distinction
- Chevron animation and transition details
- How aggregate call count is computed for running iterations

### Deferred Ideas (OUT OF SCOPE)
- COLR-03 (colored left border on trace rows) — blocked on Phase 14 color assignment
- COLR-04 (color legend in sidebar header) — blocked on Phase 14 color assignment
- COLR-05 (colored agent chip in detail panel header) — blocked on Phase 14 color assignment
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TREE-01 | Subagent traces nest visually under the parent tool call that spawned them in the sidebar | `sidebarNodes` computed getter with depth-first recursion; CSS `padding-left` calculated from depth * 20px |
| TREE-02 | Tree supports arbitrary recursive nesting depth (subagents of subagents render correctly) | Recursive JS helper passes depth as parameter; CSS uses inline style for computed indentation — no hardcoded level classes needed at depth > 2 |
| TREE-03 | Within a single trace, iterations and tool calls render at the same indentation level (flat within trace) | OWL template renders iteration rows and their tool call rows with same `padding-left`; iteration chevron still controls expand/collapse of tool call group |
| TREE-04 | Collapsing a parent trace hides all descendant traces, iterations, and tool calls | `sidebarNodes` getter only emits child trace nodes when the parent trace's `expanded` flag is true; existing collapse mechanism extended to cover descendants transitively |
</phase_requirements>

---

## Summary

Phase 15 is a pure frontend change: restructure how the sidebar tree template and JS compute which rows to render. The data is already stored correctly — every trace has `parent_trace_id` and `parent_tool_call_id` fields added in Phase 13, and Phase 14 will ensure the flat Map store is correct. Phase 15 only needs to: (1) introduce a `sidebarNodes` computed getter that builds a flat ordered list of nodes with explicit depth metadata, (2) rewrite the template to iterate over that list, and (3) add SCSS for VS Code-style guide lines and the flat-within-trace layout.

The critical locked decision from STATE.md is that OWL does **not** support template recursion — a component cannot call its own template with `t-call`. The correct pattern is a **JS-computed flat list** (`sidebarNodes` getter) where the depth-first traversal happens in JavaScript and emits plain node objects (`{type, id, depth, traceRef, ...}`) that the template iterates with a simple `t-foreach`. This avoids the recursive component anti-pattern entirely.

The within-trace flattening (TREE-03) changes the current 3-level hierarchy (level-0 trace → level-1 iteration → level-2 tool call) to a 2-level hierarchy within a trace: iteration rows and tool call rows share the same padding-left. Indentation is still needed to separate nested subagent traces from root traces, but the iteration→tool_call increment is eliminated.

**Primary recommendation:** Build a `get sidebarNodes()` getter in `app.js` that returns a flat array of node descriptors with `{ type, id, depth, ... }`, then replace the current nested `t-foreach` template with a single `t-foreach` over `sidebarNodes`. The CSS guide lines are pure SCSS — a `::before` pseudo-element or a left-border strip on a wrapper div.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| OWL (Odoo Web Library) | Bundled with Odoo master | Reactive component framework, `useState`, `useRef` | Already in use throughout the app |
| SCSS with `$o-*` variables | Odoo master | Styling — all colors must use Odoo design tokens | Project constraint: zero hardcoded colors |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Inline CSS style bindings in OWL | n/a | Dynamic depth-based padding | When CSS classes cannot express dynamic values (e.g., depth 5 would need .level-5) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| JS flat list (`sidebarNodes`) | Recursive OWL component | OWL does not support template recursion — JS flat list is mandatory |
| Inline `style` for depth-computed padding | Static `.level-N` classes | Classes can only handle finite known depths; inline style handles arbitrary depth |
| `::before` pseudo-element for guide line | Actual DOM element | Pseudo-element is simpler and doesn't affect layout; preferred |

**Installation:** No new packages. No `npm install` needed.

---

## Architecture Patterns

### Current Tree Structure (to be replaced)

The existing template (`app.xml`) uses a three-level nested `t-foreach`:
```
traces.keys().reverse()          → level-0 rows (.level-0)
  trace.iterations.keys()        → level-1 rows (.level-1)
    iteration.toolCalls.keys()   → level-2 rows (.level-2)
```

Static CSS classes `.level-0`, `.level-1`, `.level-2` set fixed `padding-left` values (4px, 24px, 44px). Child subagent traces are not rendered at all — they're just stored in the flat Map but never displayed.

### Target Tree Structure (Phase 15)

```
sidebarNodes (computed getter)   → flat array of node descriptors
  t-foreach node in sidebarNodes → single-level template loop
    t-if="node.type === 'trace'"     → trace row (two-line format, depth-aware padding)
    t-elif="node.type === 'iter'"    → iteration row (same indent as tool calls)
    t-elif="node.type === 'tc'"      → tool call row (same indent as iterations)
```

### Pattern 1: sidebarNodes Computed Getter

**What:** A getter on `AiDebugApp` that returns a flat ordered list of rendered-row descriptors using depth-first recursion in JS. Called every time OWL re-renders (reactive dependency tracking means it re-executes when `this.traces` or any `trace.expanded` / `iteration.expanded` changes).

**When to use:** Any time a tree structure has dynamic depth that can't be expressed with fixed template levels.

**Key design choices:**
- Returns plain objects (not reactive) — just used for iteration in template
- Depth starts at 0 for root traces; each level of subagent nesting adds 1
- Tool call rows and iteration rows share the same `depth` value as their owning trace (flat within trace)
- Only emits child rows when parent `expanded === true`
- Root traces are in reverse insertion order (newest first, matching current behavior)

**Example:**
```javascript
// In AiDebugApp class, after setup()

get sidebarNodes() {
    const nodes = [];
    // Root traces: those with no parent_trace_id, in reverse insertion order
    const allTraces = [...this.traces.values()];
    const rootTraces = allTraces
        .filter(t => !t.parent_trace_id)
        .reverse(); // newest first

    for (const trace of rootTraces) {
        this._collectTraceNodes(trace, 0, nodes);
    }
    return nodes;
}

_collectTraceNodes(trace, depth, nodes) {
    // 1. Emit the trace row itself
    nodes.push({ type: 'trace', id: trace.trace_id, depth, trace });

    if (!trace.expanded) return;

    // 2. Emit iterations and tool calls (flat: same depth as trace)
    // Reverse order: newest iteration first
    const iterKeys = [...trace.iterations.keys()].reverse();
    for (const iterId of iterKeys) {
        const iter = trace.iterations.get(iterId);
        nodes.push({ type: 'iter', id: iterId, depth, iter, trace });

        if (iter.expanded) {
            for (const [tcId, tc] of iter.toolCalls) {
                nodes.push({ type: 'tc', id: tcId, depth, tc, iter, trace });

                // 3. After this tool call, check for subagent traces spawned by it
                // A child trace has parent_trace_id === trace.trace_id
                // and parent_tool_call_id matching tc.call_id
                const childTraces = [...this.traces.values()].filter(
                    t => t.parent_trace_id === trace.trace_id &&
                         t.parent_tool_call_id === tc.call_id
                );
                for (const child of childTraces) {
                    this._collectTraceNodes(child, depth + 1, nodes);
                }
            }
        } else {
            // Iteration collapsed — still check for subagent traces in tool calls
            // (subagent traces are only visible if their parent iteration is expanded)
            // Per TREE-04: collapsing hides all descendants including subagent traces
            // So skip child trace emission when iteration is collapsed
        }
    }
}
```

**Important note on child trace placement:** Per the locked decision, subagent traces appear at the **same indent as tool calls** within the parent trace — which means `depth + 1` relative to the parent trace, since tool calls render at `depth` of the parent trace. The child trace itself starts a new depth context where its own children would be at `depth + 2`.

Wait — re-read the decision carefully: "Subagent traces appear at the same indent level as tool calls within the parent trace." Tool calls render at `depth` (same as parent trace). So subagent traces also render at `depth`... no, that can't be right for visual nesting.

**Clarification from CONTEXT.md:** The subagent trace is "at the same indent as tool calls within the **parent trace**." Tool calls are at `depth` (same as their parent trace). But the subagent trace **is** a child of the parent trace — so the subagent trace should render at `depth + 1` relative to the root (the parent trace's depth + 1). Within the parent trace, iterations and tool calls are at `depth` (matching the parent trace row). The subagent trace at `depth + 1` would naturally appear one level deeper than the parent trace's content.

**Correct interpretation:** Root traces are at depth=0. Their iterations/tool calls are also at depth=0 (flat within trace). Child subagent traces appear at depth=1. The child subagent's iterations/tool calls are at depth=1. Grandchild subagents appear at depth=2. This is consistent with the "same indent as tool calls within the parent trace" description — because tool calls in the parent are at depth=0, and the child trace is also at depth=1... actually that means one MORE indent than the parent's tool calls.

**Resolution:** The clearest reading: subagent traces are indented one level below the parent trace row (depth = parent_depth + 1). The parent trace's tool calls are at `parent_depth` (flat). The subagent trace header row is at `parent_depth + 1`. This gives visual nesting: the parent trace row is the "parent", and the child trace row is indented beneath it at the same position one would expect a "section" to be. Since tool calls are at `parent_depth`, the subagent trace at `parent_depth + 1` appears slightly deeper than the tool calls — which is fine. The CONTEXT.md wording "same indent as tool calls" likely means the subagent appears mixed in the same section as tool calls (not below a separate sub-header), not that pixel indentation is identical.

**Final sidebarNodes design:**
- Root trace row: `depth = 0`, padding = `depth * 20px`
- Root trace's iterations: `depth = 0` (same as parent trace)
- Root trace's tool calls: `depth = 0` (same as parent trace, same as iterations)
- Child subagent trace row: `depth = 1`, padding = `20px`
- Child subagent's iterations/tool calls: `depth = 1`
- Grandchild subagent trace row: `depth = 2`, padding = `40px`

This means trace rows at depth > 0 have visible indentation. Iterations and tool calls within a trace share that trace's depth indentation. Visual guide lines mark the depth.

### Pattern 2: Template Rewrite — Single t-foreach

**What:** Replace the current three nested `t-foreach` loops with a single loop over `sidebarNodes`.

**Example:**
```xml
<t t-foreach="sidebarNodes" t-as="node" t-key="node.id">

    <!-- Trace row (two-line format, same as current level-0) -->
    <t t-if="node.type === 'trace'">
        <div class="ai-tree-row ai-tree-trace-row"
             t-attf-style="padding-left: {{ node.depth * 20 + 4 }}px"
             t-att-class="{
                 'selected': state.selectedId === node.id,
                 'ancestor': selectedTraceId === node.id and state.selectedId !== node.id,
                 'ai-tree-has-guide': node.depth > 0
             }"
             t-att-data-node-id="node.id">
            <!-- checkbox only on root traces, or on all? keep checkbox only depth=0 -->
            <input t-if="node.depth === 0"
                   type="checkbox" class="ai-tree-row-check"
                   t-att-checked="state.checkedTraceIds.has(node.id)"
                   t-on-change.stop="() => this.toggleTraceCheck(node.id)"/>
            <span class="ai-tree-chevron"
                  t-att-class="{'expanded': node.trace.expanded}"
                  t-on-click.stop="() => this.toggleExpand(node.id, 'trace')">&#x203A;</span>
            <span class="ai-tree-label" t-on-click="() => this.selectItem(node.id, 'trace')">
                <!-- same two-line format as before -->
            </span>
            <!-- status indicators same as before -->
        </div>
    </t>

    <!-- Iteration row -->
    <t t-elif="node.type === 'iter'">
        <div class="ai-tree-row ai-tree-iter-row"
             t-attf-style="padding-left: {{ node.depth * 20 + 24 }}px"
             ...>
            <!-- iteration icon prefix (Claude's discretion) -->
            <!-- chevron for expand/collapse tool calls -->
            <!-- "Iteration N · X calls · Xs" label -->
        </div>
    </t>

    <!-- Tool call row -->
    <t t-elif="node.type === 'tc'">
        <div class="ai-tree-row ai-tree-tc-row"
             t-attf-style="padding-left: {{ node.depth * 20 + 24 }}px"
             ...>
            <!-- tool call icon prefix (Claude's discretion) -->
            <!-- tool name label -->
            <!-- success/error status icon -->
        </div>
    </t>

</t>
```

Note: `padding-left` for iterations and tool calls includes the base offset (24px matching current level-1) plus the depth-based increment. The iteration and tool call rows use the **same** padding-left value (flat within trace — TREE-03 decision).

### Pattern 3: VS Code Guide Lines via SCSS

**What:** Thin vertical lines at each depth level, positioned using pseudo-elements or a left-border technique.

**Approach — `::before` pseudo-element on depth > 0 rows:**
```scss
// Guide line: thin vertical left border for nested rows
.ai-tree-row[data-depth] {
    position: relative;
}

// Depth-1 guide line at 20px from left edge (= depth * 20px + guide offset)
// Implemented via a left-border strip on a wrapper, or ::before pseudo
.ai-tree-row.ai-tree-has-guide::before {
    content: '';
    position: absolute;
    left: 12px; // approximate center of the parent trace's chevron area
    top: 0;
    bottom: 0;
    width: 1px;
    background-color: $o-gray-300;  // light mode
    opacity: 0.6;
}
```

**Alternative — border-left on rows at depth > 0:**
Since padding-left encodes depth, a simpler approach is to use a transparent left border on a wrapper element at the nesting level. The existing `.ai-json-nested` style in the app uses this pattern already:
```scss
.ai-json-nested {
    margin-left: 6px;
    padding-left: 10px;
    border-left: 1px solid $o-gray-300;
}
```

The same technique can work for sidebar rows: add a thin left border to a container that wraps all rows at a given depth. However, since rows are in a flat list (not nested DOM), the `::before` pseudo-element approach is more practical.

**Recommended:** Use `position: relative` on `.ai-tree-row` + a `::before` pseudo-element positioned based on `data-depth` attribute set in the template. Since SCSS cannot dynamically compute pseudo-element positions from data attributes alone, the simplest approach is to set a CSS custom property via `t-attf-style`:

```xml
<!-- Set --depth custom property for guide line positioning -->
<div class="ai-tree-row ai-tree-trace-row"
     t-attf-style="--ai-node-depth: {{ node.depth }}; padding-left: {{ node.depth * 20 + 4 }}px">
```

```scss
.ai-tree-row {
    position: relative;
}
.ai-tree-row.ai-tree-has-guide::before {
    content: '';
    position: absolute;
    // Guide line at the center of the chevron at the parent's level:
    // parent depth = current depth - 1, parent chevron center ≈ (depth-1)*20 + 14px
    left: calc(var(--ai-node-depth, 0) * 20px - 8px);
    top: 0;
    bottom: 0;
    width: 1px;
    background-color: $o-gray-300;
    opacity: 0.5;
}
```

### Pattern 4: Flat Within-Trace Layout (TREE-03)

**What:** Current layout has iteration at padding-left 24px, tool calls at padding-left 44px. New layout: both at padding-left 24px (relative to their owning trace depth).

**Key change in CSS:** Remove `.ai-tree-row.level-2 { padding-left: 44px; }`. Both iteration and tool call rows get `padding-left: {{ node.depth * 20 + 24 }}px`.

**Visual distinction:** Iteration rows need an icon to distinguish them from tool call rows at the same indent. Recommended icons:
- Iteration rows: `▶` or `⟳` or a loop/cycle icon (prefix before the label)
- Tool call rows: `⚙` or `→` (wrench-like icon prefix)

These are Claude's discretion per CONTEXT.md.

**Iteration row label format:** "Iteration N · X calls · Xs"
- `N` = `iteration.iteration_index`
- `X calls` = `iteration.toolCalls.size` (use "call" for 1, "calls" for plural)
- `Xs` = duration via existing `getIterationDuration()` helper (already works)
- For running iterations: show pulse dot instead of duration (same as current behavior)
- For running iterations with 0 completed calls yet: show "0 calls"

### Anti-Patterns to Avoid

- **Recursive OWL component template:** OWL does not support recursive template calls. Do not attempt `<t t-call="self"/>` or create a `TraceNode` component that instantiates itself.
- **Level-N CSS classes for depth:** Hard-codes the depth range. Use inline `style` with calculated `padding-left` for depth-based indentation.
- **Re-traversing this.traces inside the template:** Expensive O(n) lookup on every render. Do all traversal in the JS getter, emit complete node descriptors.
- **Emitting child trace nodes when parent trace is collapsed:** The `sidebarNodes` getter must respect `trace.expanded` when deciding whether to recursively emit child trace nodes. Collapsing must hide all descendants (TREE-04).
- **Including checkbox on nested traces:** The bulk-select checkbox flow (checkedTraceIds, delete, export) currently targets root traces. Nested subagent traces should not have checkboxes in Phase 15 — this avoids complicating the bulk delete logic which would need to handle orphaned child traces.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Recursive tree rendering | Custom recursive OWL component | JS flat list + single `t-foreach` | OWL template recursion is unsupported |
| Depth-aware indentation | Level-N CSS classes | Inline `padding-left: N * 20px` via `t-attf-style` | Arbitrary depth support |
| Guide lines via DOM elements | `<div class="guide-line"/>` | CSS `::before` pseudo-element | Cleaner DOM, no layout impact |
| Finding child traces of a tool call | Nested Map lookup in template | Pre-computed in `_collectTraceNodes` JS | Template should be display-only |

**Key insight:** The template should be a dumb renderer of pre-computed node descriptors. All tree-walking logic belongs in JavaScript.

---

## Common Pitfalls

### Pitfall 1: sidebarNodes is not reactive by default

**What goes wrong:** `get sidebarNodes()` reads from `this.traces` (reactive Map) and from `trace.expanded` / `iteration.expanded`. If OWL's render function does not observe all these reads, the tree won't update when iteration expand state changes.

**Why it happens:** OWL reactive proxies track property reads made during a render. The getter runs during render, so reads on `this.traces` (Map iteration) and `trace.expanded` are tracked. However, `iteration.expanded` is on a plain object nested inside a `reactive(new Map())` — OWL should track this read IF the getter is called during rendering (i.e., referenced in the template as `sidebarNodes`).

**How to avoid:** Ensure `sidebarNodes` is referenced in the template as a simple getter expression (not cached), so it's re-evaluated on every render. Do NOT memoize it with a separate `useState` flag — that breaks reactivity. The getter pattern is the correct OWL pattern for computed values.

**Warning signs:** Tree doesn't re-render after toggling expand/collapse.

### Pitfall 2: Child traces appear out of order

**What goes wrong:** `this.traces.values()` yields traces in insertion order. Child traces may be inserted after parent traces. The `_collectTraceNodes` recursive helper must look up child traces **by parent linkage**, not by position in the Map.

**Why it happens:** The flat Map insertion order is arrival order (bus events), not logical tree order.

**How to avoid:** In `_collectTraceNodes`, after emitting tool call rows, filter `this.traces.values()` to find traces with `parent_trace_id === currentTrace.trace_id` and `parent_tool_call_id === tc.call_id`. This is O(n) per tool call, but n is small in practice (debugger sessions have few traces). Acceptable performance.

**Warning signs:** Subagent traces appear at the wrong nesting level or at root level.

### Pitfall 3: Checkbox logic breaks for nested traces

**What goes wrong:** `toggleTraceCheck(traceId)` stores IDs in `checkedTraceIds`, and `deleteCheckedTraces` deletes by ID. If subagent traces are added to `checkedTraceIds`, deleting them leaves orphaned parent reference fields. More importantly, `allChecked` computes `checkedTraceIds.size === this.traces.size` which would include subagent traces.

**Why it happens:** The checkbox system was designed for root traces only.

**How to avoid:** In Phase 15, do NOT add checkboxes to subagent trace rows. The locked decision says checkboxes are only on root traces. If the `allChecked` getter causes visual issues (e.g., select-all checks too many items), that's a Phase 15 concern — add a `rootTraces` getter for checkbox count logic.

**Warning signs:** Select-all behavior counts subagent traces.

### Pitfall 4: Iteration rows still show level-2 tool call indentation

**What goes wrong:** The current `.level-2` class has `padding-left: 44px`. After removing the separate depth increment for tool calls (TREE-03 flat layout), if the class is still applied, tool calls appear deeper than iterations.

**Why it happens:** Old CSS class remains alongside new inline style.

**How to avoid:** Remove the `.level-0`, `.level-1`, `.level-2` CSS classes entirely and replace with inline style `padding-left` computed from node depth. The old static class system is replaced.

### Pitfall 5: Guide lines appear on root traces

**What goes wrong:** Guide lines should only appear for nested (depth > 0) traces, not root traces.

**Why it happens:** CSS rule applied too broadly.

**How to avoid:** Apply guide line CSS only when `node.depth > 0`. In the template, conditionally add `ai-tree-has-guide` class (or set `--ai-node-depth` custom property) only for `node.depth > 0`.

### Pitfall 6: selectedTraceId getter misses nested traces

**What goes wrong:** `get selectedTraceId()` is used for breadcrumb tinting (`.ancestor` CSS class). It finds the owning trace for a selected iteration or tool call by scanning `this.traces`. This still works correctly with subagent traces since they're stored in the same flat Map.

**Why it happens:** No pitfall here — the existing getter already handles this correctly by scanning all traces.

**Warning signs:** None expected.

---

## Code Examples

### Current Level CSS (to be removed)
```scss
// Current — to be replaced with inline style
.ai-tree-row.level-0 { padding-left: 4px; ... }
.ai-tree-row.level-1 { padding-left: 24px; }
.ai-tree-row.level-2 { padding-left: 44px; }
```

### New Depth-Based Inline Style (in template)
```xml
<!-- Trace row: base 4px + depth * 20px -->
t-attf-style="padding-left: {{ node.depth * 20 + 4 }}px"

<!-- Iteration row: base 24px + depth * 20px (flat with tool calls at same depth) -->
t-attf-style="padding-left: {{ node.depth * 20 + 24 }}px"

<!-- Tool call row: same as iteration row (TREE-03 flat layout) -->
t-attf-style="padding-left: {{ node.depth * 20 + 24 }}px"
```

### Guide Line SCSS Pattern
```scss
// Guide lines for nested rows (VS Code file-explorer style)
.ai-tree-row.ai-tree-has-guide {
    position: relative;

    &::before {
        content: '';
        position: absolute;
        left: calc(var(--ai-node-depth) * 20px - 6px);
        top: 0;
        bottom: 0;
        width: 1px;
        background-color: $o-gray-300;
        opacity: 0.5;
        pointer-events: none;
    }
}
```

### Iteration Row Label Format
```xml
<span class="ai-tree-label" t-on-click="() => this.selectItem(node.id, 'iteration')">
    <span class="ai-tree-iter-icon">&#x21BA;</span>  <!-- or other icon -->
    Iteration <t t-esc="node.iter.iteration_index"/>
    <span class="ai-tree-label-dim">
        &#xB7; <t t-esc="node.iter.toolCalls.size"/> call<t t-if="node.iter.toolCalls.size !== 1">s</t>
    </span>
    <t t-set="duration" t-value="this.getIterationDuration(node.trace, node.id)"/>
    <t t-if="duration">
        <span class="ai-tree-label-dim"> &#xB7; <t t-esc="duration"/></span>
    </t>
</span>
```

### sidebarNodes Getter Skeleton
```javascript
get sidebarNodes() {
    const nodes = [];
    // Root traces are those with no parent_trace_id
    const rootTraces = [...this.traces.values()]
        .filter(t => !t.parent_trace_id)
        .reverse(); // newest first (matches current behavior)

    for (const trace of rootTraces) {
        this._collectTraceNodes(trace, 0, nodes);
    }
    return nodes;
}

_collectTraceNodes(trace, depth, nodes) {
    nodes.push({ type: 'trace', id: trace.trace_id, depth, trace });
    if (!trace.expanded) return;

    const iterKeys = [...trace.iterations.keys()].reverse();
    for (const iterId of iterKeys) {
        const iter = trace.iterations.get(iterId);
        nodes.push({ type: 'iter', id: iterId, depth, iter, trace });

        if (!iter.expanded) continue;

        for (const [tcId, tc] of iter.toolCalls) {
            nodes.push({ type: 'tc', id: tcId, depth, tc, iter, trace });

            // Subagent traces spawned by this tool call
            const children = [...this.traces.values()].filter(
                t => t.parent_trace_id === trace.trace_id &&
                     t.parent_tool_call_id === tc.call_id
            );
            for (const child of children) {
                this._collectTraceNodes(child, depth + 1, nodes);
            }
        }
    }
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flat traces (no parent linkage) | Flat Map with `parent_trace_id` + `parent_tool_call_id` | Phase 13 (2026-02-23) | Enables child trace detection in `_collectTraceNodes` |
| 3-level static CSS classes | Depth-computed inline padding + single flat list | Phase 15 | Supports arbitrary nesting depth |
| Nested t-foreach in template | Single t-foreach over `sidebarNodes` | Phase 15 | Cleaner template, easier to maintain |

**Deprecated/outdated:**
- `.level-0`, `.level-1`, `.level-2` CSS classes: replaced by inline `padding-left` from node depth
- Three nested `t-foreach` loops in the template: replaced by single loop over `sidebarNodes`

---

## Open Questions

1. **Checkbox behavior for subagent traces**
   - What we know: `checkedTraceIds` and `allChecked`/`someChecked` assume all traces are root. If subagent traces are stored in `this.traces`, `this.traces.size` inflates.
   - What's unclear: Should `allChecked` count only root traces? Should subagent traces be checkable?
   - Recommendation: Locked decision says no checkboxes on subagent trace rows. Add a `get rootTracesCount()` getter that returns `[...this.traces.values()].filter(t => !t.parent_trace_id).length` and use it in `allChecked` / `someChecked` comparisons. This is a small change to existing getters.

2. **Iteration row collapse hides subagent traces (TREE-04 edge case)**
   - What we know: "Collapsing a parent **trace** hides all of its descendants." But what if an iteration is collapsed? Per the `_collectTraceNodes` implementation above, collapsing an iteration (`iter.expanded = false`) already prevents emission of tool call rows — and thus no child trace lookup happens for those tool calls. Child traces of an iteration's tool calls are effectively hidden when the iteration is collapsed.
   - What's unclear: Is this the intended behavior, or should child traces be visible even when their parent iteration is collapsed?
   - Recommendation: The current implementation (child traces hidden when parent iteration is collapsed) is correct and consistent with TREE-04. This doesn't need special handling.

3. **Order of child traces under a tool call**
   - What we know: Multiple subagents could technically be spawned by the same tool call (parallel agents). Currently this is out of scope per REQUIREMENTS.md (NEST-02 deferred).
   - What's unclear: If multiple child traces share the same `parent_tool_call_id`, in what order should they appear?
   - Recommendation: Use Map insertion order (arrival order) — same as root traces. No special handling needed for Phase 15.

---

## Validation Architecture

> Skipped — `workflow.nyquist_validation` is not set in `.planning/config.json` (key absent, treated as false).

---

## Sources

### Primary (HIGH confidence)
- Direct code reading of `/ai_debug/static/src/app/app.js` — current data model, reactive patterns, `_placeTrace()`, `_pendingChildren` buffer
- Direct code reading of `/ai_debug/static/src/app/app.xml` — current template structure, three-level t-foreach, CSS classes
- Direct code reading of `/ai_debug/static/src/app/app.scss` — current SCSS, `.level-0/1/2` classes, `.ai-json-nested` guide line pattern
- `.planning/STATE.md` — locked decisions: flat Map, `sidebarNodes` computed getter, no recursive OWL components, `useState({})` for agentColors
- `.planning/phases/15-sidebar-rendering/15-CONTEXT.md` — locked implementation decisions for this phase

### Secondary (MEDIUM confidence)
- OWL reactivity tracking behavior (getter reads during render are tracked): based on OWL's reactive proxy design and consistent with the existing `useRef`/`useState` patterns in the codebase

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries needed, all patterns are from existing codebase
- Architecture: HIGH — `sidebarNodes` getter pattern explicitly documented in STATE.md as the locked decision; code reading confirms OWL reactive patterns in use
- Pitfalls: HIGH — most pitfalls derived from direct reading of existing code and the locked constraint that OWL doesn't support template recursion

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable — no external dependencies)
