---
phase: 24-remove-state-diff
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/static/src/app/detail/state_diff.js
  - ai_debug/static/src/app/detail/state_diff.xml
  - ai_debug/static/src/app/detail/iter_detail.js
  - ai_debug/static/src/app/detail/iter_detail.xml
  - ai_debug/static/src/app/detail/tc_detail.js
  - ai_debug/static/src/app/detail/tc_detail.xml
  - ai_debug/models/ai_session.py
autonomous: true
requirements: [REMOVE-STATE-DIFF]

must_haves:
  truths:
    - "IterationDetail view has no State Diff tab"
    - "ToolCallDetail view has no State Diff tab"
    - "StateDiff component files no longer exist on disk"
    - "Python backend no longer sends state_before/state_after in tool_call bus events"
    - "The app loads without import errors (no dangling references to StateDiff)"
  artifacts:
    - path: "ai_debug/static/src/app/detail/state_diff.js"
      provides: "DELETED — must not exist"
    - path: "ai_debug/static/src/app/detail/state_diff.xml"
      provides: "DELETED — must not exist"
    - path: "ai_debug/static/src/app/detail/iter_detail.js"
      provides: "IterationDetail without StateDiff import or getters"
      not_contains: "StateDiff"
    - path: "ai_debug/static/src/app/detail/iter_detail.xml"
      provides: "IterationDetail template without State Diff tab"
      not_contains: "state_diff"
    - path: "ai_debug/static/src/app/detail/tc_detail.js"
      provides: "ToolCallDetail without StateDiff import or getters"
      not_contains: "StateDiff"
    - path: "ai_debug/static/src/app/detail/tc_detail.xml"
      provides: "ToolCallDetail template without State Diff tab"
      not_contains: "state_diff"
    - path: "ai_debug/models/ai_session.py"
      provides: "State capture commented out with explanatory note"
      not_contains: "'state_before': state_before_batch"
  key_links:
    - from: "iter_detail.js"
      to: "state_diff.js"
      via: "import removed — no dangling reference"
      pattern: "StateDiff"
    - from: "tc_detail.js"
      to: "state_diff.js"
      via: "import removed — no dangling reference"
      pattern: "StateDiff"
---

<objective>
Remove the StateDiff component, its tabs in IterationDetail and ToolCallDetail views, and comment out the backend state capture logic.

Purpose: No built-in Odoo AI tool modifies `tools_context['state']`, so the state diff is always empty. The tab wastes UI space and the deepcopy captures waste CPU cycles on every tool call.
Output: Cleaner detail views (2 tabs for iteration, 3 tabs for tool call), deleted component files, commented-out backend capture.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/static/src/app/detail/state_diff.js
@ai_debug/static/src/app/detail/state_diff.xml
@ai_debug/static/src/app/detail/iter_detail.js
@ai_debug/static/src/app/detail/iter_detail.xml
@ai_debug/static/src/app/detail/tc_detail.js
@ai_debug/static/src/app/detail/tc_detail.xml
@ai_debug/models/ai_session.py
</context>

<tasks>

<task type="auto">
  <name>Task 1: Delete StateDiff component and remove all frontend references</name>
  <files>
    ai_debug/static/src/app/detail/state_diff.js (DELETE)
    ai_debug/static/src/app/detail/state_diff.xml (DELETE)
    ai_debug/static/src/app/detail/iter_detail.js
    ai_debug/static/src/app/detail/iter_detail.xml
    ai_debug/static/src/app/detail/tc_detail.js
    ai_debug/static/src/app/detail/tc_detail.xml
  </files>
  <action>
    1. DELETE `ai_debug/static/src/app/detail/state_diff.js` entirely.
    2. DELETE `ai_debug/static/src/app/detail/state_diff.xml` entirely.

    3. Edit `iter_detail.js`:
       - Remove the import line: `import { StateDiff } from "./state_diff";` (line 8)
       - Remove `StateDiff` from the `static components` object (line 12), leaving: `{ Notebook, CopyButton, JsonTree }`
       - Remove the entire `stateBefore` getter (lines 40-44) and `stateAfter` getter (lines 46-50), including the comment on line 38-39.

    4. Edit `iter_detail.xml`:
       - Remove the entire State Diff tab slot block (lines 41-53), which is the `<t t-set-slot="state_diff" ...>` through its closing `</t>`.
       - The Notebook should have exactly 2 slots remaining: "messages" and "response".

    5. Edit `tc_detail.js`:
       - Remove the import line: `import { StateDiff } from "./state_diff";` (line 8)
       - Remove `StateDiff` from the `static components` object (line 12), leaving: `{ Notebook, CopyButton, JsonTree }`
       - Remove the `stateBefore` getter (lines 51-53) and `stateAfter` getter (lines 55-57).

    6. Edit `tc_detail.xml`:
       - Remove the entire State Diff tab slot block (lines 54-66), which is the `<t t-set-slot="state_diff" ...>` through its closing `</t>`.
       - The Notebook should have exactly 3 slots remaining: "arguments", "result", and "confirmation".

    No manifest changes needed — it uses glob patterns (`**/*.js`, `**/*.xml`) so deleting files is sufficient.
  </action>
  <verify>
    Run: `grep -r "StateDiff\|state_diff" ai_debug/static/src/app/detail/` — should return NO results.
    Run: `ls ai_debug/static/src/app/detail/state_diff*` — should fail (files deleted).
    Run: `grep -c "t-set-slot" ai_debug/static/src/app/detail/iter_detail.xml` — should be 2 (messages, response).
    Run: `grep -c "t-set-slot" ai_debug/static/src/app/detail/tc_detail.xml` — should be 3 (arguments, result, confirmation).
  </verify>
  <done>
    StateDiff component files deleted. No import, component registration, getter, or template reference to StateDiff remains in any frontend detail file. IterationDetail has 2 Notebook tabs, ToolCallDetail has 3 Notebook tabs.
  </done>
</task>

<task type="auto">
  <name>Task 2: Comment out state capture in Python backend</name>
  <files>
    ai_debug/models/ai_session.py
  </files>
  <action>
    Edit `_handle_tool_calls` in `ai_debug/models/ai_session.py`:

    1. Comment out the `state_before_batch` capture line (line 279):
       ```python
       # State capture disabled — no built-in Odoo AI tool modifies
       # tools_context['state'], so the diff is always empty.
       # state_before_batch = copy.deepcopy(tools_context.get('state') or {})
       ```

    2. Comment out the `state_after_batch` capture line (line 287):
       ```python
       # state_after_batch = copy.deepcopy(tools_context.get('state') or {})
       ```

    3. Remove `'state_before'` and `'state_after'` keys from the `tool_call` bus event dict (lines 311-312). Delete these two lines entirely:
       ```python
       'state_before': state_before_batch,
       'state_after': state_after_batch,
       ```

    4. Update the docstring of `_handle_tool_calls` (lines 258-267) to reflect the change. Replace the paragraph about "Captures state_before..." with:
       ```
       State capture (state_before/state_after via deepcopy) is disabled — no built-in
       Odoo AI tool modifies tools_context['state'], so the diff is always empty. The
       commented-out lines can be re-enabled if custom tools begin mutating state.
       ```

    5. Verify that `import copy` at the top of the file is still needed. Check if `copy.deepcopy` is used elsewhere (line 34 in `_ai_debug_state_snapshot`). It IS still used there, so keep the import.
  </action>
  <verify>
    Run: `grep "state_before_batch\|state_after_batch" ai_debug/models/ai_session.py` — should show only commented-out lines (starting with #).
    Run: `grep "'state_before'" ai_debug/models/ai_session.py` — should return nothing (removed from dict).
    Run: `grep "'state_after'" ai_debug/models/ai_session.py` — should return nothing (removed from dict).
    Run: `python3 -c "import ast; ast.parse(open('ai_debug/models/ai_session.py').read()); print('syntax OK')"` — confirms valid Python.
  </verify>
  <done>
    State capture deepcopy lines are commented out with an explanatory note. The tool_call bus event no longer includes state_before or state_after keys. The docstring explains why capture is disabled and how to re-enable it. Python file parses without syntax errors.
  </done>
</task>

</tasks>

<verification>
1. No dangling references: `grep -r "StateDiff\|state_diff" ai_debug/static/src/app/detail/` returns nothing.
2. Deleted files gone: `ls ai_debug/static/src/app/detail/state_diff*` fails.
3. Backend clean: `grep "'state_before'\|'state_after'" ai_debug/models/ai_session.py` returns nothing.
4. Python valid: `python3 -c "import ast; ast.parse(open('ai_debug/models/ai_session.py').read())"` succeeds.
5. Tab counts correct: iter_detail.xml has 2 t-set-slot, tc_detail.xml has 3 t-set-slot.
</verification>

<success_criteria>
- StateDiff component files (state_diff.js, state_diff.xml) deleted from disk
- IterationDetail shows exactly 2 tabs: Messages Sent, Raw Response
- ToolCallDetail shows exactly 3 tabs: Arguments, Result, Confirmation Info
- No JS import or component reference to StateDiff in any remaining file
- Python tool_call bus event omits state_before and state_after
- State capture deepcopy lines commented out with explanation
- All files parse/compile without errors
</success_criteria>

<output>
After completion, create `.planning/quick/24-remove-state-diff-tabs-and-associated-lo/24-SUMMARY.md`
</output>
