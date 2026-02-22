---
phase: 11-hydration-and-trace-management
plan: 02
subsystem: ai_debug trace management UI
tags: [checkbox-selection, bulk-delete, owl-reactive, indexeddb, sidebar]
dependency_graph:
  requires: [11-01]
  provides: [MGMT-01, MGMT-02]
  affects: [ai_debug/static/src/app/app.js, ai_debug/static/src/app/app.xml, ai_debug/static/src/app/app.scss]
tech_stack:
  added: []
  patterns: [OWL reactive Set in useState, t-ref + onPatched indeterminate sync, t-on-change.stop event bubbling prevention, t-att-disabled or undefined idiom]
key_files:
  created: []
  modified:
    - ai_debug/static/src/app/app.js
    - ai_debug/static/src/app/app.xml
    - ai_debug/static/src/app/app.scss
decisions:
  - "deleteCheckedTraces is non-async — IDB deletes are fire-and-forget via .catch() consistent with writeTrace pattern"
  - "indeterminate property set via t-ref + onPatched (not t-att-indeterminate which does not exist as an HTML attribute)"
  - "t-att-disabled uses 'expr or undefined' idiom to remove the attribute entirely when false (avoids disabled='false' which still disables)"
  - "checkedTraceIds Set lives in this.state (not standalone reactive) so OWL tracks .size changes via the proxy"
  - "clearAll() fully replaced by deleteCheckedTraces() — new method does dual reactive Map + IDB delete, old method only cleared the Map"
metrics:
  duration: ~1 minute
  completed: 2026-02-22
  tasks_completed: 2
  files_modified: 3
---

# Phase 11 Plan 02: Checkbox Multi-Select and Bulk Delete Summary

**One-liner:** Checkbox-based multi-select in sidebar with select-all/indeterminate state and bulk delete wired to both reactive Map and IDB, replacing the old clearAll button.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Add selection state, getters, toggle methods, and deleteCheckedTraces to app.js | 1a86f8c | app.js |
| 2 | Update sidebar header and trace rows with checkboxes and action bar | 6a177bc | app.xml, app.scss |

## What Was Built

### Task 1: Selection logic in app.js

**Import update:** Added `deleteTrace` to the existing db.js import line. `deleteTrace` was already exported from db.js (Phase 10) — this plan just surfaces it in the component.

**`checkedTraceIds` in state:** Added `checkedTraceIds: new Set()` to the existing `useState({...})` block. OWL's reactive proxy wraps the Set so that `.size`, `.has()`, `.add()`, `.delete()`, and `.clear()` mutations are observed in the render function. Placing it in `this.state` (rather than a standalone `reactive(new Set())`) keeps all UI state co-located.

**`selectAllRef`:** Added `this.selectAllRef = useRef("selectAll")` after `sidebarRef`. The `t-ref="selectAll"` in the template wires this ref to the select-all checkbox DOM node.

**`onPatched` indeterminate sync:** Added `if (this.selectAllRef.el) { this.selectAllRef.el.indeterminate = this.someChecked; }` as the first thing in `onPatched`, before the existing scroll/flash logic. The `indeterminate` property is a JavaScript DOM property, not an HTML attribute — it cannot be set via `t-att-indeterminate`. The `t-ref + onPatched` pattern is the correct OWL approach (same pattern as the existing `sidebarRef` scroll logic).

**`allChecked` / `someChecked` getters:** Both derive from `checkedTraceIds.size` and `traces.size`. `someChecked` is the indeterminate condition (some but not all selected).

**`toggleTraceCheck(traceId)`:** Adds or removes a single trace ID from `checkedTraceIds`. The event `.stop` modifier in the template prevents this from bubbling to the row's click handler (which would change the detail panel selection — Pitfall 6 from the research phase).

**`toggleSelectAll()`:** If `allChecked`, clears the Set. Otherwise iterates `this.traces.keys()` and adds each ID.

**`deleteCheckedTraces()`:** Non-async. Snapshots the IDs to a plain array, then: (1) clears `checkedTraceIds`, (2) clears `selectedId/selectedType` if the viewed trace is being deleted, (3) removes each ID from the reactive Map (triggering OWL re-render), (4) fire-and-forget `deleteTrace(id).catch()` for each ID.

**Removed `clearAll()`:** The old method only cleared the reactive Map — it did not delete from IDB. `deleteCheckedTraces()` is the proper replacement for all scenarios (select-all then delete achieves the same outcome as clearAll, but also handles IDB).

### Task 2: Template and SCSS

**Header restructure:** The old `<div class="ai-tree-header">` with a single `<span>Traces</span>` and trash button is replaced with a two-child flexbox: `.ai-tree-header-left` (select-all checkbox + "Traces" label) and `.ai-tree-header-actions` (delete button). The `.ai-tree-header-actions` div is designed to accommodate a future Export button (Phase 12) without layout changes.

**Select-all checkbox:** Uses `t-ref="selectAll"` for indeterminate sync, `t-att-checked="allChecked"` for the checked state, and `t-on-change.stop="toggleSelectAll"` to prevent event bubbling.

**Delete button:** Uses `t-att-disabled="state.checkedTraceIds.size === 0 or undefined"` — the `or undefined` idiom removes the `disabled` attribute entirely when false (some browsers treat `disabled="false"` as still-disabled).

**Row checkboxes:** Added `<input type="checkbox" class="ai-tree-row-check" t-att-checked="state.checkedTraceIds.has(traceId)" t-on-change.stop="() => this.toggleTraceCheck(traceId)"/>` as the first child of each `.ai-tree-row.level-0`, before the chevron. The `.stop` modifier is critical — without it, the change event would bubble to the row div and trigger any ancestor click handlers.

**SCSS:** Replaced `.ai-tree-clear` block with:
- `.ai-tree-header-left` — flex row with gap for checkbox + label
- `.ai-tree-header-actions` — flex row for action buttons
- `.ai-tree-action-btn` — shared button style with hover (opacity + danger color + background) and disabled (opacity 0.3, not-allowed cursor) states
- `.ai-tree-row-check` / `.ai-tree-select-all` — minimal checkbox styles (flex-shrink, cursor, no margin)

Level indentation adjusted: level-0 from 8px to 4px; level-1 from 28px to 24px; level-2 from 48px to 44px. The 4px reduction maintains relative indentation hierarchy while accommodating the 18px checkbox at level-0.

## Deviations from Plan

None — plan executed exactly as written.

## Self-Check

### Files exist
- `ai_debug/static/src/app/app.js` — FOUND
- `ai_debug/static/src/app/app.xml` — FOUND
- `ai_debug/static/src/app/app.scss` — FOUND

### Commits exist
- 1a86f8c — Task 1: selection state, getters, methods in app.js
- 6a177bc — Task 2: template header/row checkboxes and SCSS

## Self-Check: PASSED
