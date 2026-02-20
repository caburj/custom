---
phase: quick
plan: 2
subsystem: ai_debug
tags: [observability, tools, json-field, trace]
dependency_graph:
  requires: []
  provides: [tools_definition field on ai.debug.trace, tools capture in _run_agentic_loop]
  affects: [ai_debug/models/ai_debug_trace.py, ai_debug/models/ai_session.py, ai_debug/views/ai_debug_trace_views.xml]
tech_stack:
  added: []
  patterns: [Odoo Json field, separate cursor write, tool recordset iteration]
key_files:
  modified:
    - ai_debug/models/ai_debug_trace.py
    - ai_debug/models/ai_session.py
    - ai_debug/views/ai_debug_trace_views.xml
decisions:
  - Capture raw tool.name (human-readable, e.g. "Create Leads") not the provider-formatted make_tool_name version (e.g. "ai_create_leads_42") since provider context is unavailable in the override
  - Empty tools list stored as False (not []) to follow Odoo Json field convention for "no value"
metrics:
  duration: 1 min
  completed: 2026-02-20
  tasks_completed: 2
  files_modified: 3
---

# Quick Task 2: Add tools_definition to ai.debug.trace Summary

**One-liner:** tools_definition Json field on ai.debug.trace captures name, description, and schema for each tool available to the LLM per agentic loop run.

## What Was Built

Added the "tools" dimension to the inputs side of trace observability. Each `ai.debug.trace` record now records the full list of tools (name, description, and raw schema) that were available to the AI agent for that run — complementing the already-captured system prompt and RAG context.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add tools_definition field and capture logic | 3834b64 | ai_debug_trace.py, ai_session.py |
| 2 | Add tools_definition to trace form view | 9edef6e | ai_debug_trace_views.xml |

## Changes Made

### ai_debug/models/ai_debug_trace.py
- Added `tools_definition = fields.Json(string='Tools Definition')` after `rag_context`
- Updated section comment to reflect group now covers system prompt, RAG, and tools

### ai_debug/models/ai_session.py
- In `_run_agentic_loop` override: build `tools_definition` list from `tools` recordset before calling `_debug_write_trace`
- Each entry: `{'name': tool.name, 'description': ..., 'schema': tool.ai_tool_schema or ''}`
- Pass as `tools_definition or False` so empty list is stored as False (Odoo Json convention)

### ai_debug/views/ai_debug_trace_views.xml
- Renamed "System Prompt & RAG" page to "System Prompt, RAG & Tools" (page `name` attribute unchanged)
- Added `<separator string="Tools Definition"/>` and `<field name="tools_definition" readonly="1" widget="json"/>`

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `ai_debug/models/ai_debug_trace.py` — FOUND: tools_definition = fields.Json
- `ai_debug/models/ai_session.py` — FOUND: tools_definition list built and passed to _debug_write_trace
- `ai_debug/views/ai_debug_trace_views.xml` — FOUND: tools_definition field with json widget
- Commit 3834b64 — FOUND
- Commit 9edef6e — FOUND
- Python syntax check: OK
- XML well-formed check: OK
