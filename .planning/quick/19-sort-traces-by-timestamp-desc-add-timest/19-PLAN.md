---
phase: "19"
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/db.js
autonomous: true
requirements: [SORT-01]

must_haves:
  truths:
    - "Traces in sidebar are always ordered newest-first regardless of source (live, hydrated, imported)"
    - "Each trace carries a numeric timestamp that determines its sort position"
    - "Exported JSON includes the timestamp so re-import preserves original ordering"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "Timestamp assignment + sorted insertion for hydration and import"
      contains: "created_ts"
    - path: "ai_debug/static/src/app/db.js"
      provides: "created_ts in serialized trace schema"
      contains: "created_ts"
  key_links:
    - from: "ai_debug/static/src/app/app.js"
      to: "ai_debug/static/src/app/db.js"
      via: "serializeTrace includes created_ts, loadAllTraces returns it"
      pattern: "created_ts"
---

<objective>
Add a `created_ts` numeric timestamp to every trace and sort traces chronologically so the sidebar always shows newest-first, regardless of whether traces arrive live, are hydrated from IndexedDB, or are imported from a JSON file.

Purpose: Currently, hydrated and imported traces appear in unpredictable order (IDB getAll returns by key = UUID lexicographic order, not chronological). Adding an explicit timestamp and sorting on load/import makes ordering deterministic and correct.

Output: Modified app.js and db.js with timestamp-based trace ordering.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/app.xml
@ai_debug/static/src/app/db.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add created_ts to trace lifecycle and serialize/hydrate paths</name>
  <files>ai_debug/static/src/app/app.js, ai_debug/static/src/app/db.js</files>
  <action>
**In db.js — serializeTrace():**
- Add `created_ts: trace.created_ts` to the serialized record (alongside the existing `storedAt` field). `created_ts` is a numeric epoch ms timestamp representing when the trace was first created. `storedAt` is when it was last persisted — these are different concepts.

**In app.js — _onNewTrace handler:**
- Add `created_ts: Date.now()` to the trace object literal (line ~92-107, alongside `started_at: new Date()`). This captures exact creation time as a sortable number.

**In app.js — hydrateTrace():**
- After reconstructing the trace object, preserve `created_ts` from the plain record: `created_ts: plain.created_ts || null`.
- If `created_ts` is null/missing (old records pre-migration), derive it: `created_ts: plain.created_ts || (plain.started_at ? new Date(plain.started_at).getTime() : 0)`. This handles legacy records that lack the field by falling back to `started_at`.

**In app.js — onWillStart hydration block (lines ~199-208):**
- After `const stored = await loadAllTraces()`, sort the array before inserting into the Map: `stored.sort((a, b) => (a.created_ts || 0) - (b.created_ts || 0))`. This ensures Map insertion order = chronological (oldest first). The template's existing `.reverse()` call on `[...traces.keys()]` then gives newest-first display.
- For the fallback derivation of created_ts during sort, use `(a.created_ts || new Date(a.started_at || 0).getTime())` to handle old records without created_ts.

**In app.js — _applyImport():**
- Before the `for (const record of records)` loop, sort the records array: `records.sort((a, b) => (a.created_ts || new Date(a.started_at || 0).getTime()) - (b.created_ts || new Date(b.started_at || 0).getTime()))`.
- This ensures imported traces are inserted into the Map in chronological order, same as hydration.

**In app.js — _applyImport() — hydrateTrace already handles created_ts:**
No additional changes needed in _applyImport's per-record logic since hydrateTrace() already derives created_ts from the record.

**Do NOT change:**
- The template (app.xml) — it already uses `[...traces.keys()].reverse()` which gives newest-first when Map insertion order is oldest-first
- The storedAt field in db.js — it serves a different purpose (last-persisted time)
  </action>
  <verify>
1. Open the AI Debugger app in the browser
2. Verify existing hydrated traces from IDB appear in chronological order (newest at top)
3. Export a few traces, then re-import them — they should appear in the same chronological order, not jumbled by UUID
4. Trigger a new live trace — it should appear at the top of the list (newest)
5. Check browser console for no errors
  </verify>
  <done>
Every trace object has a numeric `created_ts` field. Traces from IDB hydration and JSON import are sorted by created_ts before Map insertion, producing deterministic newest-first sidebar order. Exported JSON includes created_ts so round-trip import preserves order. Legacy records without created_ts gracefully fall back to started_at.
  </done>
</task>

</tasks>

<verification>
- Hydrated traces from IDB render newest-first in sidebar
- Imported traces render newest-first in sidebar
- Live traces appear at top (newest position) when they arrive
- Exported JSON includes `created_ts` field on each trace
- Re-importing exported traces preserves original order
- No console errors during any of the above flows
</verification>

<success_criteria>
Trace sidebar ordering is deterministic and chronological (newest-first) across all three trace sources: live bus events, IDB hydration, and JSON import.
</success_criteria>

<output>
After completion, create `.planning/quick/19-sort-traces-by-timestamp-desc-add-timest/19-SUMMARY.md`
</output>
