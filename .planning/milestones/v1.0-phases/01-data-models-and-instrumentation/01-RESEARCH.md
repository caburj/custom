# Phase 1: Data Models and Instrumentation - Research

**Researched:** 2026-02-20
**Domain:** Odoo model inheritance, generator passthrough, separate cursor writes, Json fields, autovacuum
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**State snapshot strategy**
- State snapshots captured per tool call (before and after each individual tool execution)
- Always store full state — no truncation regardless of size
- Claude's Discretion: whether to chain from iteration-start baseline or pure tool-call chain for the 'before' snapshot

**Large payload handling**
- Messages arrays and raw LLM responses stored always verbatim — no truncation
- Tool call results (args and return values) stored always verbatim
- Use Json fields (Odoo 17.0+ native JSON support) for all JSON data — not Text fields
- Binary content (base64-encoded images): strip and replace with placeholder (`{binary: 'image/png', size: 12345}`). Future: save stripped binaries as `ir.attachment` and link back

**Module identity**
- Technical name: `ai_debug`
- Category: Technical
- Not an application (no Apps grid tile)
- Menu location: Settings > Technical > AI Debug
- Display name: "AI Debug"

**Capture failure behavior**
- On instrumentation error: log warning via `_logger.warning()` and skip the record — loop continues unaffected
- Transaction strategy: separate cursors (`registry.cursor()`) for trace writes — traces committed independently, survive loop rollbacks
- When config param `ai_debugger.enabled` is off: override remains active as no-op passthrough (checks flag, returns immediately)

**Access & retention**
- Security access: admin only (Administration/Settings group = `base.group_system`)
- Retention config: `ir.config_parameter` only (`ai_debugger.retention_days`, default 7) — no Settings UI field
- Autovacuum cron deletes traces older than retention period

### Claude's Discretion

- Exact model field types and naming beyond the Json field decision
- Internal architecture of the generator passthrough
- Savepoint vs cursor strategy for partial writes within a single trace
- How to handle the error-case trace preservation (CAPT-08) with separate cursors

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CAPT-01 | One `ai.debug.trace` per agentic loop run with agent, model, total duration, iteration count, and termination state | Override `_run_agentic_loop` to open trace before loop, close after; use `time.perf_counter()` for ms timing |
| CAPT-02 | One `ai.debug.iteration` per LLM call with full messages sent, raw response, timing | Override `_run_agentic_loop` — each iteration of the `for api_request_idx` loop emits `{'tool_calls': ..., 'metadata': response}` or `{'final_message': ..., 'metadata': response}` so raw response is available at the yield point |
| CAPT-03 | One `ai.debug.tool.call` per tool execution with name, args, result, success, timing | Override `_handle_tool_calls` — each individual tool call is wrapped by the loop; timing bracketed before/after `_ai_tool_run` call |
| CAPT-04 | Each iteration stores exact messages array sent to LLM | `messages` list is passed into `_run_agentic_loop` and extended in-place each iteration; snapshot before `get_completions()` |
| CAPT-05 | Each iteration stores raw provider response JSON verbatim | `response` from `provider.get_completions()` is the raw provider JSON; captured directly from yield metadata |
| CAPT-06 | Each trace records termination reason (final message / max iterations / confirmation pause) | Three exit points: `yield final_message`, `raise UserError` (max iterations), early return from `_handle_tool_calls` on confirmation trigger |
| CAPT-07 | Duration in milliseconds at trace, iteration, and tool call levels | `time.perf_counter()` (confirmed in-use by ai module's own `ai_api_service_openai.py`); multiply by 1000 and round for int ms |
| CAPT-08 | Exceptions during loop set `state = 'error'` and store message; streaming behavior unchanged | Separate cursor means trace record is committed independently; `try/except` around the yield loop writes error state before re-raising |
| CAPT-09 | Each trace captures full system prompt and RAG context from `_generate_next_response()` | Override `_generate_next_response` — `instructions` (from `_get_instructions()`) and the context injection (from `_get_context_input()`) are available before `_run_agentic_loop` is called |
| CAPT-10 | Tool calls that trigger user confirmation are flagged with confirmation message stored | `tools_context['tool_request_message']` is set inside `_handle_tool_calls`; the `yield {'tool_confirmation_request': ...}` is the capture point |
| CAPT-11 | Each iteration records `tools_context['state']` snapshots before/after tool execution | `tools_context['state']` is a mutable dict; snapshot with `copy.deepcopy()` before tool loop, snapshot again after each tool result |
| CONF-01 | `ir.config_parameter` master switch (`ai_debugger.enabled`) checked before any capture fires | `self.env["ir.config_parameter"].sudo().get_param("ai_debugger.enabled", "True")` pattern; check once at entry to override, return `super()` if disabled |
| CONF-02 | Scheduled action auto-deletes traces older than configurable retention period (default 7 days) | `@api.autovacuum` on `ai.debug.trace` model reads `ai_debugger.retention_days` param and unlinks old records |
</phase_requirements>

---

## Summary

Phase 1 builds on two independent deliverables: (1) three new persistent Odoo models (`ai.debug.trace`, `ai.debug.iteration`, `ai.debug.tool.call`) that store instrumentation data, and (2) a generator yield passthrough that wraps `ai.session`'s three key methods (`_run_agentic_loop`, `_handle_tool_calls`, `_generate_next_response`) to populate those models without changing the loop's behavior.

The verified source for the `ai.session` model is `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py`. This file is identical to the version in the composable-prompts worktree. The agentic loop is a generator (`_run_agentic_loop` uses `yield`), which means the override MUST also be a generator — the passthrough pattern is `for item in super()._run_agentic_loop(...): <capture> ; yield item`. The same pattern applies to `_handle_tool_calls`.

Separate cursors are the right transaction strategy for trace writes. The `ai/controllers/thread.py` already uses `Registry(dbname) + registry.cursor()` inside the same HTTP request context, and the `iap_extract` module's `postcommit + registry.cursor()` pattern is the canonical approach for writes that must survive a main-transaction rollback. Since the agentic loop itself runs within the request's cursor context (opened in `thread.py`), the instrumentation writes must use a fresh `registry.cursor()` to ensure they are committed independently.

**Primary recommendation:** Inherit `ai.session` as a TransientModel, implement generator passhthroughs for all three methods, use `self.env.registry.cursor()` for each trace write flushed at natural yield points, and put all three debug models as regular `models.Model` (not Transient) so records persist after session cleanup.

---

## Standard Stack

### Core

| Library/API | Version | Purpose | Why Standard |
|-------------|---------|---------|--------------|
| `odoo.models.Model` | Odoo master | Persistent debug record storage | TransientModel records are GC'd; debug data must survive session cleanup |
| `odoo.models.TransientModel` + `_inherit` | Odoo master | Wrapping `ai.session` without creating new table | Standard Odoo extension pattern for TransientModels |
| `fields.Json` | Odoo 17.0+ | Storing messages arrays, raw responses, args, state snapshots | Native JSONB column in PostgreSQL; used by `ai.session` itself for `state`, `pending_tools_results`, `metadata` |
| `fields.Selection` | Odoo master | Trace and tool call state fields | Type-safe, queryable enumeration |
| `time.perf_counter()` | Python stdlib | Millisecond timing at all levels | Already used by `ai_api_service_openai.py` and `ai_api_service_google.py` for the same purpose |
| `self.env.registry.cursor()` | Odoo ORM | Separate transaction for trace writes | Canonical pattern — used in `iap_extract`, `google_calendar`, `ai/controllers/thread.py` |
| `@api.autovacuum` | Odoo master | Retention cleanup | Standard GC decorator; called by `ir.autovacuum` cron without separate cron record |

### Supporting

| Library/API | Version | Purpose | When to Use |
|-------------|---------|---------|-------------|
| `copy.deepcopy()` | Python stdlib | Snapshot `tools_context['state']` before mutation | Required because `tools_context['state']` is a mutable dict modified in-place during tool execution |
| `_logger.warning()` | Python logging | Instrument failure reporting | Locked decision: log and skip on capture error |
| `ir.config_parameter` | Odoo master | `ai_debugger.enabled` and `ai_debugger.retention_days` | `.get_param()` with `sudo()` |
| `base.group_system` | Odoo base | Admin-only access in `ir.model.access.csv` | Locked decision; matches `access_ai_session_system` pattern in `ai` module |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `fields.Json` | `fields.Text` with JSON string | Text requires manual serialize/deserialize; Json gives native JSONB querying. User locked to Json. |
| `@api.autovacuum` | Explicit `ir.cron` record | Explicit cron requires XML data file and separate scheduling; autovacuum is simpler and auto-registered |
| `self.env.registry.cursor()` | `self.env.cr.savepoint()` | Savepoints are nested within the main transaction and roll back with it; separate cursor survives rollback |

---

## Architecture Patterns

### Recommended Module Structure

```
ai_debug/
├── __manifest__.py
├── __init__.py
├── models/
│   ├── __init__.py
│   ├── ai_debug_trace.py          # ai.debug.trace model
│   ├── ai_debug_iteration.py      # ai.debug.iteration model
│   ├── ai_debug_tool_call.py      # ai.debug.tool.call model
│   └── ai_session.py              # _inherit = 'ai.session'
├── security/
│   └── ir.model.access.csv
└── data/
    └── ir_cron.xml                # @api.autovacuum auto-registered; only needed if explicit cron preferred
```

Note: `@api.autovacuum` does NOT require an `ir_cron.xml` entry. The `ir.autovacuum` nightly cron calls all decorated methods automatically. No separate cron data file is needed for retention cleanup.

### Pattern 1: Generator Yield Passthrough

**What:** Override a generator method, wrap each yielded item with capture, then re-yield it unchanged.
**When to use:** Any time you need to observe items from a generator without changing what the consumer receives.

```python
# Source: verified against ai/models/ai_session.py in master-ai-update-records-adsc
class AiSessionDebug(models.TransientModel):
    _inherit = 'ai.session'

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, temperature, tools,
                          tools_context, record=None, schema=None, web_grounding=False):
        if not self.env["ir.config_parameter"].sudo().get_param("ai_debugger.enabled", "True"):
            yield from super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            )
            return

        trace = self._debug_open_trace(model, instructions, tools_context)
        iteration_index = 0
        iter_start = time.perf_counter()
        try:
            for item in super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            ):
                # Capture at natural yield points
                if 'metadata' in item and 'tool_calls' in item:
                    # LLM response with tool calls
                    self._debug_write_iteration(trace, iteration_index, messages, item, iter_start)
                    iteration_index += 1
                    iter_start = time.perf_counter()
                elif 'final_message' in item:
                    # Loop termination
                    self._debug_write_iteration(trace, iteration_index, messages, item, iter_start)
                    self._debug_close_trace(trace, 'done', iteration_index + 1)
                yield item
        except Exception as e:
            self._debug_close_trace(trace, 'error', iteration_index, error=str(e))
            raise
```

**Critical:** `_run_agentic_loop` is decorated `@api.model` in the base — the override must also be `@api.model`.

### Pattern 2: Separate Cursor Trace Write

**What:** Write to debug models using a fresh cursor so the write is committed independently of the main transaction.
**When to use:** Any instrumentation write that must survive a main-transaction rollback (e.g., if the loop raises UserError, we still want the error trace).

```python
# Source: verified against iap_extract/models/extract_mixin.py and ai/controllers/thread.py
def _debug_write_iteration(self, trace_id, index, messages, item, start_time):
    try:
        duration_ms = round((time.perf_counter() - start_time) * 1000)
        dbname = self.env.cr.dbname
        uid = self.env.uid
        context = dict(self.env.context)
        with self.env.registry.cursor() as cr:
            env = api.Environment(cr, uid, context)
            env['ai.debug.iteration'].create({
                'trace_id': trace_id,
                'index': index,
                'messages_sent': messages,  # Json field accepts list/dict directly
                'raw_response': item.get('metadata'),
                'duration_ms': duration_ms,
            })
            # cr commits automatically on context manager exit
    except Exception:
        _logger.warning("ai_debug: failed to write iteration record", exc_info=True)
```

**Important:** Access `self.env.cr.dbname`, `self.env.uid`, and `self.env.context` BEFORE opening the new cursor — the new cursor's `api.Environment` needs these values but the original cursor is still valid at this point.

### Pattern 3: `@api.autovacuum` Retention Cleanup

**What:** Automatically called by the nightly `ir.autovacuum` cron; no separate cron XML needed.
**When to use:** Any cleanup that should run on a schedule without requiring an explicit `ir.cron` record.

```python
# Source: verified against base/models/ir_autovacuum.py and appointment/models/appointment_invite.py
class AiDebugTrace(models.Model):
    _name = 'ai.debug.trace'

    @api.autovacuum
    def _gc_ai_debug_traces(self):
        retention_days = int(
            self.env["ir.config_parameter"].sudo().get_param("ai_debugger.retention_days", "7")
        )
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=retention_days)
        self.search([('create_date', '<=', cutoff)]).unlink()
```

### Pattern 4: Binary Content Stripping Before Json Storage

**What:** Walk the messages array before storing, replace base64 binary parts with a placeholder dict.
**When to use:** Any Json field write that may contain base64 content from image/PDF tool call args or message parts.

```python
# Source: Based on locked decision in CONTEXT.md + message format from ai_debugger.md
import re

def _debug_strip_binaries(self, messages):
    """Replace base64 binary content with size placeholder before storing."""
    import copy
    cleaned = copy.deepcopy(messages)
    for msg in cleaned:
        for part in msg.get('parts', []):
            content = part.get('content', '')
            if isinstance(content, str) and len(content) > 1000:
                # Heuristic: long strings in non-text parts are likely base64
                if part.get('type', 'text') != 'text':
                    # TODO: future enhancement — save to ir.attachment and link back
                    part['content'] = {'binary': part.get('type', 'unknown'), 'size': len(content)}
    return cleaned
```

### Pattern 5: Security CSV for Admin-Only Models

```csv
# Source: ai/security/ir.model.access.csv (verified against master-ai-update-records-adsc)
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_ai_debug_trace_system,ai.debug.trace admin,model_ai_debug_trace,base.group_system,1,1,1,1
access_ai_debug_iteration_system,ai.debug.iteration admin,model_ai_debug_iteration,base.group_system,1,1,1,1
access_ai_debug_tool_call_system,ai.debug.tool.call admin,model_ai_debug_tool_call,base.group_system,1,1,1,1
```

No user-level read access — admin only per locked decision.

### Anti-Patterns to Avoid

- **Using `self.env.cr.savepoint()` for isolation:** A savepoint is still inside the main transaction. If the main transaction rolls back (e.g., UserError from loop), the savepoint write is lost. Use `registry.cursor()`.
- **Inheriting as `models.Model` instead of `models.TransientModel` for the session override:** `ai.session` is a `TransientModel`. An `_inherit` on a TransientModel must also be TransientModel (or AbstractModel). Creating a new `models.Model` with `_inherit = 'ai.session'` is invalid — it would try to change the model type.
- **Storing messages as Text JSON strings:** Use `fields.Json` — it maps to PostgreSQL JSONB and avoids double-serialization.
- **Calling `super()` on a generator method and not re-yielding:** If you call `super()._run_agentic_loop()` without yielding from it, the upstream consumer (`_generate_next_response`) receives nothing and the loop silently stops.
- **Capturing `messages` value after `messages.extend(response)`:** The `messages` list is mutated in-place inside `_run_agentic_loop`. Snapshot before `get_completions()` per iteration, not after.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Millisecond timing | Custom `datetime` subtraction | `time.perf_counter()` × 1000 | Already used in `ai_api_service_openai.py`; sub-millisecond precision, monotonic |
| JSON field storage | `fields.Text` with `json.dumps()` | `fields.Json` | Native JSONB; ORM handles serialize/deserialize |
| Scheduled cleanup | Custom `ir.cron` XML record | `@api.autovacuum` | Auto-registered by `ir.autovacuum`; no extra XML |
| Transaction isolation | Nested savepoints | `self.env.registry.cursor()` | Savepoints roll back with main transaction |
| Config parameter reads | Custom config model | `ir.config_parameter.get_param()` | Standard Odoo config pattern; already used throughout `ai` module |

**Key insight:** All the infrastructure needed already exists in Odoo — the challenge is wiring it correctly, not building new primitives.

---

## Common Pitfalls

### Pitfall 1: Generator Method Decoration Mismatch

**What goes wrong:** `_run_agentic_loop` and `_get_direct_response` are decorated `@api.model`. The `_handle_tool_calls` is a regular instance method. Forgetting this in the override causes the ORM to dispatch incorrectly.
**Why it happens:** `@api.model` means the method doesn't need a record in `self`; forgetting it on the override changes the dispatch behavior.
**How to avoid:** Copy the exact decorator from the source: `_run_agentic_loop` → `@api.model`, `_handle_tool_calls` → no decorator (instance method), `_generate_next_response` → no decorator (instance method, has `self.ensure_one()` inside).
**Warning signs:** ORM raises `Expected singleton` or the method doesn't get called at all.

### Pitfall 2: Messages List Is Mutated In-Place

**What goes wrong:** Capturing `messages` for CAPT-04 after the loop iteration has already extended the list. The stored value includes tool responses from the current iteration instead of just the input.
**Why it happens:** `messages.extend(response)` and `messages.extend(tool_outputs)` are called inside `_run_agentic_loop` after each iteration.
**How to avoid:** Snapshot `messages` with `list(messages)` or `copy.copy(messages)` before calling `super()._run_agentic_loop()` for each iteration capture — or use the `messages` value from the yield payload itself (the `'metadata'` key contains the provider-formatted request/response).
**Warning signs:** Iteration records contain more messages than were actually sent to the LLM for that iteration.

### Pitfall 3: The Separate Cursor Holds a Stale Environment

**What goes wrong:** Passing `self.env.context` that contains a recordset (like `'guest': mail.guest(42)`) into the new cursor's environment. The recordset is bound to the original cursor; accessing it after the original cursor closes causes `Cursor already closed`.
**Why it happens:** Exactly this issue exists in `ai/controllers/thread.py` — the original code extracts `guest_id = context.get('guest').id` and passes the ID, not the recordset.
**How to avoid:** Strip recordset objects from context before creating the new environment. Pass only primitives: `{k: v for k, v in self.env.context.items() if not isinstance(v, models.BaseModel)}`.
**Warning signs:** `psycopg2.InterfaceError: cursor already closed` in instrumentation code.

### Pitfall 4: `_handle_tool_calls` State Snapshot Timing

**What goes wrong:** CAPT-11 requires state snapshots before and after tool execution. `tools_context['state']` is mutated by tools. If you snapshot after the entire `super()._handle_tool_calls()` generator exhausts, you only capture the final state, not per-tool-call snapshots.
**Why it happens:** The generator yields `tool_confirmation_request`, `tool_results`, and `final_message` events, but the state mutations happen inside the tool execution between yields.
**How to avoid:** Snapshot `tools_context['state']` at the start of each tool call iteration using `copy.deepcopy(tools_context['state'])` as the "before" snapshot. After `yield {'tool_results': ...}` passes through (which is emitted after all tools in a batch complete), snapshot again as "after". Per locked decision, snapshots are per tool call not per iteration.

### Pitfall 5: Enabled Check Must Use `get_param`, Not `get_bool`

**What goes wrong:** `ir.config_parameter` has `get_bool()` in some Odoo versions but the common reliable method is `get_param()`. The default for `ai_debugger.enabled` should be `"True"` (string), consistent with how other params work.
**Why it happens:** `get_bool()` was added later; some versions return `None` for unset params, which evaluates to `False` by default, silently disabling capture.
**How to avoid:** Use `get_param("ai_debugger.enabled", "True")` and compare to the string `"True"`, or cast with `bool(self.env["ir.config_parameter"].sudo().get_param("ai_debugger.enabled", True))` — check the exact version convention.
**Warning signs:** Instrumentation silently produces no records despite being "enabled."

### Pitfall 6: `_get_direct_response` Also Calls `_run_agentic_loop`

**What goes wrong:** The override of `_run_agentic_loop` captures traces for both the conversational path (`_add_user_message` → `_generate_next_response` → `_run_agentic_loop`) AND the one-shot path (`_get_direct_response` → `_run_agentic_loop`). This is intentional per CAPT-01's scope (which says "per agentic loop run"), but the trace record may lack agent context when called via `_get_direct_response` since there's no `self.agent_id`.
**Why it happens:** `_run_agentic_loop` is `@api.model` — it runs on an empty recordset. The override must handle `self` having no records (no `agent_id`, no `channel_id`).
**How to avoid:** In `_debug_open_trace`, check `self.ids` to determine whether there is a session record with agent context. Store `agent_id` and `llm_model` from method params, not from `self`.

---

## Code Examples

### Model Field Definitions

```python
# Source: Verified against ai/models/ai_session.py field patterns + locked decisions

class AiDebugTrace(models.Model):
    _name = 'ai.debug.trace'
    _description = 'AI Debug Trace'
    _order = 'create_date desc, id desc'

    # Agent context (may be None for _get_direct_response calls)
    agent_id = fields.Many2one('ai.agent', string='Agent', ondelete='set null', index=True)
    llm_model = fields.Char(string='LLM Model', index=True)

    # System prompt + RAG (captured from _generate_next_response)
    instructions = fields.Text(string='System Instructions')
    rag_context = fields.Text(string='RAG Context')

    # Loop outcome
    state = fields.Selection([
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('paused', 'Awaiting Confirmation'),
    ], string='State', default='running', index=True, required=True)
    termination_reason = fields.Char(string='Termination Reason')
    error_message = fields.Text(string='Error Message')

    # Timing
    start_time = fields.Datetime(string='Started', default=fields.Datetime.now)
    total_duration_ms = fields.Integer(string='Duration (ms)')
    iteration_count = fields.Integer(string='Iterations')

    iteration_ids = fields.One2many('ai.debug.iteration', 'trace_id', string='Iterations')


class AiDebugIteration(models.Model):
    _name = 'ai.debug.iteration'
    _description = 'AI Debug Iteration'
    _order = 'index asc'

    trace_id = fields.Many2one('ai.debug.trace', string='Trace', required=True,
                                ondelete='cascade', index=True)
    index = fields.Integer(string='Index', required=True)  # 0-based

    # Full LLM input/output (Json = JSONB, verbatim, no truncation)
    messages_sent = fields.Json(string='Messages Sent')
    raw_response = fields.Json(string='Raw Provider Response')

    # State snapshots at iteration level
    state_before = fields.Json(string='State Before')
    state_after = fields.Json(string='State After')

    # Termination
    final_message = fields.Json(string='Final Message')

    # Timing
    duration_ms = fields.Integer(string='Duration (ms)')

    tool_call_ids = fields.One2many('ai.debug.tool.call', 'iteration_id', string='Tool Calls')


class AiDebugToolCall(models.Model):
    _name = 'ai.debug.tool.call'
    _description = 'AI Debug Tool Call'
    _order = 'id asc'

    iteration_id = fields.Many2one('ai.debug.iteration', string='Iteration', required=True,
                                    ondelete='cascade', index=True)

    # Tool identity
    tool_name = fields.Char(string='Tool Name', index=True)
    call_id = fields.Char(string='Call ID')

    # Payload (Json = JSONB, verbatim)
    args = fields.Json(string='Arguments')
    result = fields.Text(string='Result')  # Text, not Json — result may be plain string
    success = fields.Boolean(string='Success', default=True)

    # Confirmation
    triggered_confirmation = fields.Boolean(string='Required Confirmation')
    confirmation_message = fields.Text(string='Confirmation Message')

    # State snapshots per tool call (locked decision)
    state_before = fields.Json(string='State Before')
    state_after = fields.Json(string='State After')

    # Timing
    duration_ms = fields.Integer(string='Duration (ms)')
```

### `__manifest__.py` Scaffold

```python
# Source: ai/__manifest__.py pattern adapted for custom module
{
    'name': 'AI Debug',
    'technical_name': 'ai_debug',
    'version': '1.0',
    'category': 'Technical',
    'summary': 'Instrument the AI agentic loop for full observability',
    'depends': ['ai'],
    'data': [
        'security/ir.model.access.csv',
    ],
    'installable': True,
    'application': False,   # No Apps grid tile
    'auto_install': False,
    'license': 'LGPL-3',
}
```

Note: No `ir_cron.xml` needed — `@api.autovacuum` is auto-registered. Menu XML is Phase 2 scope.

### Enabled Flag Check Pattern

```python
# Source: ir.config_parameter pattern from ai/models/ai_session.py lines 166, 387
def _is_debug_enabled(self):
    return self.env["ir.config_parameter"].sudo().get_param(
        "ai_debugger.enabled", "True"
    ) not in ("False", "false", "0", "")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `fields.Text` for JSON storage | `fields.Json` (JSONB) | Odoo 16/17 | Native querying, no double-serialization |
| Explicit `ir.cron` for cleanup | `@api.autovacuum` decorator | Odoo 16+ | Simpler, auto-registered |
| `savepoint()` for nested writes | `registry.cursor()` for isolation | Always been the pattern | Required for true transaction independence |

---

## Open Questions

1. **Which branch is the module targeting at install time?**
   - What we know: `PROJECT.md` references `master-ai-update-records-adsc`; `ai_session.py` in that branch is identical to `master-imp-ai-composable-prompts-jcb`. The `master` branch does NOT have `ai.session` at all.
   - What's unclear: Whether the module should depend on `ai` from the composable-prompts feature branch or wait for it to land on master.
   - Recommendation: The planner should note that the `ai.session` model must exist before `ai_debug` installs. The `depends = ['ai']` in `__manifest__.py` covers this but only if `ai` on the running instance has `ai.session`. This is a deployment constraint, not a code constraint.

2. **`_get_direct_response` trace attribution**
   - What we know: `_run_agentic_loop` is `@api.model` — called on an empty recordset with no `agent_id`.
   - What's unclear: Whether traces from `_get_direct_response` should be captured at all, or only traces from the conversational path (`_add_user_message`).
   - Recommendation: Capture both but make agent attribution optional (`ondelete='set null'`). Use `model` parameter and any context clues for identification. The `_generate_next_response` override captures agent context via `self.agent_id` and can pass a trace ID down to `_run_agentic_loop` via context.

3. **Savepoint vs cursor for per-tool-call writes within a single trace**
   - What we know: Claude's Discretion area per CONTEXT.md. Separate cursors give full isolation. Savepoints give partial rollback within main transaction.
   - What's unclear: Whether per-tool-call writes need to survive if the overall loop transaction rolls back (which would invalidate the trace entirely anyway).
   - Recommendation: Use a single separate cursor for the entire trace lifecycle (open at trace start, flush iteration/tool records as they complete, close at trace end). This avoids `n+1` cursor opens per tool call while still surviving loop rollbacks.

---

## Sources

### Primary (HIGH confidence)

- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py` — verified `_run_agentic_loop`, `_handle_tool_calls`, `_generate_next_response` method signatures, decorators, yield points
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/controllers/thread.py` — verified `Registry(dbname) + registry.cursor()` pattern for separate transaction within ai module
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/services/ai_api_service_openai.py` — verified `time.perf_counter()` timing pattern
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/security/ir.model.access.csv` — verified `base.group_system` pattern for admin-only access
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/ai/models/ai_session.py` — verified `fields.Json` usage for `metadata`, `state`, `pending_tools_results`
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/iap_extract/models/extract_mixin.py` — verified `@self.env.cr.postcommit.add` + `self.env.registry.cursor()` canonical pattern
- Source code: `/Users/joseph/clones/odoo/odoo/.worktrees/master/addons/google_calendar/models/google_sync.py` — verified `postcommit + Registry(dbname).cursor()` pattern
- Source code: `/Users/joseph/clones/odoo/odoo/.worktrees/master/odoo/addons/base/models/ir_autovacuum.py` — verified `@api.autovacuum` auto-registration mechanism
- Source code: `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-update-records-adsc/appointment/models/appointment_invite.py` — verified `@api.autovacuum` usage pattern

### Secondary (MEDIUM confidence)

- `/Users/joseph/clones/odoo/custom/ai_debugger.md` — preliminary design document with architecture diagram; used for message format reference and instrumentation point identification

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified in production Odoo source code
- Architecture patterns: HIGH — all patterns verified against multiple canonical examples in enterprise/core
- Pitfalls: HIGH — identified from direct source inspection of the target methods
- Field model design: HIGH — follows established patterns from `ai.session` and other Odoo models

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (stable — Odoo ORM APIs change slowly; re-verify if `ai.session` changes upstream)
