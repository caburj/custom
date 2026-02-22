---
status: complete
phase: 11-hydration-and-trace-management
source: 11-01-SUMMARY.md, 11-02-SUMMARY.md
started: 2026-02-22T20:00:00Z
updated: 2026-02-22T20:15:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Traces persist across page reload
expected: Create one or more traces, then refresh the page. Previously saved traces should reappear in the sidebar after reload.
result: pass

### 2. Hydrated traces show "archived" badge
expected: After refreshing the page, traces loaded from storage should display a muted italic "archived" text badge next to the trace label in the sidebar.
result: pass

### 3. Most recent trace auto-selected on load
expected: After refreshing the page with multiple saved traces, the most recent trace should be automatically selected and its details shown in the main panel.
result: pass

### 4. Hydrated traces load collapsed
expected: After refreshing, all hydrated traces should appear with their iterations collapsed (not expanded). You should see the top-level trace rows but no expanded child content.
result: pass

### 5. Row checkboxes in sidebar
expected: Each trace row in the sidebar should have a small checkbox on the left side (before the expand chevron). Clicking the checkbox should toggle its checked state.
result: pass

### 6. Select-all checkbox in header
expected: The sidebar header area (near "Traces" label) should have a select-all checkbox. Clicking it should check all trace rows. Clicking again should uncheck all.
result: pass

### 7. Select-all indeterminate state
expected: When some (but not all) traces are checked via row checkboxes, the select-all checkbox in the header should show an indeterminate state (a dash or filled square instead of a checkmark).
result: pass

### 8. Bulk delete selected traces
expected: Check one or more traces, then click the delete button. The checked traces should be removed from the sidebar and from IndexedDB (they should not reappear on refresh).
result: pass (fixed)
reported: "they're deleted, but they reappear after refresh."
severity: major
fix: "idb.delete() does not exist on Odoo IndexedDB class — replaced with idb.execute() using raw readwrite transaction"

### 9. Delete button disabled when none selected
expected: When no trace checkboxes are checked, the delete button in the header should appear disabled (grayed out, unclickable).
result: pass

### 10. Checkbox click does not change detail view
expected: Clicking a trace's checkbox should only toggle the check state — it should NOT change which trace is displayed in the detail panel on the right.
result: pass

## Summary

total: 10
passed: 10
issues: 0
pending: 0
skipped: 0

## Gaps

- truth: "Checked traces are removed from sidebar and from IndexedDB (they should not reappear on refresh)"
  status: fixed
  reason: "User reported: they're deleted, but they reappear after refresh."
  severity: major
  test: 8
  root_cause: "idb.delete() does not exist on Odoo IndexedDB class — used idb.execute() with raw readwrite transaction instead"
  artifacts:
    - path: "ai_debug/static/src/app/db.js"
      issue: "deleteTrace called non-existent idb.delete() method"
  missing: []
  debug_session: ""

