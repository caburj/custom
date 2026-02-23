---
phase: quick-27
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/db.js
autonomous: true
requirements: [CASCADE-DELETE]

must_haves:
  truths:
    - "Deleting a root trace removes all descendant subagent traces from the sidebar"
    - "Deleting a root trace removes all descendant subagent traces from IndexedDB"
    - "If the detail panel is showing a descendant trace/iteration/tool_call of a deleted trace, the selection is cleared"
    - "Bulk delete (select-all + delete) cascades to descendants of every checked trace"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "Cascade delete logic in deleteCheckedTraces and helper method"
      contains: "_collectDescendantIds"
    - path: "ai_debug/static/src/app/db.js"
      provides: "Batch delete function for multiple trace IDs"
      contains: "deleteTraces"
  key_links:
    - from: "app.js deleteCheckedTraces"
      to: "app.js _collectDescendantIds"
      via: "gathers full descendant tree before deletion"
      pattern: "_collectDescendantIds"
    - from: "app.js deleteCheckedTraces"
      to: "db.js deleteTraces"
      via: "batch IDB deletion of all collected IDs"
      pattern: "deleteTraces"
---

<objective>
When deleting a trace (via checkbox bulk delete), all descendant subagent traces must also be deleted — both from the reactive in-memory Map and from IndexedDB. Currently, only the checked root traces are removed, leaving orphaned child traces.

Purpose: Prevent orphaned subagent traces from accumulating in storage and appearing as disconnected root entries after their parent is deleted.
Output: Updated app.js with cascade delete logic, updated db.js with batch delete function.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/db.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add batch deleteTraces to db.js and cascade delete logic to app.js</name>
  <files>ai_debug/static/src/app/db.js, ai_debug/static/src/app/app.js</files>
  <action>
**db.js — Add `deleteTraces(traceIds)` batch function:**

Add a new exported function `deleteTraces(traceIds)` that deletes multiple trace records in a single IDB transaction. This is more efficient than calling `deleteTrace()` N times (each opens its own transaction).

```js
export async function deleteTraces(traceIds) {
    if (!traceIds.length) return;
    return idb.execute((db) => {
        if (!db) return;
        if (!db.objectStoreNames.contains(STORE)) return;
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readwrite");
            const store = tx.objectStore(STORE);
            for (const id of traceIds) {
                store.delete(id);
            }
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
            tx.commit();
        });
    });
}
```

**app.js — Add `_collectDescendantIds(traceId)` helper method:**

Add a method to AiDebugApp that recursively collects all descendant trace IDs of a given trace. A descendant is any trace whose `parent_trace_id` matches the given traceId, plus recursively their descendants:

```js
_collectDescendantIds(traceId) {
    const descendants = [];
    for (const [id, trace] of this.traces) {
        if (trace.parent_trace_id === traceId) {
            descendants.push(id);
            descendants.push(...this._collectDescendantIds(id));
        }
    }
    return descendants;
}
```

Place this method right after the existing `_collectTraceNodes` method (around line 557) since they are both tree-traversal helpers.

**app.js — Update `deleteCheckedTraces()` to cascade:**

1. Import `deleteTraces` from `./db` (add to existing import on line 8). Keep the existing `deleteTrace` import since it may be used elsewhere (actually check — it is only used in `deleteCheckedTraces`, so replace it with `deleteTraces`).
2. After collecting `ids` from `checkedTraceIds`, expand the list to include all descendants:
   ```js
   // Collect all descendant trace IDs for cascade delete
   const allIds = [...ids];
   for (const id of ids) {
       allIds.push(...this._collectDescendantIds(id));
   }
   // Deduplicate (a descendant could also be checked, or shared descendants)
   const uniqueIds = [...new Set(allIds)];
   ```
3. Use `uniqueIds` instead of `ids` for:
   - The `selectedId` check (clear selection if selectedId is in uniqueIds, OR if the selectedId is an iteration/tool_call belonging to any trace in uniqueIds)
   - The `this.traces.delete()` loop
4. Replace the per-item `deleteTrace()` IDB calls with a single `deleteTraces(uniqueIds)` call.
5. For the selection clearing, also check if the currently selected iteration or tool_call belongs to a trace being deleted:
   ```js
   // Clear detail panel if selected item belongs to any deleted trace
   if (uniqueIds.includes(this.state.selectedId) || this._selectionBelongsToTraces(uniqueIds)) {
       this.state.selectedId = null;
       this.state.selectedType = null;
   }
   ```
   Where `_selectionBelongsToTraces(traceIds)` checks if the current selectedId (when selectedType is 'iteration' or 'tool_call') is inside any of the given traces. Actually, simpler: just check `this.selectedTraceId` (existing getter) against the uniqueIds list:
   ```js
   if (uniqueIds.includes(this.state.selectedId) || uniqueIds.includes(this.selectedTraceId)) {
       this.state.selectedId = null;
       this.state.selectedType = null;
   }
   ```
   This handles all cases: if a trace itself is selected, or if an iteration/tool_call within a deleted trace is selected.

**Updated deleteCheckedTraces:**
```js
deleteCheckedTraces() {
    const ids = [...this.state.checkedTraceIds];
    if (ids.length === 0) return;
    // Collect all descendant trace IDs for cascade delete
    const allIds = [...ids];
    for (const id of ids) {
        allIds.push(...this._collectDescendantIds(id));
    }
    const uniqueIds = [...new Set(allIds)];
    // Clear checkbox selection first
    this.state.checkedTraceIds.clear();
    // Clear detail panel selection if the viewed item belongs to a deleted trace
    if (uniqueIds.includes(this.state.selectedId) || uniqueIds.includes(this.selectedTraceId)) {
        this.state.selectedId = null;
        this.state.selectedType = null;
    }
    // Remove from reactive Map (triggers OWL re-render immediately)
    for (const id of uniqueIds) {
        this.traces.delete(id);
    }
    // Delete from IDB in a single transaction (fire-and-forget)
    deleteTraces(uniqueIds).catch((err) => {
        console.warn("[ai_debug] IDB cascade delete failed:", err);
    });
}
```

**Import update:** Change line 8 from:
```js
import { probeIDB, writeTrace, deleteTrace, loadAllTraces, serializeTrace } from "./db";
```
to:
```js
import { probeIDB, writeTrace, deleteTraces, loadAllTraces, serializeTrace } from "./db";
```
(Replace `deleteTrace` with `deleteTraces` — singular is no longer needed.)
  </action>
  <verify>
    <automated>cd /Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro && node -e "
      const fs = require('fs');
      const app = fs.readFileSync('ai_debug/static/src/app/app.js', 'utf8');
      const db = fs.readFileSync('ai_debug/static/src/app/db.js', 'utf8');
      const checks = [
        [db.includes('export async function deleteTraces'), 'db.js exports deleteTraces'],
        [db.includes('for (const id of traceIds)'), 'db.js iterates traceIds in single tx'],
        [app.includes('_collectDescendantIds'), 'app.js has _collectDescendantIds method'],
        [app.includes('deleteTraces'), 'app.js imports/uses deleteTraces'],
        [!app.includes('deleteTrace('), 'app.js no longer calls singular deleteTrace()'],
        [app.includes('_collectDescendantIds(id)'), 'deleteCheckedTraces calls _collectDescendantIds'],
        [app.includes('new Set(allIds)'), 'deduplication via Set'],
        [app.includes('selectedTraceId'), 'selection clearing checks selectedTraceId getter'],
      ];
      let pass = true;
      for (const [ok, label] of checks) {
        console.log(ok ? 'PASS' : 'FAIL', label);
        if (!ok) pass = false;
      }
      process.exit(pass ? 0 : 1);
    "
    </automated>
    <manual>
      1. Open AI Debugger, trigger a parent agent + subagent trace
      2. Check the parent trace checkbox in sidebar
      3. Click delete — both parent and child subagent traces should disappear
      4. Refresh page — neither parent nor child should reappear from IDB
      5. Select an iteration inside a subagent trace, then delete the root parent — detail panel should clear
    </manual>
  </verify>
  <done>
    - Checking and deleting a root trace removes it AND all descendant subagent traces from both the reactive Map and IndexedDB
    - Selection is cleared if the detail panel was showing any item inside a deleted trace tree
    - IDB deletion uses a single transaction for efficiency
    - No orphaned child traces remain after parent deletion
  </done>
</task>

</tasks>

<verification>
- `deleteCheckedTraces()` collects descendant IDs recursively before deleting
- `deleteTraces()` in db.js performs batch IDB deletion in one transaction
- Selection clearing accounts for iteration/tool_call selected inside a deleted trace
- No references to the old singular `deleteTrace` remain in app.js
</verification>

<success_criteria>
- Deleting a root trace cascades to all nested subagent traces (any depth)
- Both in-memory Map and IndexedDB are cleaned up
- Detail panel clears when any ancestor trace is deleted
- Bulk select-all + delete works correctly with cascade
</success_criteria>

<output>
After completion, create `.planning/quick/27-when-deleting-a-trace-all-descendant-tra/27-SUMMARY.md`
</output>
