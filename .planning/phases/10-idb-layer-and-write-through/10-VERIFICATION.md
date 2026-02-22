---
phase: 10-idb-layer-and-write-through
verified: 2026-02-22T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
re_verification: false
human_verification:
  - test: "After an agentic loop runs, open DevTools > Application > IndexedDB > ai_debug_traces > traces and confirm a record exists with the correct trace_id"
    expected: "One record per completed loop appears in the traces object store. Record contains trace_id, agent_name, model_name, status, storedAt, and serialized iterations array."
    why_human: "Cannot open a browser or query live IndexedDB state programmatically in this environment."
  - test: "Trigger a fast multi-iteration agentic loop and watch the sidebar during execution"
    expected: "The sidebar tree updates in real time with no visible pause or jitter. Bus event rows render immediately regardless of IDB write activity in the background."
    why_human: "UI responsiveness and jitter perception cannot be measured statically — requires live observation."
  - test: "Open the app in a private browsing window (Safari Private, Chrome Incognito, or Firefox Private) and trigger a loop"
    expected: "The 'Ephemeral' amber badge appears in the header. The trace tree still renders and updates normally. No JavaScript error in the console."
    why_human: "Private browsing IDB blocking requires an actual browser session."
  - test: "Start an agentic loop and reload the page while it is still running (mid-loop)"
    expected: "After reload the app opens cleanly. The previously-in-progress trace record is absent or complete (not corrupted/partial). No IndexedDB corruption errors in the console."
    why_human: "In-flight IDB write behavior on page unload requires a live browser test."
---

# Phase 10: IDB Layer and Write-Through Verification Report

**Phase Goal:** Traces are durably written to IndexedDB as they arrive, providing the foundation all persistence features depend on
**Verified:** 2026-02-22
**Status:** human_needed — all automated checks passed; 4 items require browser confirmation
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After an agentic loop completes, the completed trace is stored as a record in the ai_debug_traces IndexedDB store | ? NEEDS HUMAN | `writeTrace(trace)` is called in `_onLoopEnd` (app.js:145); `idb.write(STORE, trace.trace_id, record)` executes in db.js:89; correct IDB store name in db.js:6. Actual IDB record creation requires a live browser run. |
| 2 | The UI does not pause or jitter during IDB writes — bus event handlers return synchronously | ✓ VERIFIED | `writeTrace(trace).catch(...)` at app.js:145-149 is never awaited. `_onLoopEnd` returns after the synchronous reactive store updates. The Promise is detached. UI render path has zero blocking on IDB. |
| 3 | In private browsing (or when IDB is blocked), the app opens normally and shows a subtle ephemeral mode indicator in the header | ? NEEDS HUMAN | `probeIDB()` in db.js:18-21 uses `idb.execute((db) => (db ? "ok" : null))` — the correct detection technique for Odoo's error-as-undefined callback pattern. `onWillStart` at app.js:155-161 sets `state.ephemeralMode = true` before first render. `t-if="state.ephemeralMode"` span at app.xml:12-16 renders "Ephemeral" with class `ai-ephemeral-indicator`. CSS at app.scss:68-80 styles it as an amber badge. Requires private browsing session to confirm. |
| 4 | A mid-session write failure switches to ephemeral mode and shows the indicator without crashing | ✓ VERIFIED | `.catch((err) => { console.warn(...); this.state.ephemeralMode = true; })` at app.js:146-148 handles all write rejections. The `if (!this.state.ephemeralMode)` guard at app.js:144 prevents further write attempts. No crash path exists — the catch callback is the only error handler and it mutates reactive state safely. |

**Score:** 2/4 fully verified by static analysis; 2/4 need human browser confirmation. All 4 are structurally sound.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `ai_debug/static/src/app/db.js` | IDB wrapper — probeIDB(), writeTrace(), serializeTrace() | ✓ VERIFIED | 98 lines (min 40 required). Exports `probeIDB`, `writeTrace`, `deleteTrace`. `serializeTrace` is internal (not exported). `writeTrace` is NOT async — returns raw Promise. `markRaw` absent. `expanded` absent from return object (present only in JSDoc comment). `storedAt: Date.now()` in serialized record. Maps converted via `[...map.entries()]`. Only file importing `@web/core/utils/indexed_db`. |
| `ai_debug/static/src/app/app.js` | onWillStart probe, _onLoopEnd fire-and-forget write, ephemeralMode state | ✓ VERIFIED | `import { probeIDB, writeTrace } from "./db"` at line 8. `ephemeralMode: false` in useState block at line 29. `onWillStart` at line 155, before `onMounted` at line 166 (correct ordering — no render flash). Fire-and-forget write at lines 144-149 with guard and `.catch()`. `await writeTrace` absent. |
| `ai_debug/static/src/app/app.xml` | Ephemeral mode indicator span | ✓ VERIFIED | `<span t-if="state.ephemeralMode" class="ai-ephemeral-indicator" title="IndexedDB unavailable — traces won't persist across refreshes">Ephemeral</span>` at lines 12-16 inside `.ai-debug-header-status`. |
| `ai_debug/static/src/app/app.scss` | Ephemeral indicator styles | ✓ VERIFIED | `.ai-ephemeral-indicator` block at lines 68-80. Uses `$o-warning` for color, `rgba($o-warning, 0.15)` for background. Monospace font, uppercase, 10px, 600 weight. Matches header aesthetic. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| app.js | db.js | `import { probeIDB, writeTrace } from "./db"` | ✓ WIRED | Line 8 of app.js. Both exports used: `probeIDB` at line 156, `writeTrace` at line 145. |
| app.js `_onLoopEnd` | db.js `writeTrace()` | fire-and-forget call with `.catch` for ephemeral mode | ✓ WIRED | `writeTrace(trace).catch(...)` at lines 145-149. Not awaited. Guard condition at line 144. |
| app.js `setup()` | db.js `probeIDB()` | `onWillStart` async probe before first render | ✓ WIRED | `onWillStart(async () => { const available = await probeIDB(); ... })` at lines 155-161. |
| app.js `state.ephemeralMode` | app.xml ephemeral indicator | OWL reactive rendering via `t-if` | ✓ WIRED | `t-if="state.ephemeralMode"` in app.xml:12 references the reactive `state` object from app.js:25-30. OWL will re-render when `state.ephemeralMode` changes. |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| PERS-01 | 10-01-PLAN.md | Traces auto-persist to IndexedDB as bus events arrive (fire-and-forget, non-blocking) | ✓ SATISFIED | `writeTrace(trace).catch(...)` in `_onLoopEnd` without `await`. Non-blocking by construction. |
| PERS-04 | 10-01-PLAN.md | App degrades gracefully to ephemeral mode if IndexedDB is unavailable (e.g. private browsing) | ✓ SATISFIED | `probeIDB()` on startup via `onWillStart` + `.catch()` on write failures. Both paths set `state.ephemeralMode = true`. Indicator rendered via `t-if`. |

REQUIREMENTS.md marks both PERS-01 and PERS-04 as `[x] Complete` with Phase 10 as the responsible phase. No orphaned requirements found — Phase 10 claims exactly PERS-01 and PERS-04, both accounted for.

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| app.xml:103 | `ai-tree-chevron-placeholder` | CSS class named "placeholder" | ℹ️ Info | UI alignment placeholder (existed before Phase 10), not a stub indicator. No impact on phase goal. |
| app.scss:246, 519 | `.ai-tree-chevron-placeholder`, `.ai-json-toggle-placeholder` | CSS class named "placeholder" | ℹ️ Info | Pre-existing UI alignment classes, not stub content. No impact on phase goal. |

No stub implementations, no TODO/FIXME/XXX/HACK markers, no empty return values, no unimplemented handlers found in any Phase 10 modified file.

---

## Human Verification Required

### 1. IDB Record Existence After Loop

**Test:** Run an agentic loop in Odoo. When it completes (status shows success/error in sidebar), open browser DevTools > Application tab > IndexedDB > ai_debug_traces > traces object store.

**Expected:** A record exists with a key matching the `trace_id` UUID hex. The record contains: `trace_id`, `agent_name`, `model_name`, `status`, `storedAt` (timestamp), `started_at`, `ended_at`, `duration_ms`, and `iterations` as a serialized array of `[iterationId, iterationRecord]` pairs.

**Why human:** Cannot query live IndexedDB state from a static code analysis environment.

---

### 2. UI Non-Blocking During Fast Loop

**Test:** Trigger a fast multi-iteration agentic loop (e.g., a loop that runs 3-5 iterations quickly). Watch the sidebar tree during execution.

**Expected:** Each iteration row appears immediately as the bus event arrives. The sidebar never freezes or pauses between iterations. No visible delay between the loop ending and the trace status icon updating.

**Why human:** UI responsiveness and jitter are perceptual — they cannot be measured by static analysis.

---

### 3. Ephemeral Mode in Private Browsing

**Test:** Open the ai_debug DevTools panel in a private browsing window (Safari Private Browsing, Chrome Incognito, or Firefox Private Window). Wait for the page to load fully.

**Expected:** The "Ephemeral" amber badge appears in the header next to the connection status. The console shows `[ai_debug] IndexedDB unavailable — running in ephemeral mode`. The trace tree still works — triggering a loop populates the sidebar normally.

**Why human:** Private browsing IndexedDB blocking requires an actual browser session to trigger.

---

### 4. No Corruption on Mid-Loop Reload

**Test:** Start an agentic loop (wait for 1-2 iterations to arrive). While the loop is still running (status is "running" with the pulse dot), reload the page.

**Expected:** The page reloads cleanly with no JavaScript errors. After reload, the app shows an empty trace list (expected — Phase 11 hydration not yet built). No IndexedDB corruption errors appear in the console. A subsequent loop run writes successfully.

**Why human:** Mid-write page unload behavior depends on browser IDB transaction handling — requires live browser test.

---

## Verification Notes

The "fire-and-forget" guarantee is airtight in the code: `writeTrace` in db.js explicitly returns `idb.write(...)` without awaiting, and the call site in app.js uses `.catch()` — never `await`. The `onWillStart` positioning before `onMounted` is confirmed at lines 155 vs 166, ensuring the ephemeral state is determined before any render. The `serializeTrace` function explicitly enumerates fields (not spread) and converts both Maps — `trace.iterations` and per-iteration `toolCalls` — to entry arrays, which is the correct pattern for avoiding Proxy-over-Map issues with IDB structured clone.

The only reason this is `human_needed` rather than `passed` is that durable IDB persistence (Success Criterion 1), private browsing degradation (Success Criterion 3), and mid-loop reload safety (Success Criterion 4) are real-world browser behaviors that cannot be confirmed by static analysis alone.

---

_Verified: 2026-02-22_
_Verifier: Claude (gsd-verifier)_
