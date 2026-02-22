---
phase: quick-25
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/models/ai_session.py
  - ai_debug/static/src/app/app.js
  - ai_debug/static/src/app/detail/tc_detail.xml
  - ai_debug/static/src/app/detail/tc_detail.js
autonomous: true
requirements: [CONFIRM-01]

must_haves:
  truths:
    - "When a tool triggers confirmation, a tool_call bus event is emitted with triggered_confirmation=True and the confirmation_message"
    - "The Confirmation Info tab shows the HTML confirmation message when the tool triggered confirmation"
    - "The Confirmation Info tab shows 'No confirmation requested' when no confirmation was triggered"
    - "The Confirmation Info tab is only visible when triggered_confirmation is true"
  artifacts:
    - path: "ai_debug/models/ai_session.py"
      provides: "Detection of tool_confirmation_request items and emission of tool_call events with confirmation fields"
      contains: "tool_confirmation_request"
    - path: "ai_debug/static/src/app/app.js"
      provides: "Storage of triggered_confirmation and confirmation_message fields from bus payload"
      contains: "triggered_confirmation"
    - path: "ai_debug/static/src/app/detail/tc_detail.xml"
      provides: "Confirmation Info tab with conditional content and visibility"
      contains: "confirmation_message"
    - path: "ai_debug/static/src/app/detail/tc_detail.js"
      provides: "hasConfirmation getter for template conditional"
      contains: "hasConfirmation"
  key_links:
    - from: "ai_debug/models/ai_session.py"
      to: "bus event"
      via: "_ai_debug_bus_send('tool_call', ...) with triggered_confirmation and confirmation_message"
      pattern: "triggered_confirmation.*True"
    - from: "ai_debug/static/src/app/app.js"
      to: "ai_debug/static/src/app/detail/tc_detail.xml"
      via: "toolCall prop passes triggered_confirmation and confirmation_message to ToolCallDetail"
      pattern: "triggered_confirmation"
    - from: "ai_debug/static/src/app/detail/tc_detail.js"
      to: "ai_debug/static/src/app/detail/tc_detail.xml"
      via: "hasConfirmation getter drives isVisible and content rendering"
      pattern: "hasConfirmation"
---

<objective>
Implement the Confirmation Info tab in the ai_debug tool call detail panel. Currently the tab shows a placeholder; after this task it will display the actual confirmation message when a tool triggers user confirmation, and hide entirely when no confirmation was requested.

Purpose: Complete the confirmation observability story -- users can see exactly what confirmation message was shown and which tool triggered it.
Output: Backend captures confirmation events, frontend stores and renders confirmation data in the tab.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/models/ai_session.py
@ai_debug/static/src/app/app.js
@ai_debug/static/src/app/detail/tc_detail.xml
@ai_debug/static/src/app/detail/tc_detail.js
</context>

<tasks>

<task type="auto">
  <name>Task 1: Backend -- detect confirmation events and emit enriched tool_call bus events</name>
  <files>ai_debug/models/ai_session.py</files>
  <action>
In `_handle_tool_calls`, modify the instrumentation loop that iterates over `super()._handle_tool_calls(...)` items.

**Step 1: Build a tool_calls_by_id lookup** before the `for item in super()...` loop. This maps `call_id` to the original tool call dict so we can look up `tool_name` and `args` when we see a confirmation event (which only carries `call_id`):

```python
tool_calls_by_id = {tc['call_id']: tc for tc in tool_calls}
```

Place this right after the `_debug_ctx` early-return guard (after line 275), before the `for item in super()...` loop.

**Step 2: Add an `elif` branch** inside the `for item in super()...` loop (after the existing `if tool_results := item.get('tool_results'):` block) to detect `tool_confirmation_request` items:

```python
elif confirmation := item.get('tool_confirmation_request'):
    call_id = confirmation.get('call_id')
    originating_tc = tool_calls_by_id.get(call_id, {})
    _debug_ctx['tool_call_count'] += 1

    self._ai_debug_bus_send('tool_call', {
        'type': 'tool_call',
        'trace_id': _debug_ctx['trace_id'],
        'iteration_id': _debug_ctx['iteration_id'],
        'tool_call_id': uuid.uuid4().hex,
        'tool_name': originating_tc.get('name', 'unknown'),
        'call_id': call_id,
        'args': originating_tc.get('args', {}),
        'result': None,
        'success': None,
        'error': None,
        'triggered_confirmation': True,
        'confirmation_message': confirmation.get('message', ''),
    })
```

This branch fires when enterprise's `_handle_tool_calls` yields `{'tool_confirmation_request': {...}}`. We look up the originating tool call to get `tool_name` and `args`, then emit a `tool_call` bus event with `result=None`, `success=None` (pending), and the two new confirmation fields.

The existing `yield item` at the bottom of the loop already passes the item through to the caller, so no change needed there.
  </action>
  <verify>
Verify the file parses correctly:

```bash
python3 -c "import ast; ast.parse(open('ai_debug/models/ai_session.py').read()); print('OK')"
```

Manually verify:
- `tool_calls_by_id` dict comprehension is present before the loop
- `elif confirmation := item.get('tool_confirmation_request'):` branch exists
- The bus event includes `triggered_confirmation: True` and `confirmation_message`
- The `yield item` at the bottom is unchanged (still passes all items through)
  </verify>
  <done>
When enterprise's `_handle_tool_calls` yields a `tool_confirmation_request` item, ai_debug emits a `tool_call` bus event with `triggered_confirmation=True`, `confirmation_message` containing the HTML message, `result=None`, and `success=None`. Normal tool results continue to work as before (no `triggered_confirmation` field).
  </done>
</task>

<task type="auto">
  <name>Task 2: Frontend -- store confirmation fields and render in Confirmation Info tab</name>
  <files>ai_debug/static/src/app/app.js, ai_debug/static/src/app/detail/tc_detail.xml, ai_debug/static/src/app/detail/tc_detail.js</files>
  <action>
**app.js -- `_onToolCall` handler (around line 152):**

Add two new fields to the object stored in `iteration.toolCalls.set(...)`:

```javascript
triggered_confirmation: payload.triggered_confirmation || false,
confirmation_message: payload.confirmation_message || null,
```

Add these after the `call_id` line (line 163). Also in the `hydrateTrace` function, these fields will automatically round-trip through the existing spread (`...tc`) in the hydration loop (line 29), so no changes needed there.

**tc_detail.js -- add `hasConfirmation` getter:**

Add a getter after the existing `resultIsLong` getter:

```javascript
get hasConfirmation() {
    return !!this.props.toolCall.triggered_confirmation;
}
```

**tc_detail.xml -- replace the Confirmation Info tab placeholder:**

Replace the entire `<t t-set-slot="confirmation" ...>` block (lines 54-63) with:

```xml
<t t-set-slot="confirmation" title="'Confirmation Info'" isVisible="hasConfirmation">
    <div class="ai-detail-section">
        <div class="ai-detail-section-header">
            <span>Confirmation Info</span>
            <span class="badge text-bg-warning ms-2">Confirmation Required</span>
        </div>
        <div class="ai-detail-confirmation-content p-3" t-out="props.toolCall.confirmation_message"/>
    </div>
</t>
```

Key details:
- `isVisible="hasConfirmation"` -- tab only appears when `triggered_confirmation` is true. This uses the `hasConfirmation` getter added to tc_detail.js.
- The "Confirmation Required" badge uses Bootstrap's `text-bg-warning` class (already available in Odoo).
- `t-out` renders the HTML confirmation message (it comes from `make_batch_update_preview` which produces safe HTML). Using `t-out` instead of `t-esc` so the HTML renders properly.
- No "No confirmation requested" fallback needed since the tab is hidden when there's no confirmation.

Also update the header badge area (lines 9-10) to handle the `success === null` case for confirmation-pending tool calls. Currently it shows "Success" or "Failed" based on `props.toolCall.success`. Add a third condition:

Replace lines 9-10:
```xml
<span t-if="props.toolCall.success === null" class="ai-detail-meta" style="color: var(--warning);">Pending</span>
<span t-elif="props.toolCall.success" class="ai-detail-meta success">Success</span>
<span t-else="" class="ai-detail-meta error">Failed</span>
```

This shows "Pending" (in warning color) when `success` is `null` (confirmation-triggered tool calls), "Success" when true, and "Failed" when false.
  </action>
  <verify>
Check JS syntax:
```bash
node -e "require('fs').readFileSync('ai_debug/static/src/app/app.js', 'utf8')" && echo "app.js OK"
node -e "require('fs').readFileSync('ai_debug/static/src/app/detail/tc_detail.js', 'utf8')" && echo "tc_detail.js OK"
```

Check XML well-formedness:
```bash
python3 -c "import xml.etree.ElementTree as ET; ET.parse('ai_debug/static/src/app/detail/tc_detail.xml'); print('XML OK')"
```

Verify in the files:
- app.js `_onToolCall` stores `triggered_confirmation` and `confirmation_message`
- tc_detail.js has `hasConfirmation` getter
- tc_detail.xml confirmation tab uses `isVisible="hasConfirmation"` and renders with `t-out`
- tc_detail.xml header handles `success === null` with "Pending" badge
  </verify>
  <done>
The `_onToolCall` handler stores the two new confirmation fields. The Confirmation Info tab is only visible when `triggered_confirmation` is true, showing a "Confirmation Required" badge and the HTML confirmation message. Tool calls with `success=null` show a "Pending" status badge in the header instead of "Success" or "Failed". When no confirmation was triggered, the tab is completely hidden.
  </done>
</task>

</tasks>

<verification>
1. Python file parses without syntax errors
2. JS files are valid syntax
3. XML template is well-formed
4. `triggered_confirmation` field flows from backend bus event through app.js storage to tc_detail.xml rendering
5. `confirmation_message` HTML is rendered via `t-out` in the Confirmation Info tab
6. Tab visibility is gated on `hasConfirmation` getter
7. Header badge handles the `success === null` (pending) state
</verification>

<success_criteria>
- Backend emits `tool_call` bus events with `triggered_confirmation` and `confirmation_message` when enterprise yields `tool_confirmation_request`
- Frontend stores both fields and renders the Confirmation Info tab conditionally
- Tab shows HTML confirmation message with a warning badge when present
- Tab is hidden when no confirmation was triggered
- Existing tool_results instrumentation is unchanged
</success_criteria>

<output>
After completion, create `.planning/quick/25-implement-confirmation-info-tab-in-ai-de/25-SUMMARY.md`
</output>
