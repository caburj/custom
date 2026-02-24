---
phase: quick-36
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/detail/loop_detail.js
  - ai_debug/static/src/app/detail/loop_detail.xml
  - ai_debug/static/src/app/db.js
autonomous: true
requirements: [QUICK-36]

must_haves:
  truths:
    - "No client-side Date.now() or new Date() timestamps are created for trace timing purposes"
    - "The live timer chip in loop_detail header no longer displays a JS-derived elapsed time"
    - "Dead code (getIterationDuration, _formatDuration on AiDebugApp) is fully removed"
    - "Sidebar trace ordering still works correctly (newest-first) using created_ts"
    - "IDB serialization/hydration still round-trips cleanly without the removed fields"
  artifacts:
    - path: "ai_debug/static/src/app/app.js"
      provides: "Trace store without client-derived timestamps"
    - path: "ai_debug/static/src/app/detail/loop_detail.js"
      provides: "LoopDetail without timer mechanism"
    - path: "ai_debug/static/src/app/detail/loop_detail.xml"
      provides: "LoopDetail header without live timer chip"
    - path: "ai_debug/static/src/app/db.js"
      provides: "Serializer without started_at/ended_at/receivedAt fields"
  key_links:
    - from: "ai_debug/static/src/app/app.js"
      to: "ai_debug/static/src/app/db.js"
      via: "serializeTrace still produces valid IDB records"
      pattern: "serializeTrace"
    - from: "ai_debug/static/src/app/app.js"
      to: "sidebar sort order"
      via: "created_ts retained for sorting"
      pattern: "created_ts"
---

<objective>
Remove all client-side JS-derived duration values and unused client timestamps from the ai-debug UI. The server now provides real `duration_ms` on both iterations and traces, making client-derived timing redundant and misleading.

Purpose: Eliminate inaccurate client-side timing that diverges from actual server-measured durations. Clean up dead code paths that were superseded by server-provided metrics in Phase 17/quick-35.

Output: Cleaner app.js, loop_detail.js, loop_detail.xml, and db.js with no client-derived timing artifacts.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/detail/loop_detail.js
@ai_debug/static/src/app/detail/loop_detail.xml
@ai_debug/static/src/app/db.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Remove client timestamps and dead duration code from app.js</name>
  <files>ai_debug/static/src/app/app.js</files>
  <action>
    Remove the following client-side timestamp assignments and dead code from app.js:

    1. **`_placeTrace()` (line ~426):** Remove `started_at: new Date()` and `ended_at: null` from the trace object literal. Keep `created_ts: Date.now()` -- this is used for sidebar sorting (newest-first) and is NOT a displayed duration value. It serves as a monotonic ordering key.

    2. **`_onLoopEnd` handler (line ~292):** Remove `trace.ended_at = new Date()`. Keep `trace.duration_ms = payload.duration_ms` (server-provided).

    3. **`_onIteration` handler (line ~194):** Remove `receivedAt: new Date()` from the iteration object literal.

    4. **`getIterationDuration()` method (lines ~772-794):** Delete entirely. This is dead code -- never called from any template or other method. It computed durations from client-side `receivedAt` timestamps.

    5. **`_formatDuration()` method (lines ~796-802):** Delete entirely. Only called by `getIterationDuration()`, which is itself dead code. Note: the centralized `formatDuration` from `./format_metrics` is the canonical formatter used by templates.

    6. **`hydrateTrace()` function (line ~75-76):** Remove the `started_at` and `ended_at` Date reconstruction lines. Remove the fallback in `created_ts` that uses `started_at` (line ~77) -- simplify to just `created_ts: plain.created_ts || plain.storedAt || 0` (use `storedAt` as fallback since it was always written by db.js as `Date.now()`).

    7. **`hydrateTrace()` inner loop (line ~60):** Remove `receivedAt: iter.receivedAt ? new Date(iter.receivedAt) : null` from the iteration hydration.

    8. **Sort comparators (lines ~319-321, ~1066-1067):** Simplify the sort fallbacks. Change from `(a.created_ts || new Date(a.started_at || 0).getTime())` to just `(a.created_ts || a.storedAt || 0)`. The `started_at` field no longer exists on traces.

    9. **Auto-select comparator (line ~344):** Already uses just `created_ts` -- no change needed.

    Do NOT remove `created_ts: Date.now()` from `_placeTrace()` -- it is the sort key, not a displayed duration.
    Do NOT touch `duration_ms` fields anywhere -- those are server-provided and correct.
  </action>
  <verify>
    grep -n "started_at\|ended_at\|receivedAt\|getIterationDuration\|_formatDuration" ai_debug/static/src/app/app.js
    Expected: zero matches. If any remain, the cleanup is incomplete.
  </verify>
  <done>
    app.js contains zero references to started_at, ended_at, receivedAt, getIterationDuration, or _formatDuration. The created_ts sort key is retained. Server-provided duration_ms fields are untouched.
  </done>
</task>

<task type="auto">
  <name>Task 2: Remove live timer from loop_detail.js and loop_detail.xml</name>
  <files>ai_debug/static/src/app/detail/loop_detail.js, ai_debug/static/src/app/detail/loop_detail.xml</files>
  <action>
    **In loop_detail.js:**

    1. Remove `this.timerRef = useRef("liveTimer")` (line ~25) and `this._timerInterval = null` (line ~26).

    2. Remove the `onMounted` block (lines ~28-32) that starts the timer for running traces.

    3. Remove the `onWillUnmount` block (lines ~34-36) that stops the timer.

    4. Remove the `onPatched` block (lines ~38-46) that manages timer start/stop on status transition.

    5. Remove `_startTimer()` method (lines ~94-98).

    6. Remove `_updateTimerDisplay()` method (lines ~100-104) -- this is the only place that computed `Date.now() - trace.started_at.getTime()`.

    7. Remove `_stopTimer()` method (lines ~106-111).

    8. Remove the `useRef` import from the OWL import line (only if no other useRef calls remain in the file).

    9. Remove the `onMounted`, `onWillUnmount`, `onPatched` imports from the OWL import line (only if no other usages remain in the file after timer removal).

    **In loop_detail.xml:**

    10. Remove the live timer `<span>` (lines ~11-13):
        ```xml
        <span t-if="props.trace.status === 'running'"
              class="ai-metric-chip ai-metric-chip--live"
              t-ref="liveTimer">0s</span>
        ```
        Replace with a simple running indicator that does NOT show a duration. Use:
        ```xml
        <span t-if="props.trace.status === 'running'"
              class="ai-metric-chip ai-metric-chip--live">running</span>
        ```
        This preserves the visual "running" state indication without any client-derived time.

    11. Keep the `t-elif="props.trace.duration_ms"` span intact -- it shows the server-provided total duration for completed traces.
  </action>
  <verify>
    grep -n "timerRef\|_timerInterval\|_startTimer\|_stopTimer\|_updateTimerDisplay\|Date.now\|started_at" ai_debug/static/src/app/detail/loop_detail.js
    Expected: zero matches.
    grep -n "t-ref=\"liveTimer\"\|0s" ai_debug/static/src/app/detail/loop_detail.xml
    Expected: zero matches (liveTimer ref removed, "0s" placeholder removed).
  </verify>
  <done>
    loop_detail.js has no timer mechanism, no Date.now() calls, no started_at references. loop_detail.xml shows "running" text for in-progress traces and server-provided duration_ms for completed traces. No client-derived duration is displayed anywhere.
  </done>
</task>

<task type="auto">
  <name>Task 3: Clean up db.js serialization of removed fields</name>
  <files>ai_debug/static/src/app/db.js</files>
  <action>
    In `serializeTrace()` function:

    1. Remove `started_at: trace.started_at` (line ~46). This field no longer exists on traces.

    2. Remove `ended_at: trace.ended_at` (line ~47). This field no longer exists on traces.

    3. In the iteration serialization (line ~63), remove `receivedAt: iter.receivedAt`. This field no longer exists on iterations.

    4. Keep `created_ts: trace.created_ts` (line ~41) -- still used for sort ordering.

    5. Keep `storedAt: Date.now()` (line ~40) -- this is the IDB write timestamp, not a trace timing value. It also serves as the hydration fallback for created_ts on legacy records.

    6. Keep `duration_ms: trace.duration_ms` (line ~48) -- server-provided.

    Note on backward compatibility: Old IDB records that have started_at/ended_at/receivedAt will still load fine -- hydrateTrace() uses spread (...plain) so extra fields are harmless; we just stopped reading/writing them.
  </action>
  <verify>
    grep -n "started_at\|ended_at\|receivedAt" ai_debug/static/src/app/db.js
    Expected: zero matches. Only created_ts, storedAt, and duration_ms remain as time-related fields.
  </verify>
  <done>
    db.js serializeTrace no longer writes started_at, ended_at, or receivedAt. IDB records contain only server-provided timing (duration_ms) and ordering keys (created_ts, storedAt).
  </done>
</task>

</tasks>

<verification>
After all tasks complete:

1. `grep -rn "started_at\|ended_at\|receivedAt\|getIterationDuration\|_formatDuration\|_startTimer\|_stopTimer\|_updateTimerDisplay" ai_debug/static/src/app/` should return zero matches across all files.

2. `grep -n "created_ts\|duration_ms" ai_debug/static/src/app/app.js` should still show the server-provided duration_ms fields and created_ts sort key -- these are intentionally retained.

3. `grep -n "Date.now()" ai_debug/static/src/app/app.js` should show only `created_ts: Date.now()` in _placeTrace -- no other client timestamp creation.

4. `grep -n "Date.now()" ai_debug/static/src/app/db.js` should show only `storedAt: Date.now()` -- the IDB write timestamp.

5. `grep -n "new Date()" ai_debug/static/src/app/app.js` should return zero matches -- no client Date objects created for trace timing.
</verification>

<success_criteria>
- Zero client-derived duration values displayed in the UI
- Live timer chip replaced with static "running" text label
- Dead code (getIterationDuration, _formatDuration, timer methods) fully removed
- started_at, ended_at, receivedAt fields removed from trace/iteration creation, serialization, and hydration
- created_ts sort key preserved (ordering still works)
- Server-provided duration_ms untouched throughout
- No JS errors on trace lifecycle (start, iteration, end, hydration from IDB, import)
</success_criteria>

<output>
After completion, create `.planning/quick/36-remove-client-side-js-derived-duration-v/36-SUMMARY.md`
</output>
