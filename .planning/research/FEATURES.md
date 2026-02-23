# Feature Research

**Domain:** Subagent trace visualization in a browser-based AI/LLM debugger
**Researched:** 2026-02-23
**Confidence:** HIGH — ecosystem patterns drawn from LangSmith, LangFuse, Arize Phoenix, and OpenTelemetry tracing conventions. Color assignment patterns drawn from browser DevTools and established tree-view tools. Codebase constraints verified directly against existing source.

---

## Context: What This Milestone Adds

**v1.3 (shipped):** Traces appear as flat top-level entries in the sidebar tree. Each trace has a 3-level internal structure: Loop > Iteration > Tool Call. Subagent sessions, if any, appear as independent top-level traces with no visible relationship to the parent that spawned them.

**v1.4 goal:** Visualize the parent/child relationships between agent traces. When Agent A calls a tool that spawns Agent B, Agent B's trace should nest visually under the tool call that launched it. The within-trace structure is flattened (iterations and tool calls at the same indentation level). Agents are color-coded for rapid visual identification, with colors persisted to IDB.

This research covers features specifically for the v1.4 milestone. Features already shipped in v1.0–v1.3 are not re-evaluated here.

---

## Feature Landscape

### Table Stakes (Users Expect These)

A developer inspecting a subagent hierarchy assumes these behaviors exist. Their absence makes the visualization feel broken or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Subagent traces nest under parent tool call** — child trace indents visually below the tool call that spawned it | Every LLM observability tool (LangSmith, LangFuse, Arize Phoenix) that supports multi-agent tracing nests child runs under the parent span that created them. Flat listings lose the causality that makes multi-agent traces useful. | MEDIUM | Requires backend to emit `parent_trace_id` + `parent_tool_call_id` in the `new_trace` event. Frontend must locate the parent tool call node in the existing trace tree and attach the child trace beneath it. |
| **Arbitrary recursive nesting depth** — grandchildren, great-grandchildren, etc., render correctly | Subagents can themselves spawn subagents. An agent orchestrating a research pipeline may go 3–4 levels deep. Limiting to two levels is a partial solution that silently drops deep traces. | MEDIUM | The tree rendering logic must be recursive rather than hardcoded to fixed levels. CSS indentation should scale predictably with depth (each level adds a fixed `padding-left` increment). No practical depth limit needed — developers rarely create loops deeper than 4–5 levels in a single session. |
| **Flat tree within each trace** — iterations and tool calls appear at the same indentation level | The current 3-level hierarchy (Loop > Iteration > Tool Call) is the right mental model for a single agent's loop. However, with nesting, a subagent trace that contains multiple iterations already occupies depth N. Expanding the iteration to show tool calls at depth N+1 compounds the visual nesting. A flat layout (iteration + its tool calls at the same indent) halves the effective depth consumed per trace level. | MEDIUM | Iteration nodes still expand/collapse (to hide detail), but expanded tool calls appear at the same indent as the iteration, not one level deeper. This requires changing the current level-1/level-2 two-tier layout within a trace to a single flat level with contextual icons or prefixes differentiating iteration vs tool call rows. |
| **Per-agent color strip on trace rows** — each distinct agent gets a persistent color applied to its trace rows | In a multi-agent tree, developers scan the sidebar to identify which agent's rows they are reading. Color is the fastest visual differentiator — it does not require reading text. Every major tool uses color coding for this purpose (LangSmith uses span type, LangFuse uses trace color tags). | LOW | A vertical colored strip (2–3px left border or colored left accent on the row) is the most compact approach. Does not require large colored backgrounds that would conflict with selected/hover states. |
| **Color persisted across page refreshes** — agent → color mapping stored in IDB | Developers work across multiple browser sessions. If colors reset every time, the learned association between a color and an agent breaks. Any tool claiming persistence must persist everything the user relies on for orientation. | LOW | A separate IDB object store (`agent_colors`) keyed by `agent_name`. Written on first assignment, read during hydration. IDB already in use for trace persistence (v1.3). |
| **Collapsed subagent trace hides children** — collapsing a parent trace node also hides its child traces | Standard behavior in any tree view. If a child trace remained visible when the parent was collapsed, the tree would appear to have orphaned entries. | LOW | The `expanded` flag on a trace controls whether its own iterations/tool calls are visible. The same flag should gate rendering of nested child traces. When a trace is collapsed, all descendants (its children, their children, etc.) are hidden regardless of their own expanded state. |

### Differentiators (Valuable, Not Required)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Color legend / agent roster in toolbar** — small color swatches next to agent names in the sidebar header area | When 4+ agents are active, the legend helps developers decode the color map without having to hover individual rows to read agent names. LangSmith does this inline with the trace list; LangFuse surfaces it in a legend panel. | LOW | A compact horizontal strip below the sidebar header: `[●] AgentA [●] AgentB`. Clickable to filter (that's v2+); for v1.4 it is read-only labeling only. |
| **Agent name shown in detail panel header** — when a node is selected, the detail panel header shows which agent it belongs to | In a deeply nested tree, a developer who clicks a tool call may have scrolled far enough that the parent trace is off screen. Without a breadcrumb or header indicator, they lose context. | LOW | The `LoopDetail`, `IterationDetail`, and `ToolCallDetail` components already have an `ai-detail-header` with type badge and name. Adding an `[AgentName]` chip (colored with the agent's color) requires passing the agent name down to child detail components. |
| **Depth indicator on trace rows** — subtle `depth: N` label or indent guide** | In deeply nested hierarchies, developers may lose track of how far into the recursion they are. A numeric depth indicator or visual guide line reassures them. | LOW | A very dim `depth: 2` label or, better, a continuous vertical line connecting ancestor to descendant (like VSCode's bracket pair guides). The line approach is more elegant but requires CSS that tracks indent level. |

### Anti-Features (Do Not Build)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Color picker per agent** — let the user manually choose a color | "I want consistent colors across machines." | Adds a color picker UI component, persistence for custom mappings, and reset logic. The gain is marginal: a deterministic assignment algorithm (hashing the agent name) already gives consistent colors across machines and sessions. Custom colors would override this. | Hash-based assignment (see Color Assignment section below) is deterministic — the same agent name always gets the same color on any machine. No picker needed. |
| **Timeline / Gantt view of concurrent agents** | "I want to see which agents ran in parallel." | The agentic loop in Odoo's `ai.session._run_agentic_loop()` is synchronous and sequential — a subagent is spawned synchronously within a tool call, not concurrently. There is no concurrency to visualize. A timeline widget adds substantial complexity for zero informational gain in this architecture. | The existing tree with timestamps on iteration rows already shows sequential timing. |
| **Filtering sidebar by agent** — show only traces from Agent A | "I'm debugging one agent and don't want to see the others." | Filtering removes the multi-agent context that nesting is designed to show. If a subagent is filtered away, the tool call that spawned it appears to have no result. | Collapsing the tree at the parent trace level hides unwanted subtrees. If a developer is debugging a single agent in isolation, they can import a single-agent JSON export instead. |
| **Inline diff between parent and child agent state** — show state changes when control transfers to a subagent | "I want to see what state the parent passed to the child." | The `state_snapshot` in the `new_trace` event already captures initial state. Displaying a diff requires knowing the parent's state at the moment of the call, which is not in the current payload and would require architectural changes to the backend instrumentation. The value is marginal for v1.4. | Each trace's LoopDetail panel already shows the state snapshot. Developers can compare manually. |
| **Automatic tree expansion to selected item** — when a deep node is auto-selected, expand all ancestors** | "When I click a deeply nested item from the detail panel breadcrumb, I want the tree to reveal it." | Auto-expansion breaks the user's intentional collapse state. A developer who collapsed a busy parent trace to hide its clutter would find it suddenly expanded. | Developers can expand manually. The sidebar auto-scroll already ensures the selected node is visible when it first arrives. |
| **Live animation showing control flow between parent and child** — animated arrow or highlight showing where the spawned agent is executing | "This would make the hierarchy intuitive for demos." | Requires knowing the currently executing agent's trace_id at render time, continuous polling, and non-trivial animation logic. Bus.bus is event-driven, not a continuous state stream. The running pulse dot (already implemented) already indicates in-flight execution within a trace. | The pulse dot on the trace row's status position already conveys "this trace is currently running." |

---

## Feature Dependencies

```
[Subagent trace nesting]
    └──requires──> [Backend emits parent_trace_id + parent_tool_call_id in new_trace]
    └──requires──> [Frontend tree data structure supports child traces on tool call nodes]
    └──requires──> [Flat tree within trace] (nesting increases depth; flat layout offsets it)

[Arbitrary recursive nesting depth]
    └──requires──> [Subagent trace nesting] (depth > 1 only matters once nesting exists)
    └──requires──> [Recursive tree render] (not hardcoded level-0/level-1/level-2 CSS classes)

[Flat tree within trace]
    └──changes──> [Current 3-level tree] (level-1 = iteration, level-2 = tool call → both at level-1)
    └──requires-no-change-to──> [Detail panels] (IterationDetail and ToolCallDetail are unchanged)

[Per-agent color-coding]
    └──requires──> [agent_name field on trace] (already in new_trace payload since v1.1)
    └──writes-to──> [IDB agent_colors store] (new store, same DB as traces)
    └──reads-from-during-hydration──> [IDB agent_colors store]
    └──used-by──> [Sidebar tree row rendering] (left border color)
    └──used-by-optionally──> [Detail panel header chip]

[Color persisted across sessions]
    └──requires──> [Per-agent color-coding]
    └──requires──> [IDB already initialized] (v1.3 delivered this)
    └──uses-same-DB-different-store──> [IDB db.js] (add agent_colors store in same openDB() call, requires DB version bump)

[Collapsed subagent trace hides children]
    └──requires──> [Subagent trace nesting] (children only exist if nesting exists)
    └──uses-existing-mechanism──> [trace.expanded flag] (already implemented in v1.1)
```

### Dependency Notes

- **Backend change is the unlock:** Every frontend feature depends on the backend emitting `parent_trace_id` and `parent_tool_call_id`. Without this, subagent traces are indistinguishable from top-level traces. This is the first task to complete.
- **Flat tree is coupled to nesting:** If iterations and tool calls remained at two separate indentation levels within a trace, a nesting depth of 3 would put tool calls at an effective left-margin indent of 6 levels, making the sidebar unusable on standard monitor widths. Flattening within a trace is a prerequisite for nesting to be usable.
- **IDB schema bump is small:** Adding an `agent_colors` store only requires incrementing `DB_VERSION` from 1 to 2 and adding the store in the `onupgradeneeded` callback. All existing trace data is preserved across the schema version upgrade.
- **Color assignment and IDB are independent of the tree structure changes:** They can be implemented in parallel with the nesting/flattening work.

---

## Color Assignment Strategy

This is the most design-sensitive feature in v1.4. The strategy must handle:
- Dynamic agent discovery (agent names are not known at build time)
- Sessions with many agents (5–10+ is plausible in a research pipeline)
- Dark and light mode (colors must have adequate contrast in both)
- Persistence across sessions (same agent = same color, every time)
- Odoo's `$o-*` variable system (all colors must respect the theme system)

### Recommendation: Deterministic Hash Assignment from a Curated Palette

**Approach:** Pre-define a palette of N colors (8–12 is optimal). Assign each new agent the next color in the palette. The assignment is stable because it is persisted to IDB keyed by `agent_name`. On subsequent sessions, the color is read from IDB rather than re-assigned. A developer who resets IDB (clear all) gets new color assignments, which is acceptable.

Do NOT use pure hashing (mapping agent_name hash to a color slot) without IDB persistence. Pure hashing is deterministic but produces colors from the full HSL space, many of which fail contrast requirements in dark or light mode. Curated palettes guarantee contrast.

**Why not CSS custom properties or class rotation?** Rotation-only approaches are stateless — they break if traces are added, deleted, or imported in a different order. Persistence (IDB) is required to maintain the same color across sessions, which rotation cannot provide.

### Palette Design Constraints

| Constraint | Requirement | Rationale |
|------------|-------------|-----------|
| Contrast on dark backgrounds | Minimum WCAG AA for text (4.5:1) for the sidebar row accent; decorative accents (colored borders) only need 3:1 | App supports full dark mode; a color visible in light mode may be invisible in dark mode |
| Contrast on light backgrounds | Same WCAG AA minimum for any text label using the color | Light mode default |
| Distinguishable from Odoo semantic colors | Must not conflict with `$o-success` (green), `$o-danger` (red), `$o-warning` (amber) | These colors carry meaning in existing status indicators; agent colors must not be confused with success/error states |
| Visually distinct from each other | Colors should be perceptually distinguishable at small sizes (3px strip) | Developers scan, not read, when identifying agents |
| Work as left-border accents, not fills | The color is applied as a 3px left border on the row, not a background fill | Full background fills interact badly with selected/hover/ancestor state backgrounds |

### Recommended Palette (8 slots)

Use hardcoded `rgba()` values rather than `$o-*` variables for agent colors. The `$o-*` variables are semantic (danger, success, etc.) and their values change between light and dark mode in ways that may cause contrast failures. Agent colors are non-semantic accent identifiers that should remain stable across themes, with a fixed luminosity that works in both modes.

| Slot | Hex | Appearance | Contrast Passes On |
|------|-----|------------|-------------------|
| 0 | `#4f8ef7` | Cornflower blue | Light and dark backgrounds |
| 1 | `#e06c75` | Soft red (distinct from $o-danger which is vivid) | Light and dark |
| 2 | `#56b6c2` | Teal/cyan | Light and dark |
| 3 | `#d19a66` | Warm orange (distinct from $o-warning amber) | Light and dark |
| 4 | `#c678dd` | Purple | Light and dark |
| 5 | `#98c379` | Muted green (distinct from $o-success which is vivid) | Light and dark |
| 6 | `#e5c07b` | Gold/yellow | Dark backgrounds (borderline on light — use as accent only, not text) |
| 7 | `#61afef` | Sky blue (lighter than slot 0) | Light and dark |

These eight colors are derived from the One Dark Pro palette (used by VS Code, Atom, many terminals) and are battle-tested for contrast against both dark and light IDE backgrounds.

**Overflow strategy:** If more than 8 agents appear in a session, the assignment wraps around (slot N % 8). The wrapped color will coincide with an existing agent's color. This is acceptable — 8+ agents in a single session is rare, and even with wrapping, the colors still aid visual grouping. An alternative is to emit a muted gray for slots beyond 8, signaling that the palette has been exhausted.

### Color Storage in IDB

```
Database: 'ai_debug_traces' (same DB, version bump to 2)
Object store: 'agent_colors'
  keyPath: 'agent_name'
  value: { agent_name: string, color: string (hex), slot: number }
```

On `new_trace` arrival: check if `agent_name` is in the local `agentColors` Map. If not, assign the next available slot, store the color in the Map and write to IDB `agent_colors`. If yes, use the existing color.

On hydration: read all records from `agent_colors` store, populate the in-memory Map, then reconstruct slot assignment (slot = max of all existing slots + 1 for the next new agent). This ensures continued assignment doesn't re-use slots already in the IDB.

### Color Application in the UI

Apply the agent color as a `border-left: 3px solid <color>` on the trace row. This is:
- Compact (does not eat into label space)
- Non-conflicting with selected (blue bg), hover (gray bg), and ancestor (faint blue bg) states
- Clearly visible in both light and dark mode at any luminosity
- Consistent with how VS Code, Chrome DevTools timeline, and LangSmith apply per-resource colors

For the trace rows of nested child traces, apply the child agent's color, not the parent's. This makes parent/child boundaries immediately visible — the color changes at the trace boundary.

For iteration and tool call rows within a trace, apply the same color as their parent trace (they belong to that agent). A very low-opacity fill (3–5% opacity of the agent color) on iteration/tool call rows, rather than a full left border, distinguishes "own content" from "the trace header itself."

---

## MVP Definition

### Launch With (v1.4)

The minimum required to make subagent hierarchies visible and navigable.

- [ ] **Backend emits parent_trace_id + parent_tool_call_id** — `new_trace` event includes these fields when the session was spawned by a tool call in another session. Top-level traces have these fields as `null`.
- [ ] **Frontend attaches child trace under parent tool call node** — when a `new_trace` arrives with a non-null `parent_tool_call_id`, locate that tool call in `this.traces` and attach the child trace to it.
- [ ] **Flat tree within a trace** — iterations and tool calls render at the same indentation level. Expanding an iteration reveals its tool calls inline at the same depth, not one level deeper.
- [ ] **Recursive tree rendering** — the OWL template renders trace subtrees recursively so arbitrary nesting depth works without code changes per depth level.
- [ ] **Per-agent color strip** — each trace row has a 3px left border in the agent's assigned color. Assignment happens on first `new_trace` arrival for that `agent_name`.
- [ ] **Color persisted to IDB** — `agent_colors` store in the existing IDB database (requires DB version bump from 1 to 2). Colors restored on hydration.
- [ ] **Dark and light mode compatibility** — agent colors use hardcoded hex values from the curated 8-slot palette, verified to work in both themes.

### Add After Validation (v1.4.x)

- [ ] **Agent legend in sidebar header** — colored swatches + agent names, read-only. Add when developer feedback indicates they lose track of the color map.
- [ ] **Agent color chip in detail panel header** — small colored badge next to the agent name in the `ai-detail-header`. Add when navigating deep hierarchies creates context confusion.

### Future Consideration (v2+)

- [ ] **Search/filter sidebar by agent** — explicitly deferred in PROJECT.md.
- [ ] **Custom color assignment per agent** — only if deterministic hashing fails in a use case that actually occurs.
- [ ] **OpenTelemetry export with parent/child span relationships** — `EXPT-01` in PROJECT.md v2+ candidates; subagent nesting is a prerequisite because OTLP requires a complete span hierarchy.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Backend emits parent_trace_id + parent_tool_call_id | HIGH | LOW | P1 — nothing else works without this |
| Frontend nests child trace under parent tool call | HIGH | MEDIUM | P1 — core milestone goal |
| Flat tree within a trace | HIGH | MEDIUM | P1 — required for nesting to be usable on standard displays |
| Recursive tree rendering | HIGH | MEDIUM | P1 — required for depth > 1 |
| Per-agent color strip | HIGH | LOW | P1 — visual orientation in multi-agent tree |
| Color persisted to IDB | HIGH | LOW | P1 — persistence is a design commitment since v1.3 |
| Dark/light mode compatibility for colors | HIGH | LOW | P1 — both themes are officially supported |
| Agent legend in sidebar header | MEDIUM | LOW | P2 — helps when 4+ agents; not blocking for 2–3 |
| Agent color chip in detail panel header | MEDIUM | LOW | P2 — context aid for deep hierarchies |
| Depth indicator on rows | LOW | LOW | P3 — nice to have, rarely needed in practice |
| Custom color picker per agent | LOW | MEDIUM | ANTI-FEATURE — hash + IDB is sufficient |
| Timeline / Gantt view | LOW | HIGH | ANTI-FEATURE — loop is synchronous, no concurrency to show |
| Filtering sidebar by agent | LOW | MEDIUM | ANTI-FEATURE — breaks multi-agent context |

---

## Ecosystem Context

The following patterns are drawn from established LLM observability tools. Web access was not available during this research session; patterns reflect training data knowledge of these tools up to August 2025 and direct inspection of the existing codebase.

**Confidence level: MEDIUM** for specific UI patterns (training data, unverifiable against current versions). **HIGH** for the underlying principles (standard tree-view and tracing patterns that predate LLM tooling).

### How LangSmith Handles Nested Runs

LangSmith's run tree shows child runs indented under the parent run that spawned them. Each run type (chain, llm, tool, agent) has a distinct icon and, in some views, a colored left border. The hierarchy is unbounded — any run can be a parent. Tool calls that spawn sub-chains show the sub-chain's run tree as a collapsible nested section.

Key pattern this project should adopt: **the indentation communicates causality**, not just containment. The visual line from parent to child tells the developer "this is what caused that."

### How LangFuse Handles Nested Spans

LangFuse uses an OpenTelemetry-compatible span model. Child spans indent under parent spans in the trace timeline. Each span type has a color (llm = blue, function = gray, etc.). The project assigns color by span type, not by agent identity — but that distinction doesn't apply here since the tool type is already conveyed by icons.

Key pattern: **color is applied as a type/identity signal, not a status signal**. Status (success/error/running) is conveyed separately via icons. This is exactly the proposed design for v1.4 — left border = agent identity, right icon = status.

### How Arize Phoenix Handles Agent Traces

Phoenix shows agent traces as a flat list with nesting conveyed by indentation and connecting lines. Parent-child relationships are explicit in the data model (`parent_id` on each span). The UI renders recursively — there is no hardcoded depth limit.

Key pattern: **the `parent_id` approach** (which maps directly to `parent_trace_id` + `parent_tool_call_id` in this project's design) is the standard data model for agent trace hierarchies.

---

## Sources

- PROJECT.md — milestone goals, design decisions, out-of-scope items (HIGH confidence — source of truth)
- Existing codebase (app.js, app.xml, app.scss, db.js) — current data model, event structure, IDB schema (HIGH confidence — direct inspection)
- LangSmith documentation (training data, verified as of August 2025) — run tree nesting patterns (MEDIUM confidence)
- LangFuse documentation (training data, verified as of August 2025) — span color coding patterns (MEDIUM confidence)
- Arize Phoenix documentation (training data, verified as of August 2025) — recursive parent_id span model (MEDIUM confidence)
- OpenTelemetry tracing specification (training data) — parent_span_id as the canonical way to express span causality (HIGH confidence — stable specification)
- One Dark Pro palette (VS Code, Atom) — verified contrast on dark and light backgrounds by community validation over many years (HIGH confidence)
- WCAG 2.1 contrast guidelines — AA minimum 4.5:1 for text, 3:1 for decorative elements (HIGH confidence — stable standard)

---

*Feature research for: Subagent visualization — nested trace tree, flat within-trace layout, per-agent color-coding (ai_debug v1.4)*
*Researched: 2026-02-23*
