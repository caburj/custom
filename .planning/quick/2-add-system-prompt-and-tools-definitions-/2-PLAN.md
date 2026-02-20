---
phase: quick
plan: 2
type: execute
wave: 1
depends_on: []
files_modified:
  - ai_debug/models/ai_debug_trace.py
  - ai_debug/models/ai_session.py
  - ai_debug/views/ai_debug_trace_views.xml
autonomous: true
requirements: [TOOLS-DEF-01]

must_haves:
  truths:
    - "Each ai.debug.trace record stores the list of tools available to the agent for that run"
    - "Tools definition is captured once per trace (not per iteration) since tools don't change mid-loop"
    - "Tools definition includes name, description, and parameter schema for each tool"
  artifacts:
    - path: "ai_debug/models/ai_debug_trace.py"
      provides: "tools_definition Json field on ai.debug.trace"
      contains: "tools_definition"
    - path: "ai_debug/models/ai_session.py"
      provides: "Tools capture logic in _run_agentic_loop override"
      contains: "tools_definition"
    - path: "ai_debug/views/ai_debug_trace_views.xml"
      provides: "Tools definition visible in trace form view"
      contains: "tools_definition"
  key_links:
    - from: "ai_debug/models/ai_session.py"
      to: "ai_debug/models/ai_debug_trace.py"
      via: "_debug_write_trace passes tools_definition value"
      pattern: "tools_definition"
---

<objective>
Add a `tools_definition` Json field to ai.debug.trace that captures the formatted list of tools (name, description, schema) available to the AI agent for each agentic loop run. This gives full observability into what tools the LLM was offered, complementing the already-captured system prompt and RAG context.

Purpose: Complete the "inputs" side of trace observability — instructions, RAG context, AND tools.
Output: Updated model, capture logic, and form view.
</objective>

<execution_context>
@/Users/joseph/.claude/get-shit-done/workflows/execute-plan.md
@/Users/joseph/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@ai_debug/models/ai_debug_trace.py
@ai_debug/models/ai_session.py
@ai_debug/views/ai_debug_trace_views.xml
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add tools_definition field and capture logic</name>
  <files>ai_debug/models/ai_debug_trace.py, ai_debug/models/ai_session.py</files>
  <action>
1. In `ai_debug/models/ai_debug_trace.py`, add a new Json field after the `rag_context` field (line 29):

```python
tools_definition = fields.Json(string='Tools Definition')
```

Keep it in the "System prompt + RAG" comment group. Update the comment to read: `# System prompt, RAG, and tools (captured from _generate_next_response / _run_agentic_loop)`.

2. In `ai_debug/models/ai_session.py`, in the `_run_agentic_loop` override, build a tools summary from the `tools` recordset BEFORE calling `_debug_write_trace`. Add this right after the `captured_rag` line (around line 252):

```python
# Build tools definition summary from the tools recordset.
# We serialize name, description, and schema for each tool — this is the
# "what tools were available" companion to the already-captured instructions.
tools_definition = []
if tools:
    for tool in tools:
        tools_definition.append({
            'name': tool.name,
            'description': (tool.ai_tool_description or '').strip(),
            'schema': tool.ai_tool_schema or '',
        })
```

Note: We capture the raw schema string (not parsed JSON) and the original tool record name (e.g. "Create Leads") — NOT the make_tool_name version (e.g. "ai_create_leads_42"). The raw name is more human-readable for debug inspection. The formatted/provider-specific version depends on provider which we don't have access to in the override.

3. Include `tools_definition` in the `_debug_write_trace` call dict:

```python
trace_id, bus_channel = self._debug_write_trace({
    'llm_model': model,
    'state': 'running',
    'instructions': captured_instructions,
    'rag_context': captured_rag,
    'tools_definition': tools_definition or False,
})
```

Use `or False` so empty lists are stored as False (Odoo Json field convention for "no value").
  </action>
  <verify>
    Grep for `tools_definition` in both files to confirm field declaration and usage:
    - `ai_debug/models/ai_debug_trace.py` has `tools_definition = fields.Json`
    - `ai_debug/models/ai_session.py` has the tools list construction and passes it to `_debug_write_trace`

    Python syntax check: `python3 -c "import ast; ast.parse(open('ai_debug/models/ai_debug_trace.py').read()); ast.parse(open('ai_debug/models/ai_session.py').read()); print('OK')"` returns OK.
  </verify>
  <done>
    - ai.debug.trace model has a tools_definition Json field
    - _run_agentic_loop override builds a list of {name, description, schema} dicts from the tools recordset and passes it to the trace creation
    - Empty tools list stored as False, non-empty stored as list of dicts
  </done>
</task>

<task type="auto">
  <name>Task 2: Add tools_definition to trace form view</name>
  <files>ai_debug/views/ai_debug_trace_views.xml</files>
  <action>
In `ai_debug/views/ai_debug_trace_views.xml`, update the form view's notebook:

1. Rename the "System Prompt &amp; RAG" page (line 64) to "System Prompt, RAG &amp; Tools" (keep the `name="system_prompt"` attribute unchanged for stability).

2. Add the `tools_definition` field after the `rag_context` field inside that page, with a separator for clarity:

```xml
<page string="System Prompt, RAG &amp; Tools" name="system_prompt">
    <field name="instructions" readonly="1"/>
    <field name="rag_context" readonly="1"/>
    <separator string="Tools Definition"/>
    <field name="tools_definition" readonly="1" widget="json"/>
</page>
```

The `widget="json"` renders the Json field with proper formatting in the Odoo form view.
  </action>
  <verify>
    Grep for `tools_definition` in `ai_debug/views/ai_debug_trace_views.xml` confirms the field is present in the form view. XML is well-formed: `python3 -c "from xml.etree.ElementTree import parse; parse('ai_debug/views/ai_debug_trace_views.xml'); print('OK')"` returns OK.
  </verify>
  <done>
    - Trace form view shows tools_definition in the system prompt tab
    - Tab renamed to reflect it now contains tools info too
    - Field is readonly with json widget for formatted display
  </done>
</task>

</tasks>

<verification>
After both tasks:
1. All three files modified: model, session override, view XML
2. `tools_definition` field declared, populated, and displayed
3. Python files pass syntax check
4. XML file is well-formed
</verification>

<success_criteria>
- ai.debug.trace has a tools_definition Json field
- Each trace created by _run_agentic_loop includes the tools available for that run
- The trace form view displays the tools definition alongside instructions and RAG context
- No changes to loop behavior or streaming — instrumentation only
</success_criteria>

<output>
After completion, create `.planning/quick/2-add-system-prompt-and-tools-definitions-/2-SUMMARY.md`
</output>
