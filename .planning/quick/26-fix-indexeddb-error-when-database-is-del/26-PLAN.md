---
phase: quick-26
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/db.js
autonomous: true
requirements: [QUICK-26]
must_haves:
  truths:
    - "Page refresh after external IndexedDB deletion does not throw NotFoundError"
    - "loadAllTraces returns [] when the traces store is missing or was recreated"
    - "writeTrace and deleteTrace work normally after the DB is recreated"
    - "Existing behavior is unchanged when IDB is not deleted"
  artifacts:
    - path: "ai_debug/static/src/app/db.js"
      provides: "Resilient IndexedDB operations that handle missing object stores"
  key_links:
    - from: "ai_debug/static/src/app/db.js"
      to: "@web/core/utils/indexed_db.js"
      via: "idb._tables registration ensures store creation on upgrade"
      pattern: "idb\\._tables\\.add"
---

<objective>
Fix NotFoundError thrown when the IndexedDB database is deleted externally (e.g., via DevTools) and the ai_debug page is refreshed.

Purpose: The error occurs because `loadAllTraces()` and `deleteTrace()` call `idb.execute()` directly, which does not register the "traces" store in `idb._tables`. When the DB is recreated on open, only the `__DBVersion__` store gets created during `onupgradeneeded`. The subsequent `db.transaction("traces")` call fails because the store does not exist.

Output: Patched `db.js` that eagerly registers the store and defensively guards against missing object stores.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/db.js
@web/static/src/core/utils/indexed_db.js (upstream — read only, do not modify)
</context>

<tasks>

<task type="auto">
  <name>Task 1: Register store eagerly and guard against missing object stores</name>
  <files>ai_debug/static/src/app/db.js</files>
  <action>
Two changes are needed in `ai_debug/static/src/app/db.js`:

**Change 1 — Eager store registration (root cause fix):**

After `const idb = new IndexedDB(DB_NAME, DB_VERSION);` on line 8, add:

```js
// Ensure the "traces" store is registered with the IndexedDB utility so that
// onupgradeneeded creates it when the DB is opened (e.g. after external deletion).
// Without this, direct idb.execute() calls skip store registration (only read/write/
// getAllKeys add to _tables) and the store won't exist after DB recreation.
idb._tables.add(STORE);
```

This ensures that whenever `_execute` opens the database, if the `traces` store is missing, `onupgradeneeded` will fire and create it — exactly as it would for `read()`/`write()`/`getAllKeys()` which call `_tables.add()` internally.

**Change 2 — Defensive guard in loadAllTraces (belt-and-suspenders):**

In `loadAllTraces()`, before creating the transaction, check that the store exists in `db.objectStoreNames`. If the store is missing (edge case: race with external deletion mid-session), return `[]` gracefully instead of throwing:

```js
export async function loadAllTraces() {
    return idb.execute((db) => {
        if (!db) return [];
        if (!db.objectStoreNames.contains(STORE)) return [];
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readonly");
            const req = tx.objectStore(STORE).getAll();
            req.onsuccess = () => resolve(req.result ?? []);
            tx.onerror = () => reject(tx.error);
        });
    });
}
```

**Change 3 — Defensive guard in deleteTrace:**

Same pattern for `deleteTrace()` — if the store is missing, return silently (nothing to delete):

```js
export async function deleteTrace(traceId) {
    return idb.execute((db) => {
        if (!db) return;
        if (!db.objectStoreNames.contains(STORE)) return;
        return new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, "readwrite");
            tx.objectStore(STORE).delete(traceId);
            tx.oncomplete = resolve;
            tx.onerror = () => reject(tx.error);
            tx.commit();
        });
    });
}
```

Do NOT modify the upstream `@web/core/utils/indexed_db.js` — it belongs to core Odoo.
  </action>
  <verify>
1. Open the ai_debug page, create or import a trace so data exists in IDB.
2. Open DevTools > Application > IndexedDB, delete the `ai_debug_traces` database.
3. Refresh the page.
4. Expected: No console error, page loads normally with empty trace list, ephemeral mode is NOT triggered (IDB is available, just empty).
5. Create a new trace — it should persist to IDB normally.
6. Refresh again — the new trace should be hydrated from IDB.

Automated: `grep -n "_tables.add" ai_debug/static/src/app/db.js` should show the eager registration line. `grep -n "objectStoreNames.contains" ai_debug/static/src/app/db.js` should show two guard lines (loadAllTraces and deleteTrace).
  </verify>
  <done>
Page refresh after external IDB deletion loads without errors. loadAllTraces returns [] when the store is missing. Subsequent writes recreate the store and work normally. No changes to upstream IndexedDB utility.
  </done>
</task>

</tasks>

<verification>
- No `NotFoundError` in console after deleting IDB and refreshing
- Traces list is empty after DB deletion + refresh (graceful degradation, not error)
- New traces persist normally after recovery
- Normal flow (no DB deletion) is completely unaffected
</verification>

<success_criteria>
The ai_debug page handles external IndexedDB deletion gracefully: no errors on refresh, empty state shown, and subsequent operations work normally as the store is auto-recreated.
</success_criteria>

<output>
After completion, create `.planning/quick/26-fix-indexeddb-error-when-database-is-del/26-SUMMARY.md`
</output>
