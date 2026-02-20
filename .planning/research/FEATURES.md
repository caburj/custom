# Feature Research

**Domain:** Live agentic loop tracer — sidebar tree / master-detail layout (v1.1)
**Researched:** 2026-02-20
**Confidence:** MEDIUM-HIGH (ecosystem patterns from LangSmith, Langfuse, Jaeger, VS Code are well-documented; Odoo OWL translation is original reasoning from verified source code)

---

## Context: What v1.0 Already Provides

These features exist and must NOT be re-implemented — they are dependencies, not deliverables.

- Live iteration streaming via bus.bus (iterations arrive in real time)
- Tool call tracking with args/results (lazy-loaded on expand)
- System prompt, RAG context, tools definition display (left panel)
- JsonTree recursive renderer with Ctrl+click recursive fold
- StateDiff viewer (changed/added/removed keys, unchanged collapsible)
- Two-column layout: left trace context + right timeline
- Connection status indicator
- Listen mode (auto-attaches to next new trace)

The v1.1 deliverable replaces the timeline + manual expand model with a sidebar tree + detail panel model. The existing OWL components (JsonTree, StateDiff) are reused in the new detail panel.

---

## Reference Ecosystem

**Patterns studied:**
- **VS Code debugger sidebar** — multi-session call stack as a tree; selecting a frame in the left sidebar updates variables/watch panels on the right. Multiple debug sessions appear as top-level tree roots.
- **Jaeger trace UI** — traces collapsed by default; clicking a span expands detail inline OR opens a detail panel; tree indentation communicates parent/child span relationships. Waterfall timing is the primary visual.
- **Langfuse new trace view (2025)** — tree/timeline toggle; tree reconstructed from `parent_observation_id`; clicking a span shows input/output in a right-side detail pane. Search within the tree by type, ID, or name.
- **LangSmith run tree** — collapsible tree nodes per agent step; status badges (running/success/error) inline with each node; clicking opens detail with input/output, metadata, latency.
- **Browser DevTools (Network panel)** — left list is the "master"; clicking a request reveals headers/preview/response/timing tabs in the right detail area. Arrow-key navigation moves selection up/down.

**Key pattern synthesis:** The canonical live-tracer UX is a persistent left sidebar tree (master) and a right detail panel (detail). Selection in the sidebar drives content in the detail panel. The tree nodes carry status badges inline (spinner for running, checkmark for done, X for error). Multiple concurrent runs become top-level nodes in the same sidebar.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features a developer opening a live tracer sidebar expects without being told they exist. Missing any of these makes the tool feel broken or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Sidebar tree with 3-level hierarchy** — Loop > Iteration > Tool Call | Every live tracer (Jaeger, LangSmith, Langfuse, VS Code) organizes data as a tree. A flat timeline is a v1.0 debugging aid; the tree is how inspectors work. | MEDIUM | OWL component: `TracerSidebar`. Each level: loop node > iteration nodes > tool call leaf nodes. All 3 levels visible simultaneously via collapse/expand. |
| **Click-to-select drives detail panel** | The entire point of a master/detail layout. Clicking a node in the sidebar must immediately replace the detail panel content with that node's data. | LOW | Selection state: `{ type: 'loop' \| 'iteration' \| 'tool_call', id }`. Detail panel is a single OWL component that switches content based on type. |
| **Status badge inline with each tree node** | VS Code shows a spinner next to the active stack frame. LangSmith puts running/success/error badges on each node. Developers need to see "what's happening right now" without opening the detail panel. | LOW | CSS-only: spinner icon for running, checkmark for done, X for error. Loop node shows running state while any iteration is in flight. |
| **Auto-select the latest running node** | When a new iteration or tool call arrives over bus.bus, the sidebar selection should auto-advance to it — unless the user has manually selected a different node. Equivalent to how a debugger's call stack auto-selects the current frame. | MEDIUM | "User has manually selected" flag. Clear flag when a new loop starts. Auto-select only the newest node from bus.bus events. |
| **Loop node as first-class citizen** — labeled by agent name | The loop (trace) must be a visible, selectable root node in the tree — not just a header. Selecting it shows the loop-level context (system prompt, RAG, tools). This is equivalent to Jaeger's root span. | LOW | Loop node: `[agent_name] — [model] — [status]`. Clicking it shows the left-panel content from v1.0 (system prompt, RAG, tools) in the detail panel. |
| **Multiple loops as top-level tree roots** | When two agentic loops run in the same session (sequentially or concurrently), both appear as top-level nodes in the sidebar. VS Code debugger shows multiple debug sessions as siblings in the call stack tree. | MEDIUM | State: `loops[]`, each with nested iterations. Sidebar renders one tree root per loop. No tabs — all roots are always visible in the sidebar. |
| **Ephemeral session-scoped data** — refresh clears all | The v1.1 tracer has no database. All state lives in frontend memory. Refresh = empty sidebar. Users of developer tools understand this (DevTools network panel, VS Code debug session). Must be explicit: no "save trace" in v1.1. | LOW | Frontend-only state. No ORM reads for trace data (full payloads come over bus.bus). |
| **Full payloads over bus.bus** — no lazy ORM reads | The v1.0 model lazy-loaded detail via `orm.read()` on expand. v1.1 has no DB models. Every bus.bus event must carry the full payload needed to populate the detail panel. | MEDIUM | Bus payload schema design: iteration events carry `messages_sent`, `raw_response`, `state_before`, `state_after`. Tool call events carry `args`, `result`, confirmation fields. This is a backend instrumentation task, not just frontend. |
| **Connection status indicator** | Already exists in v1.0. Must be retained. Developers watching a live trace must know if the WebSocket is connected or reconnecting. | LOW | Carry forward from v1.0 debug_panel.js `_syncConnectionStatus`. |

### Differentiators (Competitive Advantage)

Features that make this tracer better than a generic span-tree inspector, specifically because it is Odoo-native and domain-specific.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Agent name as loop label** — reads from `ai.agent` record | LangSmith/Langfuse show trace IDs or operation names. The Odoo AI module has named agents (the `ai.agent` model). Labeling each loop root with the agent name ("Sales Assistant", "HR Bot") is instantly meaningful to developers. Generic tracers cannot do this. | LOW | Bus payload includes `agent_name` from `ai.agent.name` at loop start. Displayed as the primary label on the loop tree node. |
| **Subagent-ready tree design** — parent/child loop relationship anticipated | The Odoo `ai` module is expected to support subagents (a nested agentic loop spawned inside a parent loop). The tree data model should carry a `parent_loop_id` field from day one, even though subagent nesting is not yet implemented upstream. This avoids a data model migration later. | LOW | Data model: `loops[].parent_loop_id`. When populated, the child loop node renders as a child of the parent in the sidebar tree (4-level hierarchy: parent loop > child loop > iteration > tool call). In v1.1 this field is always null. |
| **Iteration-level timing waterfall** — duration_ms as a visual bar in the sidebar node | LangSmith and Jaeger show timing as a waterfall bar next to each node. Even a simple text duration (`1.2s`) next to each iteration node gives immediate "which call was slow" signal without opening the detail panel. | LOW | Format: `formatDuration(ms)` already exists in debug_panel.js. Display inline on each iteration tree node. |
| **Confirmation pause state** — explicit "Paused: waiting for user" node status | Odoo's AI module has a unique two-phase confirmation pattern. When a tool triggers a confirmation pause, the current iteration's status must clearly show "Paused" — not "Running" and not "Done". No external tracer has this concept. | LOW | Bus payload `state = 'paused'` on the loop update event. Loop node shows a "paused" badge (distinct from running/done/error). |
| **Detail panel tabs match node type** — different tab sets for loop vs iteration vs tool call | Selecting a loop shows: System Prompt / RAG Context / Tools Definition tabs. Selecting an iteration shows: Messages Sent / Raw Response / State Diff tabs. Selecting a tool call shows: Args / Result / State Diff tabs. This is type-aware context — better than a generic key/value viewer. | MEDIUM | Single `DetailPanel` OWL component with `t-if` branches on selected node type. Reuses existing JsonTree and StateDiff components for content rendering. |
| **Listen mode preserved** — auto-attaches to next loop | v1.0's "listen" mode (no trace_id in URL, auto-attaches to the next `ai_debug/new_trace` bus event) must survive the v1.1 redesign. Developers leave the tracer open in a tab and watch loops arrive automatically. | LOW | Carry forward from v1.0 `_onNewTrace` handler. In v1.1: add the new loop as a tree root and auto-select it. |
| **Keyboard navigation in sidebar tree** — arrow keys to move selection | W3C ARIA tree pattern: Down Arrow moves to next visible node, Up Arrow moves to previous, Right Arrow expands a collapsed node, Left Arrow collapses or moves to parent. This matches DevTools and VS Code behavior developers already know. | MEDIUM | OWL `t-on-keydown` on sidebar container. ARIA `role="tree"`, `role="treeitem"` on nodes. Adds accessibility without changing visual design. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Tabs for multiple loops** — a tab bar where each loop is a tab | Feels familiar (Chrome tabs, VS Code editor tabs). Easy to implement. | When two loops run simultaneously or in rapid succession, a tab bar means only one loop is visible at a time. The sidebar tree shows all loops simultaneously, giving a more complete picture. Tabs also break keyboard navigation and don't scale past ~5 loops in a session. | Top-level tree roots in the sidebar. All loops visible simultaneously. Most recent is auto-selected. |
| **Persistent traces across refreshes** — localStorage or IndexedDB cache | Developers lose traces on refresh and ask for persistence. | v1.1 is explicitly ephemeral. Persistence via localStorage creates stale data problems (events from a previous session polluting a new one), schema migration headaches, and privacy concerns (sensitive LLM payloads cached in browser storage). | Database persistence is a v2 feature. For now: document that traces are session-scoped. A clear "Session" label in the sidebar header sets the expectation. |
| **Search / filter within the sidebar tree** | Large loops with 20+ iterations and 50+ tool calls are hard to scan. | Adds significant UI complexity (filter input, match highlighting, collapsed-but-matching state) for a developer tool where the tree depth is bounded (3–4 levels, typically 1–20 iterations). Adding search now would require rebuilding the tree state model to track "match" status. | Defer to v1.x. Sorting (latest first vs chronological) is a simpler first step. Ctrl+F browser search works for text already visible in the sidebar. |
| **Live token streaming** — show LLM response tokens as they arrive | "I want to see the response being generated." | The Odoo AI module's `generate_response` endpoint delivers complete chunks, not per-token SSE. There is no token-level hook without modifying the provider layer — explicitly out of scope. Any attempt to fake streaming (polling for partial response) would require DB persistence. | Show the raw response in the detail panel as soon as the iteration completes. Display duration_ms so developers know how long the LLM took. |
| **Editable trace replay** — click a node and re-run with modified messages | LangSmith has this, users will ask. | Requires constructing and firing a new `ai.session` run from within the frontend — which requires knowing the session context, record ID, channel ID, and other runtime state that the tracer does not control. The Odoo session lifecycle (TransientModel tied to a chat channel) makes safe replay non-trivial. | Defer to v2+. For now: add a "Copy JSON" button to the detail panel for messages_sent. Developers can paste into their own test script. |
| **Graph visualization** — Langfuse-style DAG view of spans | Langfuse added a graph view for LangGraph traces. Looks impressive. | The Odoo agentic loop is strictly sequential (loop > iteration > tool call) — not a DAG. Graph visualization adds visual complexity with no benefit for a linear execution model. When subagents arrive (parent/child loops), the tree already expresses the hierarchy correctly. | The sidebar tree IS the graph for this domain. Invest in making the tree readable (badges, timing, clear indentation) rather than a DAG renderer. |

---

## Feature Dependencies

```
[Sidebar tree component]
    └──requires──> [Full bus.bus payloads] (no ORM reads means all data must arrive in events)
    └──requires──> [Loop node as tree root] (tree cannot render without a root)
    └──enhances-with──> [Status badges]
    └──enhances-with──> [Timing waterfall display]

[Detail panel component]
    └──requires──> [Click-to-select state] (nothing to show without a selection)
    └──reuses──> [JsonTree] (existing component — messages, args, result, raw response)
    └──reuses──> [StateDiff] (existing component — state_before / state_after)
    └──branches-on──> [Node type: loop | iteration | tool_call]

[Auto-select latest node]
    └──requires──> [Click-to-select state] (needs "user manually selected" flag)
    └──listens-to──> [bus.bus iteration events]
    └──listens-to──> [bus.bus tool_call events]

[Agent name label]
    └──requires──> [agent_name in new_trace bus payload] (backend must include it)

[Multiple loops as tree roots]
    └──requires──> [Loop node as tree root]
    └──requires-change-to──> [State shape: loops[] array instead of single trace]

[Subagent-ready data design]
    └──requires──> [parent_loop_id field in loop state]
    └──does-not-require──> [Actual subagent nesting] (field is null in v1.1)

[Confirmation pause state]
    └──requires──> [Status badge system]
    └──requires──> [loop state update bus event carrying state='paused']

[Keyboard navigation]
    └──requires──> [Sidebar tree component]
    └──requires──> [Click-to-select state] (arrow keys move selection, same state)
```

### Dependency Notes

- **Full bus.bus payloads are the foundational backend change.** The v1.0 instrumentation saved data to DB and let the frontend lazy-load via ORM. v1.1 removes the DB, so the backend must embed all detail data in each bus.bus event payload. This is a backend instrumentation task that must land before the detail panel can be built.
- **State shape must change from single-trace to loops array.** v1.0 had `state.traceId` + `state.iterations[]`. v1.1 needs `state.loops[]`, where each loop has its own `iterations[]`. This is the central structural change; all other features compose on top of it.
- **JsonTree and StateDiff are reused unchanged.** These existing components slot directly into the new detail panel. No modifications needed.
- **Listen mode logic is preserved but must feed the new loops[] state.** When `_onNewTrace` fires, it appends to `state.loops[]` rather than replacing a single trace.

---

## MVP Definition

### Launch With (v1.1)

Minimum viable for replacing the v1.0 timeline model. The tracer is usable the moment a developer can navigate the tree and see the right detail for whatever they clicked.

- [ ] **Full bus.bus payloads** (backend) — iteration events carry messages_sent, raw_response, state_before, state_after; tool call events carry args, result, confirmation fields
- [ ] **Loops-array state model** — `state.loops[]` replaces `state.traceId` + single-trace state; each loop has nested iterations and tool calls
- [ ] **Sidebar tree — 3-level hierarchy** — Loop > Iteration > Tool Call; expand/collapse per node; status badge (running/done/error/paused) inline
- [ ] **Click-to-select drives detail panel** — selecting any node replaces the detail panel; selection is a single `{ type, id }` object
- [ ] **Detail panel with type-aware tabs** — Loop: System Prompt / RAG / Tools; Iteration: Messages / Response / State Diff; Tool Call: Args / Result / State Diff; reuses JsonTree and StateDiff
- [ ] **Agent name as loop label** — agent_name in new_trace bus payload; rendered as primary node label
- [ ] **Auto-select latest running node** — new bus events auto-advance selection unless user has manually selected
- [ ] **Multiple loops as top-level sidebar roots** — sequential and concurrent loops both appear as siblings in the sidebar
- [ ] **subagent-ready: parent_loop_id in loop data model** — field exists and is null in v1.1; tree renders parent/child when populated

### Add After Validation (v1.1.x)

- [ ] **Keyboard navigation** — arrow keys move sidebar selection; ARIA tree roles; add once base tree is working and selection is stable
- [ ] **Confirmation pause badge** — 'paused' status distinct from 'running'; add once pause/resume events are confirmed to fire correctly in the instrumentation
- [ ] **Timing display on iteration nodes** — formatDuration inline; add once tree is rendered correctly; trivial once tree node template exists

### Future Consideration (v2+)

- [ ] **Database persistence of traces** — session-scoped is the explicit v1.1 design; persistence is a separate milestone
- [ ] **Search / filter within sidebar** — bounded tree depth makes this low-priority; add only if developers report navigation pain with 50+ iterations
- [ ] **Trace export** — OTLP / JSON export of a captured loop; deferred from v1.1 per PROJECT.md
- [ ] **Replay / re-run with modified messages** — requires session lifecycle integration; deferred to v2+

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Full bus.bus payloads (backend) | HIGH | MEDIUM | P1 — blocks everything else |
| Loops-array state model | HIGH | MEDIUM | P1 — structural foundation |
| Sidebar tree (3-level) | HIGH | MEDIUM | P1 — the core UX |
| Click-to-select + detail panel | HIGH | LOW | P1 — makes tree useful |
| Detail panel type-aware tabs | HIGH | LOW | P1 — immediate value |
| Agent name as loop label | HIGH | LOW | P1 — trivial with payload field |
| Auto-select latest running node | MEDIUM | LOW | P1 — key for live-watching |
| Multiple loops as tree roots | MEDIUM | LOW | P1 — correctness for concurrent runs |
| Subagent-ready parent_loop_id | LOW | LOW | P1 — do it now, costs nothing |
| Timing display on iteration nodes | MEDIUM | LOW | P2 — easy, not blocking |
| Keyboard navigation | MEDIUM | MEDIUM | P2 — nice polish, not MVP |
| Confirmation pause badge | MEDIUM | LOW | P2 — needs confirmed bus events |
| DB persistence | HIGH | HIGH | P3 (v2+) |
| Search/filter sidebar | LOW | HIGH | P3 |
| Trace export | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for v1.1 launch
- P2: Should have, add when core is stable
- P3: Future milestone

---

## Competitor / Reference Analysis

| Feature | VS Code Debugger | Jaeger UI | LangSmith | Langfuse | Odoo AI Tracer v1.1 |
|---------|-----------------|-----------|-----------|----------|---------------------|
| Sidebar tree | Yes — call stack | Yes — span waterfall tree | Yes — run tree | Yes — observation tree | Yes — loop/iteration/tool call |
| Multi-session/multi-trace roots | Yes — top-level siblings | Yes — search + open multiple | Yes — trace list | Yes — trace list | Yes — loops[] array as siblings |
| Click-to-select + detail panel | Yes | Yes | Yes | Yes | Yes |
| Status badge inline | Yes (spinner/arrow) | Yes (error highlighting) | Yes (running/success/error) | Yes | Yes |
| Agent/service name label | Session name | Service name | Run name | Trace name | ai.agent.name — specific Odoo field |
| Auto-select current frame | Yes | No | Partial | No | Yes — newest bus event auto-selects |
| Keyboard navigation | Yes | Partial | No | No | v1.1.x (after base) |
| Domain-specific tabs | No (generic) | Logs/Tags/Process | Input/Output/Metadata | Input/Output/Metadata | System Prompt/RAG/Tools; Messages/Response/StateDiff |
| Confirmation pause state | No | No | No | No | Yes — Odoo-specific pattern |
| Session-scoped ephemeral | Yes (debug session) | No (persisted) | No (persisted) | No (persisted) | Yes — explicit v1.1 design |
| Subagent / nested loop | Nested call stacks | Nested spans | Yes | Yes | Anticipated (parent_loop_id) |

---

## Sources

- [Debugging Deep Agents with LangSmith — blog.langchain.com](https://blog.langchain.com/debugging-deep-agents-with-langsmith/) — MEDIUM confidence (official blog)
- [New Trace View — Langfuse changelog, 2025-03-19](https://langfuse.com/changelog/2025-03-19-new-trace-view) — MEDIUM confidence (official changelog)
- [Langfuse Tracing Data Model — langfuse.com](https://langfuse.com/docs/observability/data-model) — HIGH confidence (official OSS docs)
- [VS Code Debugger Documentation — code.visualstudio.com](https://code.visualstudio.com/docs/debugtest/debugging) — HIGH confidence (official docs)
- [VS Code multi-session call stack — github.com/microsoft/vscode issue #194881](https://github.com/microsoft/vscode/issues/194881) — HIGH confidence (official issue tracker)
- [W3C ARIA TreeView Pattern — w3.org](https://www.w3.org/WAI/ARIA/apg/patterns/treeview/) — HIGH confidence (W3C standard)
- [Jaeger UI features — jaegertracing.io](https://www.jaegertracing.io/) — MEDIUM confidence (official docs, UI inferred from described behavior)
- [PatternFly Primary-detail pattern — patternfly.org](https://www.patternfly.org/patterns/primary-detail/design-guidelines/) — HIGH confidence (open design system)
- ai_debug source code (debug_panel.js, json_tree.js, state_diff.js) — HIGH confidence (direct code review)
- PROJECT.md (v1.1 requirements) — HIGH confidence (direct project specification)

---

*Feature research for: Live agentic loop tracer — sidebar tree / master-detail layout (Odoo AI Debugger v1.1)*
*Researched: 2026-02-20*
