# Project Research Summary

**Project:** AI Debugger v1.4 — Subagent Hierarchy Visualization
**Domain:** Odoo standalone OWL app — AI agentic loop live tracer
**Researched:** 2026-02-23
**Confidence:** HIGH

## Executive Summary

The v1.4 milestone adds subagent hierarchy visualization to the existing `ai_debug` OWL app. The app already ships with IndexedDB persistence (v1.3), native Odoo theming (v1.2), and a working bus-event-driven trace store (v1.1). V1.4 is a contained, additive change: two new nullable fields in the Python `new_trace` bus event, a flat-Map-with-parent-pointers data model in the JS store, a computed `sidebarNodes` getter replacing the three-level nested template, per-agent color assignment, and a new IDB sentinel key for color persistence. No new npm packages, Odoo modules, or Python libraries are required. All patterns are verified against the live codebase at the worktree paths.

The recommended approach is: (1) instrument the Python backend to inject `_ai_debug_parent_trace_id` and `_ai_debug_parent_tool_call_id` into `env.context` before calling `super()._handle_tool_calls()` — this causes the child session's `_run_agentic_loop` override to emit parent linkage in `new_trace` automatically; (2) keep `this.traces` as a flat `useState(new Map())` keyed by `trace_id`, with parent pointer fields on each trace object rather than nesting child traces inside parent objects; (3) derive the sidebar display tree in a computed `sidebarNodes` getter using a depth-first recursive JavaScript function (not recursive OWL components, which OWL does not support as template recursion); (4) store agent colors as a sentinel record in the existing `traces` IDB store (key `__agent_colors__`) to avoid a DB version bump.

The key risks are well-identified and each has a low-cost mitigation: bus event ordering (child `new_trace` can arrive before the parent's `tool_call` event — requires a `_pendingChildren` buffer in the JS event handler), reactivity pitfalls (agent colors must live in `useState({})`, not a plain Map), selection logic breakage (existing `getSelectedTrace` getters must be audited when the flat+nested rendering model replaces the three-level hierarchy), and IDB serialization gaps (parent pointer fields must be explicitly added to `serializeTrace()` or they are silently lost on export/import). None of these are blocking unknowns — they are prevention patterns, not research questions.

## Key Findings

### Recommended Stack

No new dependencies are introduced in v1.4. The existing stack remains unchanged: OWL `mountComponent` for the standalone app, `bus_service` for event delivery, `@web/core/utils/indexed_db` for persistence, `downloadFile` from `@web/core/network/download` for export, and Odoo's SCSS/Bootstrap system for theming. The only backend component that changes is `ai_debug/models/ai_session.py` (Python instrumentation overrides).

**Core technologies:**

- `ai_debug/models/ai_session.py` (`_inherit = 'ai.session'`): Python instrumentation layer — detects subagent tool calls in `_handle_tool_calls`, injects parent trace linkage via `self.with_context(...)` before `super()`, emits `new_trace` events with `parent_trace_id` and `parent_tool_call_id`; a `reserved_subagent_tc_id` is generated before `super()` and used in the subsequent `tool_call` event so the parent and child refer to the same identifier
- `useState(new Map())` flat trace store in `AiDebugApp`: single reactive source of truth for all traces (root and subagent); child traces store `parent_trace_id` and `parent_tool_call_id` pointer fields, not nested inside parent objects; the rendering tree is derived from these pointers at render time
- `useState({})` reactive plain object for `agentColors`: keyed by `agent_name`; `useState({})` is required (not a plain Map) because OWL tracks property reads on `useState`-wrapped objects and triggers re-renders when new agent names are added
- `@web/core/utils/indexed_db` (`IndexedDB` class): persists serialized trace records; agent colors stored as a sentinel record keyed `__agent_colors__` in the existing `traces` object store (no schema version bump needed, avoids the `onupgradeneeded` failure mode)
- Computed `sidebarNodes` getter in `app.js`: produces a flat, ordered array of display node objects with `{type, id, depth, data}`; the template iterates this single array with one `t-foreach`; depth-based `padding-left` provides visual indentation; no recursive OWL components
- 8-slot hardcoded hex color palette (One Dark Pro-derived): assigned on first `new_trace` per agent name; values are static hex strings verified to work on both dark (`#1B1D26`) and light (`#F9FAFB`) Odoo backgrounds as 3px left-border accents

**What not to use:** recursive OWL components for tree rendering (OWL templates cannot recurse — causes double-render cascades and lifecycle ordering bugs); nested Map for child traces (breaks all existing lookup, serialize, and selection functions); `reactive()` without a render observer for color storage; IDB version bump for agent colors (use sentinel key instead to avoid wiping existing traces).

### Expected Features

**Must have (table stakes — v1.4 launch):**
- Subagent traces nest visually under the tool call that spawned them — causality is visible in the sidebar tree; every LLM observability tool (LangSmith, LangFuse, Arize Phoenix) implements this; flat listings lose causality
- Arbitrary recursive nesting depth — grandchildren and beyond render correctly; no hardcoded depth limit; the `sidebarNodes` getter's recursive `renderTrace` helper handles any depth
- Flat tree within each trace — iterations and tool calls appear at the same indentation level (not iterations > tool calls); with subagent nesting adding depth, the old 3-level within-trace hierarchy makes tool calls appear at 6 levels deep on standard monitors
- Per-agent color strip — 3px left border on trace rows in the agent's assigned color; fastest visual differentiator when scanning a multi-agent sidebar
- Color persisted across page refreshes — sentinel key in IDB preserves agent-to-color mapping across sessions
- Dark and light mode compatibility — hardcoded hex palette verified for both Odoo themes
- Collapsed parent hides all descendants — existing `trace.expanded` flag gates child trace rendering; unchanged mechanism

**Should have (differentiators, add after validation):**
- Agent legend in sidebar header — color swatches + agent names, read-only; add when 4+ agents cause orientation confusion
- Agent color chip in detail panel header — small colored badge next to agent name; add when deep hierarchies lose context

**Defer (v2+):**
- Search/filter sidebar by agent — explicitly deferred per PROJECT.md; breaks multi-agent context by hiding child traces of filtered-out agents
- Custom color picker per agent — deterministic hash + IDB is sufficient; picker adds UI complexity for marginal gain
- OpenTelemetry export with parent/child span relationships — v1.4 is a prerequisite; add in v2+
- Timeline/Gantt view — Odoo's agentic loop is synchronous; no concurrency to visualize

### Architecture Approach

The architecture follows the OpenTelemetry flat-span model: every trace (root or subagent) lives at the top level of `this.traces`, carries nullable `parent_trace_id` and `parent_tool_call_id` pointer fields, and the display hierarchy is computed from those pointers at render time in the `sidebarNodes` getter. This preserves all existing lookup functions, IDB write patterns, export/import logic, and selection state management with zero changes to their core logic. The only structural change is replacing the three-level nested `t-foreach` template with a single `t-foreach` over the computed node array, and removing the `iteration.expanded` toggle (iterations are always shown when their trace is expanded, at the same depth level as tool calls).

**Major components:**

1. `ai_debug/models/ai_session.py` (MODIFIED) — `_handle_tool_calls`: scans tool_calls before `super()`, detects subagent tool by `"ai_request_subagent"` substring, generates `reserved_subagent_tc_id`, injects `self.with_context(_ai_debug_parent_trace_id, _ai_debug_parent_tool_call_id)`; `_run_agentic_loop`: reads context fields, emits both in `new_trace` (null for root sessions)
2. `app.js` (MODIFIED) — adds `agentColors = useState({})`, `_pendingChildren = new Map()` buffer, `sidebarNodes` computed getter with depth-first recursive `renderTrace` helper, updated `_onNewTrace` (stores parent fields, assigns color, buffers if parent tool call not yet seen), updated `_onToolCall` (drains pending-child buffer after insert), updated `onWillStart` (loads colors from IDB before traces)
3. `app.xml` (MODIFIED) — single `t-foreach` over `sidebarNodes`; depth-based `padding-left: calc(node.depth * 12px + 8px)`; agent color swatch `<span>` on trace rows; `iteration.expanded` toggle and `toggleExpand` calls removed
4. `db.js` (MODIFIED) — `serializeTrace` and `hydrateTrace` gain `parent_trace_id`, `parent_tool_call_id`, `agent_color` fields; sentinel-key `writeAgentColors` and `loadAgentColors` functions added
5. `app.scss` (MODIFIED) — `.ai-agent-color-swatch` styling; CSS custom property for depth indentation

No new files are required for v1.4.

**Build order (dependency-aware):**
Steps 1 (Python) and 2 (IDB schema) are fully parallel. Step 3 (JS store + color) depends on step 1 for live data and step 2 for IDB. Step 4 (`sidebarNodes` getter) depends on step 3. Step 5 (template refactor) depends on step 4. Step 6 (SCSS) depends on step 5.

### Critical Pitfalls

1. **Child `new_trace` arrives before parent `tool_call`** — bus events are committed via separate database cursors with no ordering guarantee between them. Without a buffer, subagent traces silently land at root level. Prevention: implement `_pendingChildren = new Map()` in `setup()`; buffer child payloads when `parent_tool_call_id` is not yet in any trace; drain buffer in `_onToolCall` after inserting the tool call. Recovery if missed: add the buffer after the fact — medium cost.

2. **Nested subagent traces stored inside parent trace objects** — breaks every existing function that assumes `this.traces` is a flat Map keyed by `trace_id`: `getSelectedTrace`, `deleteCheckedTraces`, `exportSelected`, `serializeTrace`, `hydrateTrace`. Prevention: decide the flat model before writing any code. Recovery if missed: full data model refactor — high cost.

3. **`serializeTrace()` missing parent linkage fields** — the function explicitly enumerates fields; new fields on trace objects are silently dropped unless added to `serializeTrace()`. Hierarchy is lost on export/import. Prevention: audit `serializeTrace` and `hydrateTrace` together when adding any new field. Recovery: add fields and re-write IDB records on next `loop_end` — low cost.

4. **Agent colors stored in a plain (non-reactive) Map** — Map mutations are invisible to OWL; new agent color assignments don't trigger re-renders; sidebar rows appear colorless until the next unrelated event. Prevention: `this.agentColors = useState({})` (plain object, string keys), not `new Map()`. Recovery: change storage and wipe existing color assignments — low cost.

5. **Selection logic breaks with flat+nested rendering** — the existing selection getters (`getSelectedIteration`, `getSelectedToolCall`, `selectedTraceId`) were written for flat traces only. Subagent traces are also in `this.traces` so getters still find them, but `getRootTraceId()` must be added for cases that need the root-level trace. Prevention: audit all selection getters when refactoring the template; add `getRootTraceId(traceId)` that walks `parent_trace_id` to the root. Recovery: incremental getter fixes — low-to-medium cost.

## Implications for Roadmap

Based on research, the build order has clear dependencies. Python instrumentation is the independent starting point; IDB schema additions are parallel to Python; JS store updates depend on Python being in place for live data; the `sidebarNodes` getter depends on store changes; the template refactor depends on the getter; SCSS is last.

### Phase 1: Python Instrumentation + JS Bus Event Handling

**Rationale:** Every frontend feature depends on the backend emitting `parent_trace_id` and `parent_tool_call_id`. This is the unlock. Implementing the `_pendingChildren` buffer in JS at the same time prevents the bus ordering race from being discovered as a hard-to-reproduce bug. These two pieces are the first integration point to establish and verify before touching the store or rendering.

**Delivers:** `_handle_tool_calls` override detects subagent tool, injects context, uses `reserved_subagent_tc_id`; `_run_agentic_loop` override reads and emits `parent_trace_id` + `parent_tool_call_id` (null for root); `_onNewTrace` buffers children when parent tool call not yet seen; `_onToolCall` drains buffer after insert; `_onLoopEnd` unchanged; backward compatible (existing non-subagent sessions emit null for both fields).

**Addresses:** Subagent trace nesting (table stake #1), arbitrary recursive depth (table stake #2).

**Avoids:** Pitfall 1 (pending-child buffer), Pitfall 3 (context injection must precede `super()` call — verified pattern from ARCHITECTURE.md).

### Phase 2: Data Model, IDB Schema, Color Assignment

**Rationale:** IDB changes are independent of live Python events and can proceed in parallel with Phase 1. The flat-Map-with-parent-pointers decision must be locked in before rendering work begins — switching from nested to flat after template code is written is a major refactor. Agent color assignment and IDB persistence for colors are low-complexity and belong here with the data model.

**Delivers:** `parent_trace_id`, `parent_tool_call_id`, `agent_color` fields on trace objects; `serializeTrace` and `hydrateTrace` updated for all three fields; `agentColors = useState({})` reactive store; `_assignAgentColor` method; sentinel-key `writeAgentColors` / `loadAgentColors` in `db.js`; two-pass hydration (load all traces first, then validate parent pointers); `onWillStart` loads colors before traces.

**Uses:** `@web/core/utils/indexed_db` (existing); sentinel key pattern (no version bump); `useState({})` for color reactivity.

**Implements:** Flat trace store with parent pointers, IDB persistence for colors (ARCHITECTURE.md Q2, Q4).

**Avoids:** Pitfall 2 (flat model decided upfront), Pitfall 4 (colors in `useState`), Pitfall 5 (colors in `useState({})`, not plain Map), Pitfall 6 (sentinel key, no version bump needed), Pitfall 7 (two-pass hydration), Pitfall 8 (linkage fields in `serializeTrace`), Pitfall 9 (colors keyed by `agent_name`).

### Phase 3: Sidebar Rendering Refactor

**Rationale:** Depends on Phase 1 (parent pointers in live events) and Phase 2 (parent pointers in store). The `sidebarNodes` computed getter and template refactor are a single coherent change — the getter defines the data contract the template consumes, so they must be implemented together. Selection logic audit is a required step within this phase; skipping it produces incorrect ancestor highlighting for items inside subagent traces.

**Delivers:** `sidebarNodes` getter with depth-first `renderTrace` recursive helper producing flat ordered node array; single `t-foreach` template over `sidebarNodes`; depth-based `padding-left` indentation; agent color swatch on trace rows; `iteration.expanded` toggle removed; `getRootTraceId(traceId)` helper; all selection getters audited.

**Avoids:** Pitfall 4 (selection logic audit), Pitfall 10 (flat iterative rendering, not recursive OWL components).

### Phase 4: Export/Import Verification and SCSS Polish

**Rationale:** Export/import is the final integration point that exercises the full data lifecycle (Python events -> JS store -> IDB -> serialize -> export -> import -> hydrate -> render). SCSS is last because it has no code dependencies — only element class names from Phase 3. Running the "looks done but isn't" checklist from PITFALLS.md as a structured step before closing the milestone catches silent failures.

**Delivers:** Export confirmed to include parent linkage fields; import reconstructs nesting correctly (two-pass after load); `.ai-agent-color-swatch` SCSS styling; CSS custom property for depth indentation; PITFALLS.md verification checklist completed and passing.

**Avoids:** Pitfall 8 (export missing linkage fields — verify by inspecting exported JSON).

### Phase Ordering Rationale

- Python instrumentation must come first because there is no parent linkage to observe without it. The pending-child buffer must exist before any subagent can trigger the race condition.
- Data model decisions (flat Map) must be made before any rendering code — the nested-Map anti-pattern discovered late is the highest-recovery-cost mistake in PITFALLS.md (full refactor).
- The `sidebarNodes` getter bundles the tree computation and template refactor — splitting them creates an intermediate broken state where the getter exists but the template still uses the old nested `t-foreach`.
- Export/import verification is last because it exercises the complete stack and is the best integration test for all earlier phases working together.

### Research Flags

No additional `/gsd:research-phase` is needed for any phase. All patterns are verified from direct source reading. No external APIs, undocumented integrations, or speculative assumptions remain.

**Standard patterns (skip research-phase):**
- **Phase 1 (Python instrumentation):** `env.context` injection before `super()` is a standard Odoo override pattern. `_handle_tool_calls` and `_run_agentic_loop` override structure verified directly from `ai_debug/models/ai_session.py`. `parent_session_id` field existence verified from `enterprise/ai/models/ai_session.py` line 62. No unknowns.
- **Phase 2 (data model + IDB + colors):** Flat Map with parent pointers is the established OpenTelemetry span model. `useState({})` reactivity for plain objects is verified from existing codebase patterns. Sentinel key approach avoids the `onupgradeneeded` version bump entirely. Two-pass hydration is standard load-then-link. No unknowns.
- **Phase 3 (rendering):** `sidebarNodes` flat-array pattern eliminates template recursion concerns. CSS depth-indentation is trivial. Selection getter audit is procedural.
- **Phase 4 (verification + SCSS):** No new patterns. Checklist-driven.

One empirical check needed during implementation (not a research gap):
- **IDB sentinel key shape compatibility:** The `loadAllTraces()` function does `getAll()` and processes every record. The sentinel record (key `__agent_colors__`, no `trace_id` field) must be filtered out before `hydrateTrace()` is called on it. Add a `if (!record.trace_id) continue` guard in the hydration loop.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All technologies verified by direct source reading of the live codebase. No external dependencies introduced. Every import path confirmed reachable from `ai_debug.assets`. |
| Features | HIGH | Table stakes derived from PROJECT.md requirements (HIGH) and LangSmith/LangFuse/Arize patterns (MEDIUM for UI conventions; HIGH for the underlying principle that subagent causality must be visible). Differentiators and anti-features clearly reasoned from existing architecture. |
| Architecture | HIGH | `sidebarNodes` getter, flat-Map-with-parent-pointers, `env.context` injection — all derived from direct source reading and reasoned against the full 627-line `app.js`, 201-line `app.xml`, and 143-line `db.js`. Anti-patterns derived from code analysis, not speculation. |
| Pitfalls | HIGH | Bus event ordering race is empirically grounded (separate cursors, no ordering guarantee — verified from `_ai_debug_bus_send` implementation). OWL reactivity pitfalls verified from existing code patterns and PROJECT.md key decisions. IDB version semantics verified from Odoo `IndexedDB` class source (`_checkVersion()` deletes and recreates on version change). |

**Overall confidence:** HIGH

### Gaps to Address

- **`parent_call_id` exact disambiguation for parallel subagents:** When one agent iteration calls multiple subagent tools in the same iteration, matching each child trace to its exact spawning tool call requires threading the LLM's `call_id` through `env.context`. Deferred to v1.4.1 per STACK.md recommendation. The common case (one subagent call per iteration) works correctly with the `parent_session_id` mapping approach. Accept this limitation for v1.4.

- **IDB sentinel key shape filter in `loadAllTraces()`:** The sentinel record (key `__agent_colors__`) has no `trace_id` field. The hydration loop must filter it out before calling `hydrateTrace()`. This is a one-line guard, not a design issue.

- **Color palette contrast on Odoo's actual dark theme:** The 8-slot One Dark Pro palette is documented as having good contrast on dark and light IDE backgrounds but should be spot-checked against Odoo's `$o-gray-100 = #1B1D26` (dark background) and `#F9FAFB` (light background) at implementation time. The 3px border accent requires only 3:1 contrast (WCAG AA for decorative elements) — all 8 slots are expected to pass easily.

## Sources

### Primary (HIGH confidence — direct source reads at worktree paths)

- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — full instrumentation override (334 lines); `_run_agentic_loop`, `_handle_tool_calls`, `_ai_debug_bus_send`, `_ai_debug_state_snapshot`
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.js` — reactive store, bus handlers, hydration, selection getters (627 lines)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/app.xml` — sidebar template, 3-level nested `t-foreach` (201 lines)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/static/src/app/db.js` — IDB schema, `serializeTrace`, `hydrateTrace`, `writeTrace`, `loadAllTraces` (143 lines)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` — upstream agentic loop, `_handle_tool_calls` subagent forward, `parent_session_id` field at line 62 (478 lines)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_agent.py` — `_ai_tool_request_sub_agent` at line 1339, `make_tool_name`, `parent_session_id` set in create dict at line 1365
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/data/ir_actions_server_data.xml` — subagent tool record confirming name "AI: Request Sub-Agent" → `ai_request_sub_agent_{id}`
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/web/static/src/core/utils/indexed_db.js` — `IndexedDB` class: `read`, `write`, `getAllKeys`, `invalidate`, `execute`, `_checkVersion` (version bump deletes and recreates DB)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/.planning/PROJECT.md` — v1.4 requirements, key decisions, constraints

### Secondary (MEDIUM confidence — training data as of August 2025)

- LangSmith multi-agent run tree — nested child runs under spawning parent; causality via indentation; color coding per run type
- LangFuse span model — color as type/identity signal (not status); OpenTelemetry-compatible flat span storage with `parent_id`
- Arize Phoenix agent trace model — flat span storage with `parent_id` pointer; recursive rendering with no hardcoded depth limit
- OpenTelemetry tracing specification — `parent_span_id` as canonical way to express span causality; flat span model
- One Dark Pro palette — 8 colors, battle-tested contrast on dark/light IDE backgrounds used across VS Code, Atom, and many terminals
- WCAG 2.1 — AA minimum 4.5:1 for text, 3:1 for decorative elements (applies to 3px border accent use case)

---

*Research completed: 2026-02-23*
*Ready for roadmap: yes*
