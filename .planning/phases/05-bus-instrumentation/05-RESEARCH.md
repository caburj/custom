# Phase 5: Bus Instrumentation - Research

**Researched:** 2026-02-21
**Domain:** Odoo bus.bus instrumentation / Python agentic loop override
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Tools definition in `new_trace` event: include full JSON schemas (name, description, parameters) — not just names
- Raw LLM response in iteration events: include the full API response object (content, usage stats, finish_reason, model info, token counts)
- All events go on a single `ai_debug` channel, differentiated by a `type` field in the payload (not per-type channels)
- `messages_sent` in iteration events: Claude decides whether to send full conversation history or deltas, based on payload size tradeoffs and downstream complexity
- Field naming convention (snake_case vs camelCase): Claude decides based on Odoo conventions and bus layer patterns
- Capture everything available for state snapshots: discuss context (partner, channel), environment (uid, company, lang), tool registry, model config — full picture
- Send full state snapshots each time; the OWL frontend computes diffs for display
- State snapshots taken both before and after each tool call
- Whether the `new_trace` event includes a baseline state snapshot is at Claude's discretion — research the `ai` module's agentic loop to determine what state is available at loop start
- No size limits or truncation — send everything. This is a dev tool, optimize later if needed
- Instrumentation pre-serializes all Python objects to JSON-safe dicts before sending
- Exclude binary content from payloads; include metadata only (filename, size, mimetype)
- Explicit `loop_end` event when the agentic loop finishes, carrying termination reason (success, max_iterations, error, user_cancel)
- `loop_end` includes summary stats: iteration_count, tool_call_count, duration_ms, termination_reason
- Tool call errors: emit normal tool_call event with an `error` field
- LLM API failures: part of the iteration event with an error field instead of raw_response

### Claude's Discretion

- `messages_sent`: send full conversation history vs deltas — recommend full history per iteration for downstream simplicity
- Field naming convention — recommend snake_case throughout (matches Odoo Python conventions; frontend can alias if needed)
- Whether `new_trace` includes a baseline state snapshot

### Deferred Ideas (OUT OF SCOPE)

- Binary content inclusion in payloads via ir.attachment
- Subagent nesting in event hierarchy (NEST-01)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BUS-01 | Instrumentation sends full iteration data (messages_sent, raw_response, state snapshots) over bus.bus | Override `_run_agentic_loop` in `ai.session`; emit before/after state in `new_trace` + per-iteration bus sends |
| BUS-02 | Instrumentation sends full tool call data (args, result, state snapshots) over bus.bus | Override `_handle_tool_calls` in `ai.session`; capture before/after state at each tool call |
| BUS-03 | Loop start event includes system prompt, RAG context, tools definition, agent name, and model name | At `_run_agentic_loop` entry, serialize tools (from `formatted_tools`), instructions, model name; `new_trace` event |
| BUS-04 | All bus sends use separate cursors for real-time delivery (not batched at HTTP commit) | `Registry(dbname).cursor()` pattern confirmed in `ai/controllers/thread.py`; `_sendone` with auto-commit flushes immediately |
| BUS-05 | UUID keys replace DB autoincrement IDs for trace/iteration/tool_call identification | Python `uuid.uuid4()` already used in `ai` module; no DB models needed |
</phase_requirements>

## Summary

Phase 5 instruments the existing `ai.session` agentic loop by overriding two key `@api.model` methods — `_run_agentic_loop` and `_handle_tool_calls` — in the `ai_debug` module. The overrides inject bus events at four lifecycle points: loop start (`new_trace`), per-iteration LLM call (`iteration`), per-tool-call (`tool_call`), and loop end (`loop_end`). All events are sent to the string channel `"ai_debug"` using separate cursors so they arrive in the browser before the HTTP response commits.

The critical architectural insight is how `bus.bus._sendone` works: it enqueues messages into `precommit.data` and fires NOTIFY on `postcommit`. Standard HTTP request cursors commit all at once at request end — batching everything. To send events one-by-one during the loop, the instrumentation must use a **separate cursor per event** (via `self.env.registry.cursor()`) that commits independently from the main request cursor. This exact pattern is already used in `ai/controllers/thread.py` and throughout the Odoo enterprise codebase.

The `_run_agentic_loop` method signature and generator protocol are fully understood from source. Override is straightforward: `super()` call wrapped with UUID generation, timing, and bus sends at each yield point. The `formatted_tools` list (from `_prepare_tools`) provides the full JSON schemas needed for BUS-03. State snapshot should include: `tools_context['state']`, `session.res_model`, `session.res_id`, `session.channel_id`, `env.uid`, `env.company.id`, `env.lang`.

**Primary recommendation:** Override `_run_agentic_loop` and `_handle_tool_calls` on `ai.session` in `ai_debug/models/ai_session.py`. Use `env.registry.cursor()` for each bus send to ensure real-time delivery. Generate all UUIDs with `uuid.uuid4().hex`.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uuid` (Python stdlib) | any | Generate UUID4 identifiers | Already used in `ai` module (`ir_http.py`, `ai_api_service_google.py`); no DB autoincrement available |
| `odoo.addons.bus` (bus.bus) | master | Transport layer for real-time events | Channel `"ai_debug"` already subscribed in frontend; `ir.websocket` override already gates access |
| `odoo.modules.registry.Registry` | master | Acquire separate cursors for real-time flush | Same pattern used in `ai/controllers/thread.py` line 45–46 |
| `time` (Python stdlib) | any | Duration tracking (`time.monotonic()`) | Standard; needed for `duration_ms` in `loop_end` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` (Python stdlib) | any | Pre-serialize complex objects to JSON-safe dicts before bus send | Required by user decision: "pre-serialize all Python objects" |
| `logging` | any | Debug instrumentation failures | Standard Odoo pattern |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `env.registry.cursor()` | `env.cr` (main cursor) | Main cursor batches all bus sends until HTTP commit; separate cursor commits immediately per event |
| String channel `"ai_debug"` | Per-user channel (partner record) | String channel simpler; security gate already enforces internal-user-only in `ir.websocket` |

## Architecture Patterns

### Recommended Project Structure

```
ai_debug/
├── models/
│   ├── __init__.py        # add ai_session import
│   ├── ir_websocket.py    # already exists (channel gate)
│   └── ai_session.py      # NEW: override _run_agentic_loop + _handle_tool_calls
└── (no new views, no new ir.model records needed)
```

### Pattern 1: Override `_run_agentic_loop` via `@api.model`

**What:** Inherit `ai.session`, override `_run_agentic_loop` with `super()` call, wrap generator protocol to inject bus events at each yield point.

**When to use:** Instrumenting any `@api.model` generator method without modifying upstream code.

The method signature from source:
```python
# ai/models/ai_session.py line 381
@api.model
def _run_agentic_loop(self, model, instructions, messages, temperature, tools, tools_context, record=None, schema=None, web_grounding=False):
```

The generator yields three kinds of items:
- `{'tool_calls': [...], 'metadata': response}` — LLM requested tool calls; `metadata` IS the raw response
- `{'tool_results': [...], 'metadata': tool_outputs}` — tool results formatted for LLM
- `{'final_message': [...], 'metadata': response}` — loop done; `metadata` IS the raw response

The `response` value from `get_completions()` is a list of provider-formatted dicts (OpenAI Items or Google Messages) — this IS the raw API response in provider-normalized format.

**Example structure:**
```python
# ai_debug/models/ai_session.py
import uuid
import time
from odoo import api, models

class AiSession(models.TransientModel):
    _inherit = 'ai.session'

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, temperature, tools, tools_context, record=None, schema=None, web_grounding=False):
        trace_id = uuid.uuid4().hex
        iteration_count = 0
        tool_call_count = 0
        started_at = time.monotonic()

        # Emit new_trace event before first iteration
        self._ai_debug_bus_send('ai_debug/new_trace', {
            'type': 'new_trace',
            'trace_id': trace_id,
            'agent_name': self.agent_id.name if self else None,
            'model_name': model,
            'instructions': instructions,          # full system prompt (includes RAG context)
            'tools': self._ai_debug_serialize_tools(tools, model),
            'state_snapshot': self._ai_debug_state_snapshot(tools_context),
        })

        try:
            for item in super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            ):
                if 'tool_calls' in item or 'final_message' in item:
                    # This is an LLM response — emit iteration event
                    iteration_id = uuid.uuid4().hex
                    iteration_count += 1
                    self._ai_debug_bus_send('ai_debug/iteration', {
                        'type': 'iteration',
                        'trace_id': trace_id,
                        'iteration_id': iteration_id,
                        'iteration_index': iteration_count,
                        'messages_sent': messages,      # full current messages list
                        'raw_response': item.get('metadata'),
                        'has_tool_calls': 'tool_calls' in item,
                        'is_final': 'final_message' in item,
                    })
                yield item
        except Exception as e:
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            self._ai_debug_bus_send('ai_debug/loop_end', {
                'type': 'loop_end',
                'trace_id': trace_id,
                'termination_reason': 'error',
                'error': str(e),
                'iteration_count': iteration_count,
                'tool_call_count': tool_call_count,
                'duration_ms': elapsed_ms,
            })
            raise

        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        self._ai_debug_bus_send('ai_debug/loop_end', {
            'type': 'loop_end',
            'trace_id': trace_id,
            'termination_reason': 'success',
            'iteration_count': iteration_count,
            'tool_call_count': tool_call_count,
            'duration_ms': elapsed_ms,
        })
```

### Pattern 2: Separate Cursor for Real-Time Bus Send (BUS-04)

**What:** Standard `_sendone` queues sends on the main cursor's precommit hooks. Using a separate cursor commits immediately, flushing NOTIFY before the HTTP request completes.

**Source:** `enterprise/ai/controllers/thread.py` lines 45–46 + `odoo/addons/bus/models/bus.py` `_ensure_hooks`.

```python
def _ai_debug_bus_send(self, notification_type, payload):
    """Send a bus event immediately using a separate cursor."""
    try:
        dbname = self.env.cr.dbname
        channel = 'ai_debug'
        with self.env.registry.cursor() as cr:
            env = self.env(cr=cr)
            env['bus.bus']._sendone(channel, notification_type, payload)
            # precommit hook fires here at context manager exit (cr.commit())
    except Exception:
        _logger.exception("AI Debug: failed to send bus event %s", notification_type)
```

**Key insight:** `registry.cursor()` is a context manager that calls `cr.commit()` on exit. This triggers the `precommit` hooks that insert into `bus_bus` and then the `postcommit` hooks that NOTIFY PostgreSQL. The browser receives the event before the next iteration of the agentic loop begins.

### Pattern 3: Override `_handle_tool_calls` for Per-Tool-Call Events (BUS-02)

**What:** `_handle_tool_calls` is a generator that yields `{'thought': ...}`, `{'tool_confirmation_request': ...}`, `{'tool_results': ...}`, and `{'final_message': ...}` items. Override to capture state before and after each tool execution.

**Source:** `ai/models/ai_session.py` lines 155–232.

The challenge: `_handle_tool_calls` loops over `tool_calls` list internally. The override needs to capture state snapshot _before_ the tool runs and emit a `tool_call` event with before+after state _after_ `format_tool_result` completes.

**Option A (recommended): Re-implement the capture loop around super()**

Since `_handle_tool_calls` yields `tool_results` only after ALL tool calls in a batch are processed, capturing individual before/after states requires wrapping each individual call. The cleanest approach is to override and monkey-instrument at the tool level:

```python
def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record, confirmed_tool_id=None, refuse_all=False):
    # Capture state before any tool runs (for the first tool_call event)
    for item in super()._handle_tool_calls(
        tool_calls, tools_by_name, tools_context, record, confirmed_tool_id, refuse_all
    ):
        yield item
```

This approach won't give per-tool before/after states since `super()` processes all tool_calls as a batch. **Better approach:** Since the user decided "state snapshots taken both before and after each tool call", we need to instrument at a finer level.

**Option B (recommended): Instrument `tools_context` state before/after each tool**

`tools_context['state']` is the mutable state dict that tools modify. Snapshot it before yielding from super() and again after. Since `tool_results` contains all results for a batch, emit one `tool_call` event per result item:

```python
def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record, confirmed_tool_id=None, refuse_all=False):
    state_before_batch = copy.deepcopy(tools_context.get('state') or {})
    for item in super()._handle_tool_calls(
        tool_calls, tools_by_name, tools_context, record, confirmed_tool_id, refuse_all
    ):
        if tool_results := item.get('tool_results'):
            # Emit one tool_call event per result
            for result_item in tool_results:
                self._ai_debug_bus_send('ai_debug/tool_call', {
                    'type': 'tool_call',
                    'tool_call_id': uuid.uuid4().hex,
                    'tool_name': result_item['tool_call']['name'],
                    'args': result_item['tool_call'].get('args', {}),
                    'result': result_item.get('result'),
                    'success': result_item.get('success', True),
                    'state_before': state_before_batch,
                    'state_after': copy.deepcopy(tools_context.get('state') or {}),
                })
        yield item
```

**Limitation of Option B:** Both `state_before` and `state_after` represent the batch boundary, not individual tool boundaries. For the v1.1 scope this is acceptable since the user said "detail panel shows exactly what a tool changed" — this captures what changed across the batch.

**Option C (most accurate but complex):** Fully re-implement `_handle_tool_calls` body in the override to capture per-tool state. HIGH coupling to upstream code; avoid for v1.1.

**Recommendation:** Option B for v1.1. Add a note in the plan that per-tool granularity requires Option C in a future phase.

### Pattern 4: Serialize `formatted_tools` for `new_trace` (BUS-03)

**What:** `formatted_tools` is built from `_prepare_tools()` which calls `provider._format_tool()`. The result is provider-specific (OpenAI format: `{'name': ..., 'description': ..., 'type': 'function', 'parameters': ...}`). This list is passed to `get_completions()` but not directly available inside the override of `_run_agentic_loop` until we compute it ourselves.

**Available at override entry point:**
- `tools` — recordset of `ir.actions.server` with `ai_tool_schema`, `ai_tool_description`
- `model` — string model name (used to get provider)
- `instructions` — full system prompt (already includes RAG context injected in `_get_instructions()` → `_build_rag_context()`)

**Approach:** Call `_prepare_tools` from the override to get the formatted list for the event payload:

```python
def _ai_debug_serialize_tools(self, tools, model):
    """Get tool definitions in provider-agnostic format for new_trace payload."""
    from odoo.addons.ai.services.ai_provider import AIProvider
    if not tools:
        return []
    provider = AIProvider.get_by_model(self.env, model)
    tools_by_name = self._get_tools_by_name(tools)
    formatted = self._prepare_tools(tools_by_name, provider)
    # formatted is a list of provider-formatted tool dicts
    # already JSON-safe (no ORM objects)
    return formatted
```

**Note:** `instructions` already contains the RAG context (injected by `_get_context_input` → but actually RAG is injected into the `message`, not `instructions`). The `instructions` parameter to `_run_agentic_loop` IS the full system prompt from `_get_instructions()`. RAG is added to the user message part in `_generate_next_response`. So `new_trace` will have the system prompt (instructions) but not the RAG context that was appended to the user message. However, looking at `_get_context_input`, it includes RAG inline in `message['parts']`. For full observability, capture `messages[0]` as the initial message which will contain the RAG context.

### Pattern 5: State Snapshot Composition

**What:** The `state_snapshot` dict to include in events.

**Available context from method parameters:**
- `tools_context['state']` — the mutable tool state dict (tool registry, any session data)
- `tools_context['llm_model']` — model name
- `tools_context['res_model']` / `tools_context['res_id']` — linked record (if any)
- `self.env.uid` — current user ID
- `self.env.company.id` — current company ID
- `self.env.lang` — current language
- `self.channel_id.id` — discuss channel ID (if session-based)
- `self.agent_id.id` / `self.agent_id.name` — agent info

**State snapshot helper:**
```python
def _ai_debug_state_snapshot(self, tools_context):
    import copy
    return {
        'tool_state': copy.deepcopy(tools_context.get('state') or {}),
        'uid': self.env.uid,
        'company_id': self.env.company.id,
        'lang': self.env.lang,
        'res_model': tools_context.get('res_model'),
        'res_id': tools_context.get('res_id'),
        'channel_id': self.channel_id.id if self.channel_id else None,
        'agent_id': self.agent_id.id if self.agent_id else None,
        'agent_name': self.agent_id.name if self.agent_id else None,
        'llm_model': tools_context.get('llm_model'),
    }
```

### Pattern 6: `loop_end` Termination Reasons

The agentic loop terminates in three ways (from `ai_session.py`):
1. **success** — generator yields `{'final_message': ...}` and returns
2. **max_iterations** — `UserError` raised after `max_successive_calls` exceeded (line 416)
3. **error** — any other exception

The `max_successive_calls` `UserError` message is: "Number of successive API calls exceeded, please try again with a more precise request." Detect by checking exception type and message.

**Termination reason detection:**
```python
except UserError as e:
    reason = 'max_iterations' if 'successive' in str(e).lower() else 'error'
    # emit loop_end with reason
    raise
except Exception:
    # emit loop_end with reason='error'
    raise
```

### Anti-Patterns to Avoid

- **Sending bus events on the main cursor:** `env['bus.bus']._sendone(channel, ...)` on the request's `env.cr` will batch all events until HTTP commit. Must use `self.env.registry.cursor()` for real-time.
- **Using `self.env.user._bus_send()`:** This sends to the user's partner channel, not the `"ai_debug"` string channel. Use `_sendone` directly with `"ai_debug"` string.
- **Passing ORM recordsets in payloads:** Will fail or produce wrong results when serialized. Pre-serialize all ORM data to plain dicts/scalars.
- **Passing binary data in payloads:** Base64 encode of file content in `ir.attachment` must be excluded. Include only filename, size, mimetype.
- **Serializing `messages` list without care:** The `messages` list contains provider-formatted dicts (OpenAI Items, Google Messages). These are plain dicts, safe to send. However, base64 image/file content in `input_image` / `input_file` parts should be stripped (replaced with metadata).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Real-time delivery | Custom NOTIFY loop | `env.registry.cursor()` + `_sendone` | Pattern established in `ai/controllers/thread.py`; handles NOTIFY splitting |
| UUID generation | Sequential IDs, timestamp IDs | `uuid.uuid4().hex` | Already used in `ai` module; no DB sequence needed |
| Bus channel security | Custom auth | Already implemented in `ir.websocket` override (Phase 4) | Modifying the existing gate is wrong; it's already correct |
| Binary detection in messages | Custom MIME detection | Check `part['type']` in message parts (not `'text'`) | Provider format already types each part |

## Common Pitfalls

### Pitfall 1: Main Cursor Batches All Bus Sends

**What goes wrong:** Events arrive all at once in the browser after the HTTP response, not one-by-one during the loop.

**Why it happens:** `bus.bus._sendone` uses `precommit.data` on the current cursor. The cursor doesn't commit until the HTTP request handler finishes. Every `_sendone` in `_run_agentic_loop` accumulates in the same precommit batch.

**How to avoid:** Wrap every bus send in `with self.env.registry.cursor() as cr:` and use `self.env(cr=cr)['bus.bus']._sendone(...)`. The context manager commits the cursor immediately, flushing precommit+postcommit hooks.

**Warning signs:** All events appear simultaneously in browser after agent response posts; no events during loop execution.

### Pitfall 2: `@api.model` Override Loses `self` Context

**What goes wrong:** `self` is an empty recordset (`AiSession` with no ID) when called as `@api.model`. Session fields like `self.agent_id`, `self.channel_id` may not be available.

**Why it happens:** `_run_agentic_loop` is `@api.model` — it's called on the model class, not a record. `self` is the model class with the caller's environment, but not bound to a specific record.

**How to avoid:** Check `self.ids` before accessing instance fields. In practice, `_generate_next_response` calls `self._run_agentic_loop(...)` where `self` IS a specific `ai.session` record, so `self.agent_id` etc. are available. `_get_direct_response` calls `self._run_agentic_loop(...)` where `self` is also a record (via `self.env['ai.session']`). The pattern is safe.

**Warning signs:** `AttributeError` on `self.agent_id.name` or `MissingError`.

### Pitfall 3: `messages` List Mutates During Loop

**What goes wrong:** The `messages` list passed to `_run_agentic_loop` is mutated by `messages.extend(response)` inside the loop (line 404 of `ai_session.py`). If the override captures `messages` at iteration start, it sees the growing history.

**Why it happens:** `messages` is a mutable list passed by reference. The super() implementation extends it in-place each iteration.

**How to avoid:** To send `messages_sent` for an iteration (what was actually sent to the LLM at that iteration), capture `list(messages)` (a shallow copy) BEFORE yielding from super, OR capture the length before and after to extract just the new items.

**Recommendation:** For BUS-01, `messages_sent` means "the full conversation history sent to the LLM for this iteration." Since the user decided "Claude decides whether to send full history or deltas," recommend sending the full current `messages` list (a shallow copy taken at iteration start). This is downstream-simpler. A shallow copy of provider-formatted dicts is fine (the inner dicts are not mutated).

### Pitfall 4: Binary Content in `messages` List

**What goes wrong:** `input_image` and `input_file` parts in the `messages` list contain base64-encoded binary data in `image_url` or `file_data` fields. Sending these over bus.bus creates huge payloads.

**Why it happens:** The provider formatters (`_format_to_llm`) embed binary content directly in the message list (e.g., OpenAI: `"file_data": "data:application/pdf;base64,..."` — line 116-122 of `ai_provider_openai.py`).

**How to avoid:** When serializing `messages_sent` for the bus payload, strip binary content. Scan each message for parts with `type` in `('input_image', 'input_file')` and replace content with metadata:

```python
def _ai_debug_strip_binary(self, messages):
    """Strip binary content from messages for bus payload."""
    import copy
    result = []
    for msg in messages:
        msg_copy = copy.copy(msg)
        if 'content' in msg_copy and isinstance(msg_copy['content'], list):
            new_content = []
            for part in msg_copy['content']:
                if part.get('type') in ('input_image', 'input_file'):
                    new_content.append({
                        'type': part['type'],
                        '_binary_excluded': True,
                        'original_type': part.get('type'),
                    })
                else:
                    new_content.append(part)
            msg_copy = dict(msg_copy, content=new_content)
        result.append(msg_copy)
    return result
```

### Pitfall 5: `tools_context['state']` is Mutated by Tools

**What goes wrong:** State snapshots before/after tool calls reference the same dict object.

**Why it happens:** `tools_context['state']` is mutated in-place by tools (they write to it directly).

**How to avoid:** Always use `copy.deepcopy(tools_context.get('state') or {})` for state snapshots.

### Pitfall 6: Separate Cursor Environment Isolation

**What goes wrong:** Fields like `self.agent_id` load data from the ORM cache of the main cursor. The separate cursor has its own transaction context but the `self` record is still valid because it references the main cursor's environment.

**Why it happens:** Using `self.env.registry.cursor()` creates a new cursor but we pass `self.env(cr=cr)` which creates a new environment on the separate cursor. However, `self` is still bound to the original env. Avoid loading ORM data in the separate-cursor environment block.

**How to avoid:** Pre-extract all needed data (agent name, model name, etc.) from `self` in the main cursor BEFORE opening the separate cursor. Pass only plain Python values (strings, dicts, ints) into the separate cursor block.

```python
# Correct pattern
agent_name = self.agent_id.name  # read from main cursor
payload = {'agent_name': agent_name, ...}

def _ai_debug_bus_send(self, notification_type, payload):
    try:
        with self.env.registry.cursor() as cr:
            cr.env = self.env(cr=cr)  # new env on new cursor
            cr.env['bus.bus']._sendone('ai_debug', notification_type, payload)
    except Exception:
        _logger.exception("AI Debug bus send failed")
```

## Code Examples

### Complete `_ai_debug_bus_send` helper

```python
# Source: ai/controllers/thread.py lines 44-46 (separate cursor pattern)
# Source: bus/models/bus.py lines 132-154 (_sendone implementation)

import logging
_logger = logging.getLogger(__name__)

def _ai_debug_bus_send(self, notification_type, payload):
    """Send an ai_debug bus event using a separate cursor for real-time delivery."""
    try:
        with self.env.registry.cursor() as cr:
            env = self.env(cr=cr)
            env['bus.bus']._sendone('ai_debug', notification_type, payload)
    except Exception:
        _logger.exception("ai_debug: failed to send bus event '%s'", notification_type)
```

### `new_trace` event payload structure

```python
# Emitted once at the start of _run_agentic_loop
{
    'type': 'new_trace',
    'trace_id': 'abc123...',       # uuid4().hex
    'agent_name': 'My Agent',      # self.agent_id.name (if available)
    'model_name': 'gpt-4o',        # model parameter
    'instructions': '...',          # full system prompt (includes topic instructions)
    'tools': [                      # formatted_tools list (provider-specific format)
        {
            'name': 'ai_create_leads_42',
            'description': '...',
            'type': 'function',
            'parameters': {...},   # full JSON schema
        }
    ],
    'state_snapshot': {            # environment at loop start
        'tool_state': {},          # tools_context['state'] (empty at loop start)
        'uid': 2,
        'company_id': 1,
        'lang': 'en_US',
        'res_model': 'sale.order',
        'res_id': 42,
        'channel_id': 15,
        'agent_id': 3,
        'agent_name': 'My Agent',
        'llm_model': 'gpt-4o',
    },
}
```

### `iteration` event payload structure

```python
# Emitted once per LLM API call (before tool calls are processed)
{
    'type': 'iteration',
    'trace_id': 'abc123...',
    'iteration_id': 'def456...',   # uuid4().hex — unique per iteration
    'iteration_index': 1,           # 1-based counter
    'messages_sent': [...],         # shallow copy of messages list at call time (binary stripped)
    'raw_response': [...],          # item['metadata'] — provider-formatted response
    'has_tool_calls': True,
    'is_final': False,
    # If LLM API call failed:
    # 'error': 'Network timeout: ...'
    # 'raw_response': None
}
```

### `tool_call` event payload structure

```python
# Emitted once per tool in a batch (after tool execution)
{
    'type': 'tool_call',
    'trace_id': 'abc123...',
    'iteration_id': 'def456...',   # parent iteration
    'tool_call_id': 'ghi789...',   # uuid4().hex — unique per tool call
    'tool_name': 'ai_create_leads_42',
    'call_id': 'call_xyz',          # LLM's original call_id for correlation
    'args': {...},                  # tool arguments dict
    'result': '...',                # tool result string or dict
    'success': True,
    'error': None,                  # populated if success=False
    'state_before': {...},          # deepcopy of tool_state before batch
    'state_after': {...},           # deepcopy of tool_state after batch
}
```

### `loop_end` event payload structure

```python
# Emitted once when loop terminates (success, max_iterations, or error)
{
    'type': 'loop_end',
    'trace_id': 'abc123...',
    'termination_reason': 'success',  # 'success' | 'max_iterations' | 'error'
    'error': None,                     # error message if termination_reason='error'
    'iteration_count': 3,
    'tool_call_count': 5,
    'duration_ms': 12450,
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| DB-backed trace/iteration models (`ai.debug.trace` etc.) | Ephemeral bus events + frontend-only memory | Phase 4 MIGR-02 decision | No DB persistence needed; simpler instrumentation |
| Integer autoincrement IDs (DB sequences) | UUID4 hex strings | Phase 5 BUS-05 | No DB write required for ID generation |
| Batched bus sends (all at HTTP commit) | Separate cursor per event | Phase 5 BUS-04 | Events visible in browser during loop execution |

## Open Questions

1. **Is `new_trace` emitted for `_get_direct_response` calls (server actions) or only `_generate_next_response` (chat)?**
   - What we know: Both call `_run_agentic_loop`. Overriding `_run_agentic_loop` instruments both.
   - What's unclear: `_get_direct_response` has no `session` context (no `self.agent_id` etc.). The `self` in that context is `ai.session` class without a specific record.
   - Recommendation: Emit `new_trace` for both, but populate agent fields conditionally (`agent_name = self.agent_id.name if self.agent_id else None`). This gives full observability for server action loops too.

2. **Does `new_trace` include a baseline state snapshot?**
   - What we know: At loop start, `tools_context['state']` is `{}` (empty, from `_generate_next_response`) or `{}` (from `_get_direct_response`). The session `self.state` may have been set by a previous tool call (stored in TransientModel).
   - Recommendation: YES, include a state snapshot in `new_trace`. It captures the environment at loop start. `tool_state` will be `{}` for fresh sessions, but `uid`, `company_id`, `lang`, `res_model`, `res_id`, `channel_id` are valuable context.

3. **`messages_sent` — full history or current batch only?**
   - What we know: At iteration N, `messages` contains the full accumulated conversation history (initial user message + all previous LLM responses + tool results).
   - Recommendation: Send **full history** (shallow copy). Rationale: downstream simplicity — Phase 7 detail panel just reads `messages_sent[iteration]` to render the conversation; no need to reconstruct history from deltas. Payload size is the only concern, but user decided no truncation for v1.1.

4. **What happens if the separate cursor `_ai_debug_bus_send` fails?**
   - What we know: `_sendone` can fail if the DB is unavailable or the cursor is exhausted.
   - Recommendation: Wrap in `try/except` and log the error; do NOT propagate — instrumentation must never disrupt the main loop. This is already shown in the code examples above.

## Sources

### Primary (HIGH confidence)

- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py` — Full `_run_agentic_loop` (line 381), `_handle_tool_calls` (line 155), `_prepare_tools` (line 418) source code read directly
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/controllers/thread.py` — `Registry(dbname).cursor()` pattern (lines 44–46) — confirmed separate cursor usage
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus.py` — `_sendone` implementation (lines 132–154); `precommit`/`postcommit` hook mechanism confirmed
- `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/bus/models/bus_listener_mixin.py` — `_bus_send` uses `_sendone` on current env cursor
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/services/ai_provider_openai.py` — `_format_tool` return structure (lines 146–207), `_format_to_llm` binary embedding pattern (lines 93–142)
- `/Users/joseph/clones/odoo/custom/ai_debug/models/ir_websocket.py` — Channel gate already implemented for `"ai_debug"` string channel (Phase 4)

### Secondary (MEDIUM confidence)

- Enterprise codebase grep for `registry.cursor()` — confirmed pattern in `iap_extract/models/extract_mixin.py`, `l10n_au_hr_payroll_api`, `web_studio/controllers/report.py`, `whatsapp/models/whatsapp_account.py`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all APIs read directly from source
- Architecture: HIGH — agentic loop structure fully read from source; separate cursor pattern confirmed in multiple places
- Pitfalls: HIGH — most identified from code analysis, not speculation; binary content pitfall confirmed from `_format_to_llm` source

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (stable codebase; `ai` module would need to change materially to invalidate)
