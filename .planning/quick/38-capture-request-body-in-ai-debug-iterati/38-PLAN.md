---
phase: quick-38
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/models/ai_provider_patch.py
  - ai_debug/models/ai_session.py
  - ai_debug/static/src/app/detail/iter_detail.js
  - ai_debug/static/src/app/detail/iter_detail.xml
autonomous: true
requirements: [QUICK-38]

must_haves:
  truths:
    - "Each iteration event contains the full HTTP request body sent to the LLM provider"
    - "The Request tab displays the request body as a collapsible JSON tree in the iteration detail view"
    - "Base64 binary data in request body messages is stripped before bus transmission"
  artifacts:
    - path: "ai_debug/models/ai_provider_patch.py"
      provides: "Thread-local stashing of request body"
      contains: "last_request_body"
    - path: "ai_debug/models/ai_session.py"
      provides: "request_body inclusion in iteration bus event"
      contains: "request_body"
    - path: "ai_debug/static/src/app/detail/iter_detail.js"
      provides: "requestJson getter for copy button"
      contains: "requestJson"
    - path: "ai_debug/static/src/app/detail/iter_detail.xml"
      provides: "Request tab in Notebook"
      contains: "Request"
  key_links:
    - from: "ai_debug/models/ai_provider_patch.py"
      to: "ai_debug/models/ai_session.py"
      via: "pop_last_completion_data() returns request_body"
      pattern: "request_body"
    - from: "ai_debug/models/ai_session.py"
      to: "ai_debug/static/src/app/detail/iter_detail.xml"
      via: "iteration bus event carries request_body field"
      pattern: "request_body"
---

<objective>
Capture the full HTTP request body per iteration in ai_debug and display it in a new "Request" tab in the iteration detail view.

Purpose: Currently the debugger captures what was sent (messages) and what came back (raw_response), but not the actual HTTP body sent to the LLM provider. The request body includes provider-specific formatting, tool schemas, temperature, model name, and other parameters that are invisible in the messages-sent view. This closes the observability gap.

Output: Modified backend patch + session files, updated frontend iter_detail component with Request tab.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/models/ai_provider_patch.py
@ai_debug/models/ai_session.py
@ai_debug/static/src/app/detail/iter_detail.js
@ai_debug/static/src/app/detail/iter_detail.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Capture request body in thread-local and include in iteration bus event</name>
  <files>
    ai_debug/models/ai_provider_patch.py
    ai_debug/models/ai_session.py
  </files>
  <action>
**ai_provider_patch.py:**

1. In `_patched_request()`, inside the `is_completion` branch, stash the request body in thread-local storage BEFORE calling `_original_request`:
   ```python
   _ai_debug_local.last_request_body = body
   ```
   Place this line right before `t0 = time.monotonic()` (line 57). The body is the dict that will be JSON-serialized by the HTTP layer — capture it before the call so it's available even if the request fails.

2. In `pop_last_completion_data()`:
   - Read `last_request_body` from thread-local (same pattern as `last_completion_response` on line 162):
     ```python
     request_body = getattr(_ai_debug_local, 'last_request_body', None)
     ```
   - Clear it immediately after reading (same pattern as lines 168-169):
     ```python
     _ai_debug_local.last_request_body = None
     ```
   - Add `'request_body': request_body` to the returned dict (alongside `tokens` and `llm_duration_ms`).

3. Update the module docstring (line 5 comment about fields) to mention `last_request_body`.

**ai_session.py:**

1. In `_run_agentic_loop()`, after the existing `completion_data` extraction (around line 211-217), extract `request_body`:
   ```python
   request_body = completion_data.get('request_body')
   ```

2. Strip binary data from the request body before including in the bus event. The request body contains provider-formatted messages that may include base64 image data. Apply binary stripping to the message array inside the body:
   - For OpenAI: the key is `"input"` (a list of message dicts)
   - For Google: the key is `"contents"` (a list of message dicts)

   After extracting `request_body`, if it's not None, make a shallow copy and strip binaries from the message array:
   ```python
   if request_body is not None:
       import copy
       request_body = copy.copy(request_body)  # shallow copy to avoid mutating original
       # Strip binary from OpenAI input messages
       if isinstance(request_body.get('input'), list):
           request_body['input'] = self._ai_debug_strip_binary(request_body['input'])
       # Strip binary from Google contents messages
       if isinstance(request_body.get('contents'), list):
           request_body['contents'] = self._ai_debug_strip_binary(request_body['contents'])
   ```
   Note: `copy` is already imported at the top of ai_session.py (line 1).

3. Add `request_body` to `iteration_payload` (the dict built around lines 228-238) conditionally:
   ```python
   if request_body is not None:
       iteration_payload['request_body'] = request_body
   ```
   Place this alongside the existing conditional fields (after the `if llm_duration_ms` block around line 243).

4. Do NOT add request_body to the error iteration payloads in the except blocks (lines 265-280, 295-309) — there is no meaningful request body to capture when an exception occurs before completion data is available.
  </action>
  <verify>
    grep -n "last_request_body" ai_debug/models/ai_provider_patch.py && grep -n "request_body" ai_debug/models/ai_session.py
  </verify>
  <done>
    - `_patched_request` stashes body in `_ai_debug_local.last_request_body` before the LLM call
    - `pop_last_completion_data` returns `request_body` alongside `tokens` and `llm_duration_ms`
    - `_run_agentic_loop` includes `request_body` (with binary-stripped messages) in iteration bus events
  </done>
</task>

<task type="auto">
  <name>Task 2: Add Request tab to iteration detail view</name>
  <files>
    ai_debug/static/src/app/detail/iter_detail.js
    ai_debug/static/src/app/detail/iter_detail.xml
  </files>
  <action>
**iter_detail.js:**

Add a `requestJson` getter following the same pattern as `responseJson` (line 37-39):
```javascript
get requestJson() {
    return JSON.stringify(this.props.iteration.request_body, null, 2);
}
```

**iter_detail.xml:**

Add a new "Request" tab to the Notebook, placed BETWEEN the "Messages Sent" tab and the "Raw Response" tab (i.e., after the closing `</t>` of the messages slot on line 36, before the response slot on line 38). Follow the exact same pattern as the "Raw Response" tab:

```xml
<t t-set-slot="request" title="'Request'" isVisible="true">
    <div class="ai-detail-section">
        <div class="ai-detail-section-header">
            <span>HTTP Request Body</span>
            <CopyButton content="() => this.requestJson"/>
        </div>
        <JsonTree data="props.iteration.request_body"
                  onExpandText="(title, content) => this.openTextPopup(title, content, 'json')"/>
    </div>
</t>
```

The tab should render even when `request_body` is undefined/null — JsonTree handles null data gracefully by showing nothing. The `isVisible="true"` keeps it always available in the tab bar.
  </action>
  <verify>
    grep -n "requestJson\|request_body\|Request" ai_debug/static/src/app/detail/iter_detail.js ai_debug/static/src/app/detail/iter_detail.xml
  </verify>
  <done>
    - Iteration detail view shows three tabs: "Messages Sent", "Request", "Raw Response"
    - Request tab renders the request_body using JsonTree with collapsible nodes
    - Copy button on Request tab copies the full JSON to clipboard
  </done>
</task>

</tasks>

<verification>
1. Backend: `grep -rn "request_body" ai_debug/models/` shows the field flowing from patch -> session -> bus event
2. Frontend: `grep -rn "request_body\|requestJson\|Request" ai_debug/static/src/app/detail/` shows the tab and getter
3. Manual: Trigger an AI agent conversation, open the debugger, click an iteration row, verify the "Request" tab appears between "Messages Sent" and "Raw Response" and shows the full HTTP body as a JSON tree
</verification>

<success_criteria>
- The HTTP request body is captured per-iteration and transmitted via bus event
- Binary content in request body messages is stripped before transmission
- A "Request" tab appears in the iteration detail view showing the request body as a collapsible JSON tree
- Copy button on the Request tab copies the full request body JSON
</success_criteria>

<output>
After completion, create `.planning/quick/38-capture-request-body-in-ai-debug-iterati/38-SUMMARY.md`
</output>
