---
phase: 15-data-integrity-fixes
verified: 2026-02-24T10:00:00Z
status: human_needed
score: 5/5 must-haves verified
human_verification:
  - test: "Export cascade includes subagent descendants in JSON file"
    expected: "Exporting a checked root trace with subagent children produces a JSON file containing the root trace plus all descendant traces. Re-importing that file into an empty session reconstructs the full nested hierarchy in the sidebar."
    why_human: "exportSelected() triggers a browser file download; the content of the produced JSON and the sidebar re-render after import cannot be verified programmatically from source alone."
  - test: "Orphan traces render at root level after page refresh"
    expected: "After deleting a parent trace from IDB (or otherwise leaving a child trace whose parent_trace_id points to a missing trace), a page refresh nulls out the parent fields and the orphan appears as a root-level entry in the sidebar — not hidden."
    why_human: "Requires real IDB state with a deliberately orphaned trace; no automated mechanism can simulate IDB deletion and observe the post-refresh sidebar render."
  - test: "Auto-select never picks a subagent child trace on page load"
    expected: "After page refresh with a session containing both root traces and subagent child traces, the detail panel auto-populates with a root trace (most recently created by created_ts), never with a child trace."
    why_human: "Runtime OWL reactive state and the detail panel render require a live browser session to observe."
---

# Phase 15: Data Integrity Fixes Verification Report

**Phase Goal:** Export cascades to subagent descendants; orphan traces excluded from auto-selection
**Verified:** 2026-02-24T10:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Exporting a root trace with subagent descendants includes all descendant traces in the JSON file | ? HUMAN | `exportSelected()` at lines 849-876 calls `_collectDescendantIds(id)` for each checked id, deduplicates with `new Set(allIds)`, and maps `uniqueIds` through `serializeTrace()`. Code path is complete and substantive. Actual file output requires browser verification. |
| 2 | Re-importing the exported JSON file reconstructs the full nested subagent hierarchy | ? HUMAN | `_applyImport()` at lines 977-994 sorts by `created_ts`, calls `hydrateTrace(record)` for each record, and writes to `this.traces`. `hydrateTrace()` uses `...plain` spread (line 39) restoring `parent_trace_id`, `parent_tool_call_id`, `session_id`. Sidebar rendering via `sidebarNodes` uses `!t.parent_trace_id` root detection (line 622). Logic is verified; visual re-render requires browser. |
| 3 | After page refresh, orphan traces whose parent_trace_id points to a non-existent trace are promoted to root level | ✓ VERIFIED | Lines 284-288: second pass iterates `this.traces.values()`, checks `trace.parent_trace_id && !this.traces.has(trace.parent_trace_id)`, and nulls both `parent_trace_id` and `parent_tool_call_id`. Pattern matches PLAN key_link exactly. |
| 4 | After page refresh, auto-select picks the newest root trace — never a subagent child trace | ✓ VERIFIED | Lines 293-305: `bestTrace` logic iterates traces, guards with `if (!trace.parent_trace_id)`, compares `trace.created_ts` to pick newest, then sets `this.state.selectedId = bestTrace.trace_id`. No `at(-1)` fallback remains. |
| 5 | serializeTrace()/hydrateTrace() roundtrip preserves parent_trace_id, parent_tool_call_id, and session_id | ✓ VERIFIED | `db.js` lines 52-54 explicitly write all three fields in `serializeTrace()`. `hydrateTrace()` uses `...plain` spread (app.js line 39) which restores every plain field including all three. |

**Score:** 5/5 truths verified (3 fully automated, 2 pending human confirmation of runtime output)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `ai_debug/static/src/app/app.js` | exportSelected() with descendant cascade, onWillStart with two-pass hydration and root-only auto-select | ✓ VERIFIED | File exists (995 lines). Contains `_collectDescendantIds` cascade in `exportSelected()` (lines 849-876), second-pass orphan loop (lines 279-289), and root-only `bestTrace` auto-select (lines 290-306). All substantive — no stubs. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `exportSelected()` | `_collectDescendantIds()` | descendant cascade before serialization | ✓ WIRED | Line 856: `allIds.push(...this._collectDescendantIds(id))` inside `exportSelected()` for-loop. `uniqueIds` (line 858) used in the subsequent `.map()` (line 861). Both call and result usage confirmed. |
| `onWillStart` second pass | `this.traces.has()` | orphan detection loop over loaded traces | ✓ WIRED | Line 284-285: `for (const trace of this.traces.values())` followed by `if (trace.parent_trace_id && !this.traces.has(trace.parent_trace_id))`. Pattern matches PLAN frontmatter exactly. |
| auto-select logic | root trace filter | filter to traces without parent_trace_id before selecting | ✓ WIRED | Line 296: `if (!trace.parent_trace_id)` inside the `bestTrace` selection loop (lines 294-301). Auto-select cannot reach subagent child traces. |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DATA-01 | 15-01-PLAN.md | `serializeTrace()` and `hydrateTrace()` preserve parent linkage fields (`parent_trace_id`, `parent_tool_call_id`) across IDB roundtrip | ✓ SATISFIED | db.js lines 52-54 explicitly serialize all three fields; hydrateTrace() `...plain` spread (app.js line 39) restores them. Verified in commit `a7ac163` (Phase 14 Plan 01). No code change needed in Phase 15. |
| DATA-02 | 15-01-PLAN.md | JSON export/import preserves subagent hierarchy — imported traces reconstruct parent-child nesting correctly | ✓ SATISFIED | `exportSelected()` cascade via `_collectDescendantIds()` ensures all descendant traces are included in the export. `_applyImport()` + `hydrateTrace()` preserves linkage on import. Committed in `a1b886a`. |
| DATA-03 | 15-01-PLAN.md | Two-pass IDB hydration: first pass loads all traces, second pass validates parent pointers (handles random IDB record ordering) | ✓ SATISFIED | `onWillStart` two-pass hydration implemented (lines 276-289). Orphan promotion nulls `parent_trace_id`/`parent_tool_call_id`. Root-only auto-select via `bestTrace` pattern (lines 293-305). Committed in `1132803`. |

**Orphaned requirements check:** REQUIREMENTS.md maps DATA-01, DATA-02, DATA-03 to Phase 15 — all three appear in 15-01-PLAN.md `requirements` field. No orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| — | — | — | — | — |

No TODO/FIXME/HACK/PLACEHOLDER comments found. No stub return patterns in the modified functions. No console.log-only implementations. No empty handlers.

### Human Verification Required

#### 1. Export produces correct JSON with descendant traces

**Test:** In the debug UI, create or load a session with a root trace that has at least one subagent child trace visible in the sidebar. Check the root trace's checkbox. Click Export. Open the downloaded JSON file.
**Expected:** The JSON array contains records for both the root trace and all of its subagent descendant traces. Each descendant record has `parent_trace_id` set to the root trace's `trace_id`.
**Why human:** Browser file download and JSON file content cannot be asserted from source inspection alone. The cascade code is correct, but the actual produced output requires runtime confirmation.

#### 2. Re-import reconstructs nested hierarchy

**Test:** Using the JSON file from test 1, clear the current session (or use a fresh browser tab with empty IDB). Use the Import button to load the file.
**Expected:** The sidebar shows the root trace with its subagent children nested beneath it, in the same hierarchy as before export. The detail panel renders correctly for each selected item.
**Why human:** OWL reactive re-render and sidebar tree structure after import require a live browser to observe.

#### 3. Orphan promotion on page refresh

**Test:** Manually delete a parent trace from IDB (e.g., via browser DevTools > Application > IndexedDB), leaving its child trace intact. Refresh the page.
**Expected:** The child trace (previously a subagent, now an orphan) appears as a root-level entry in the sidebar. It is selectable and shows its detail content.
**Why human:** Requires deliberate IDB state manipulation and post-refresh observation of the sidebar render.

#### 4. Auto-select picks root trace, not child trace

**Test:** Load or create a session with both root traces and subagent child traces in IDB. Refresh the page without a previously selected trace (or clear `selectedId` from state).
**Expected:** The detail panel auto-populates with a root trace — specifically the one with the highest `created_ts` among root traces. A subagent child trace is never auto-selected.
**Why human:** Requires observing the detail panel's initial state in a live browser session with specific IDB content.

### Gaps Summary

No gaps found in automated verification. All three must-have truths that can be verified programmatically are fully verified. The two truths relating to export file content and import sidebar rendering require runtime browser confirmation and are flagged for human verification only — there are no code deficiencies that would prevent them from working.

---

## Commit Verification

| Commit | Task | Files Changed | Verified |
|--------|------|---------------|---------|
| `a1b886a` | Task 1: Export cascade + DATA-01 verification | `ai_debug/static/src/app/app.js` (+9/-2) | Yes — commit exists, diff confirms cascade code |
| `1132803` | Task 2: Two-pass hydration + root-only auto-select | `ai_debug/static/src/app/app.js` (+26/-4) | Yes — commit exists, diff confirms both patterns |

---

_Verified: 2026-02-24T10:00:00Z_
_Verifier: Claude (gsd-verifier)_
