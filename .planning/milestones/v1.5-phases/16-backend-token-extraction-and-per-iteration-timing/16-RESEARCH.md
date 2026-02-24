# Phase 16: Backend Token Extraction and Per-Iteration Timing - Research

**Researched:** 2026-02-24
**Domain:** Python backend instrumentation — provider service layer patching, token normalization, per-iteration timing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Token field semantics**
- Schema: `{input, output, total, cached, reasoning}` — five fields
- `total` uses the raw value from the provider API (not computed from input + output)
- `cached` and `reasoning` are sparse — omitted when 0, only present when non-zero
- `input`, `output`, `total` are always present on successful iterations
- No additional token categories beyond these five — keep it minimal

**Duration scope**
- Three timing values per iteration: total duration, LLM API call duration, tool execution aggregate duration
- Total = LLM call + tool execution
- Tool execution duration is a single aggregate number at the iteration level (not per-tool-call)
- Individual tool call bus events also get their own `duration_ms` — captured in this phase
- Per-tool-call timing is already visible via tool call rows; iteration-level is the aggregate

**Provider-specific handling**
- Per-provider extractor functions (separate logic for OpenAI and Google)
- Degrade gracefully on unexpected/missing token data: log warning, default missing fields to 0
- Extract tokens from the final stream chunk only (not accumulated across chunks)
- On errored iterations (network timeout, 500, etc.): skip the tokens field entirely — absence signals failure
- Duration is still captured up to the failure point even on errors

**Bus event structure**
- Tokens as nested object: `tokens: {input: 150, output: 80, total: 230}` (cached/reasoning only when non-zero)
- Tokens field only on iteration events, not on tool call events
- Tool call events get `duration_ms` only
- Provider name included per iteration event (e.g. `provider: "openai"` or `provider: "google"`)

### Claude's Discretion
- Naming convention for timing fields (duration_ms, llm_ms, tools_ms or nested — Claude picks based on existing bus event conventions)
- Exact placement of timing hooks in the provider call stack
- How to handle the final stream chunk token extraction per provider
- Logging format for degraded token extraction warnings

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

## Summary

The enterprise `ai` module's provider service layer (`AIApiServiceOpenAI`, `AIApiServiceGoogle`) extracts token usage from the HTTP response body and logs it — but discards it before returning to the caller. The `get_completions()` methods return only the parsed content (output items for OpenAI, candidate content for Google), stripping the `usage`/`usageMetadata` envelope. By the time the agentic loop in `ai_session._run_agentic_loop()` yields an item, the token data is gone. This is the central architectural challenge of Phase 16.

The approved approach (from STATE.md decision) is to intercept at `AIApiService._request()` using `threading.local()` to side-channel token data back to the instrumentation layer — captured in a new file `ai_provider_patch.py`. This avoids modifying enterprise code and works within the existing `_inherit` pattern. Timing is simpler: `time.monotonic()` hooks wrap the `get_completions()` call in the `_run_agentic_loop` override already in `ai_session.py`.

Both providers already exist and their raw API response shapes are verified in the codebase. OpenAI uses `response['usage']` with `input_tokens`, `output_tokens`, `total_tokens`, plus nested `input_tokens_details.cached_tokens` and `output_tokens_details.reasoning_tokens`. Google uses `response['usageMetadata']` with `promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`, `cachedContentTokenCount`, `thoughtsTokenCount`. Normalization to the canonical `{input, output, total, cached, reasoning}` schema is deterministic.

**Primary recommendation:** Use `threading.local()` in a new `ai_provider_patch.py` that monkey-patches (or subclasses) `AIApiService._request` to stash the last completion response into a thread-local; read that stash in the `_run_agentic_loop` override immediately after `get_completions()` returns; clear it after reading. Timing uses `time.monotonic()` before and after `provider.get_service(...).get_completions(...)` inside the existing `_run_agentic_loop` override.

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOKN-01 | Backend extracts normalized token usage from OpenAI API responses (input, output, total, cached, reasoning) | OpenAI raw response verified: `response['usage']` with `input_tokens`, `output_tokens`, `total_tokens`, `input_tokens_details.cached_tokens`, `output_tokens_details.reasoning_tokens` |
| TOKN-02 | Backend extracts normalized token usage from Google API responses (input, output, total, cached, reasoning) | Google raw response verified: `response['usageMetadata']` with `promptTokenCount`, `candidatesTokenCount`, `totalTokenCount`, `cachedContentTokenCount`, `thoughtsTokenCount` |
| TOKN-03 | Iteration bus events include a `tokens` field with the normalized schema `{input, output, total, cached, reasoning}` | Iteration bus event emitted in `_run_agentic_loop` override; `tokens` dict added alongside existing fields |
| TOKN-04 | Missing token fields default to 0 so JS rendering is provider-agnostic | Extractor functions return `{input: 0, output: 0, total: 0}` minimum; sparse fields omitted when 0 |
| TIME-01 | Backend captures per-iteration duration via `time.monotonic()` and emits `duration_ms` on iteration bus events | `time.monotonic()` already imported in `ai_session.py`; wrap `get_completions()` call in override |
| TIME-02 | Trace-level total duration surfaced from existing `loop_end.duration_ms` field | Already present in `loop_end` bus event (`duration_ms: int((time.monotonic() - started_at) * 1000)`); no code change needed — requirement is satisfied by existing code |
</phase_requirements>

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `threading` | stdlib | Thread-local storage for side-channel token data | Only safe way to pass data from `_request()` to caller without modifying return type |
| `time` | stdlib | `time.monotonic()` for wall-clock duration measurement | Already used in `ai_session.py` (loop-level timing); consistent |
| `logging` | stdlib | Warn on missing/unexpected token data | Already the project pattern (`_logger.exception`, `_logger.warning`) |

### Supporting

None — this phase is pure Python instrumentation, no new dependencies.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `threading.local()` side-channel | Subclass `AIApiServiceOpenAI`/`AIApiServiceGoogle` and override `get_completions()` | Subclassing is cleaner but requires `AIProvider.get_service()` to return the subclass, which needs enterprise code modification — off limits |
| `threading.local()` side-channel | Modify `get_completions()` return type to include tokens | Clean but modifies enterprise `ai` module — off limits |
| `threading.local()` side-channel | Patch `_request()` at class level in `ai_provider_patch.py` | This IS the approved approach — patch once at module load, affects all instances |

---

## Architecture Patterns

### Recommended Project Structure

```
ai_debug/
├── models/
│   ├── __init__.py          # add: from . import ai_provider_patch
│   ├── ai_session.py        # modify: add timing + token extraction
│   ├── ai_provider_patch.py # NEW: threading.local() patch on AIApiService._request
│   ├── ai_agent.py          # no change
│   └── ir_websocket.py      # no change
```

### Pattern 1: threading.local() Side-Channel for Token Interception

**What:** Monkey-patch `AIApiService._request` to store the last completion response in a thread-local before returning. The caller (`get_completions`) returns only parsed content, but the thread-local retains the full HTTP envelope for the instrumentation layer to read.

**When to use:** When you need data from inside a call stack that strips it before returning, and you cannot modify the callee's return type.

**Example:**
```python
# ai_debug/models/ai_provider_patch.py
import threading
import logging
from odoo.addons.ai.services.ai_api_service import AIApiService

_logger = logging.getLogger(__name__)
_ai_debug_local = threading.local()


def _patched_request(self, method, endpoint, body, **kwargs):
    result = _original_request(self, method, endpoint, body, **kwargs)
    # Only stash completion responses — identified by endpoint pattern
    if 'generateContent' in endpoint or endpoint.strip('/').endswith('responses'):
        _ai_debug_local.last_completion_response = result
    return result


_original_request = AIApiService._request
AIApiService._request = _patched_request


def pop_last_token_data():
    """Return and clear the stashed completion response, or None."""
    return getattr(_ai_debug_local, 'last_completion_response', None).__class__  # placeholder
```

**Critical detail:** The patch must run at module load time. Import `ai_provider_patch` from `models/__init__.py` so it executes during Odoo startup.

**Critical detail 2:** The endpoint check must be resilient — check both `/responses` (OpenAI) and `:generateContent` (Google) patterns. Embedding and transcription endpoints must NOT be captured.

### Pattern 2: Token Normalization — Per-Provider Extractor Functions

**What:** Two pure functions that accept the raw HTTP response dict and return the canonical `{input, output, total}` dict, plus optional `cached` and `reasoning` when non-zero.

**OpenAI raw response shape (verified in `ai_api_service_openai.py` lines 86-94):**
```python
# response['usage'] structure from OpenAI Responses API
{
    'input_tokens': 150,
    'output_tokens': 80,
    'total_tokens': 230,
    'input_tokens_details': {'cached_tokens': 0},
    'output_tokens_details': {'reasoning_tokens': 0},
}
```

**Google raw response shape (verified in `ai_api_service_google.py` lines 75-83):**
```python
# response['usageMetadata'] structure from Gemini API
{
    'promptTokenCount': 150,
    'candidatesTokenCount': 80,
    'totalTokenCount': 230,
    'cachedContentTokenCount': 0,
    'thoughtsTokenCount': 0,
}
```

**Extractor pattern:**
```python
def _extract_tokens_openai(raw_response):
    """Normalize OpenAI usage to canonical schema. Returns None on missing data."""
    try:
        usage = raw_response.get('usage')
        if not usage:
            return None
        tokens = {
            'input': usage.get('input_tokens', 0),
            'output': usage.get('output_tokens', 0),
            'total': usage.get('total_tokens', 0),
        }
        details_in = usage.get('input_tokens_details', {})
        details_out = usage.get('output_tokens_details', {})
        if cached := details_in.get('cached_tokens', 0):
            tokens['cached'] = cached
        if reasoning := details_out.get('reasoning_tokens', 0):
            tokens['reasoning'] = reasoning
        return tokens
    except Exception:
        _logger.warning("ai_debug: failed to extract OpenAI token data", exc_info=True)
        return None


def _extract_tokens_google(raw_response):
    """Normalize Google usageMetadata to canonical schema. Returns None on missing data."""
    try:
        usage = raw_response.get('usageMetadata')
        if not usage:
            return None
        tokens = {
            'input': usage.get('promptTokenCount', 0),
            'output': usage.get('candidatesTokenCount', 0),
            'total': usage.get('totalTokenCount', 0),
        }
        if cached := usage.get('cachedContentTokenCount', 0):
            tokens['cached'] = cached
        if reasoning := usage.get('thoughtsTokenCount', 0):
            tokens['reasoning'] = reasoning
        return tokens
    except Exception:
        _logger.warning("ai_debug: failed to extract Google token data", exc_info=True)
        return None
```

### Pattern 3: Per-Iteration Timing in _run_agentic_loop Override

**What:** Wrap the `get_completions()` call with `time.monotonic()` before and after; separately track tool execution aggregate duration; add all three to the iteration bus event.

**Where:** In the existing `_run_agentic_loop` override in `ai_debug/models/ai_session.py`. The override already has the `for item in super()._run_agentic_loop(...)` loop — timing must be added inside this override.

**Challenge:** The existing override calls `super()._run_agentic_loop()` as a generator. The actual `get_completions()` call happens inside `super()`'s loop body, which is opaque to our override. We cannot wrap just the `get_completions()` call from outside.

**Solution:** Use the thread-local approach consistently — stash timing alongside tokens in the patched `_request()` call, or add a second timing hook. Since the `_request()` patch is already needed for tokens, add `start_time`/`end_time` to `_ai_debug_local` there too. This gives LLM API call duration directly from the HTTP round-trip.

**Alternatively:** Track timing at the iteration level in the override by noting `time.monotonic()` just before `yield from super()` — but this doesn't split LLM vs tool execution. The cleaner split comes from the `_request()` patch.

**Timing approach (preferred — consistent with token approach):**
```python
# In _patched_request (ai_provider_patch.py):
import time

def _patched_request(self, method, endpoint, body, **kwargs):
    is_completion = 'generateContent' in endpoint or endpoint.strip('/').endswith('responses')
    if is_completion:
        t0 = time.monotonic()
    result = _original_request(self, method, endpoint, body, **kwargs)
    if is_completion:
        _ai_debug_local.last_completion_response = result
        _ai_debug_local.last_llm_duration_ms = int((time.monotonic() - t0) * 1000)
    return result
```

**For tool execution aggregate:** Track `time.monotonic()` around the tool-call segment in the override. The existing override yields items from `super()`, so we can detect when `tool_calls` items arrive vs `final_message` — but the tool execution happens inside the generator. This requires timing hooks around `_handle_tool_calls` which is also overridden. Add timing tracking to `_handle_tool_calls` override: record start time before `super()._handle_tool_calls()` delegation, record end time after it completes.

**Naming convention recommendation (Claude's discretion):** Use flat fields matching existing `loop_end` convention (`duration_ms`):
- `duration_ms` — total iteration duration (LLM + tools)
- `llm_duration_ms` — HTTP round-trip to LLM API
- `tool_duration_ms` — aggregate tool execution time

This mirrors the existing `loop_end.duration_ms` naming and keeps fields at the top level (not nested), consistent with all existing bus event fields.

### Pattern 4: Tool Call duration_ms

**What:** Each `tool_call_completed` event needs `duration_ms` (per CONTEXT.md locked decision). The `_handle_tool_calls` override already fires `tool_call_started` before execution and `tool_call_completed` after. Add `time.monotonic()` between them per tool.

**Current `_handle_tool_calls` override structure:**
```python
# Currently emits tool_call_started for all tools in batch BEFORE execution
for tc in tool_calls:
    self._ai_debug_bus_send('tool_call_started', {...})

# Then iterates super()._handle_tool_calls() results
for item in super()._handle_tool_calls(...):
    if tool_results := item.get('tool_results'):
        for result_item in tool_results:
            self._ai_debug_bus_send('tool_call_completed', {...})  # no duration_ms
```

**Issue:** Started events are batch-fired before any tool runs; completed events fire after `super()` yields batch results. Cannot measure per-tool timing this way.

**Solution:** Stash per-tool start time in a dict keyed by `call_id` immediately before `super()` delegation, then compute duration when `tool_call_completed` fires. Since `super()` is synchronous (not async), tracking needs the thread-local or a mutable dict in the closure.

**Practical approach:** Add `_tc_start_times = {tc['call_id']: time.monotonic() for tc in tool_calls}` immediately before the `super()._handle_tool_calls()` call (after the started events are fired), then `duration_ms = int((time.monotonic() - _tc_start_times.get(call_id, 0)) * 1000)` in the completed handler.

**Note:** This overestimates individual tool duration slightly (batch overhead), but is accurate enough — the user decision says "aggregate tool execution duration" at iteration level and "per-tool-call duration" in the tool call row.

### Anti-Patterns to Avoid

- **Do not store tokens in `_debug_ctx`** — `_debug_ctx` is shared across iterations; token data is per-iteration and must be read and cleared immediately after each `get_completions()` call to avoid cross-contamination
- **Do not use `environ` or request context** — `threading.local()` is the correct thread-safe mechanism for Odoo worker processes
- **Do not call `pop_last_token_data()` in a finally block shared across iterations** — call it synchronously right after the iteration event that triggered the token extraction
- **Do not apply the endpoint filter too broadly** — `_request()` is called for embeddings and transcription too; only stash for completion endpoints
- **Do not assume `total_tokens` exists on OpenAI** — the Responses API may not always include `total_tokens` in `usage`; compute from input + output as fallback if `total` is missing (but CONTEXT says use raw value — so if missing, default to 0 per TOKN-04)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Thread-safe storage | Custom lock-based dict | `threading.local()` | stdlib, zero overhead, per-thread by design, no locking needed |
| Timing | Custom time tracking class | `time.monotonic()` | stdlib, monotonic (immune to NTP/clock adjustments), already used in codebase |
| Provider identification | String parsing of model names | Read from existing `AIProvider.name` attribute | `AIProviderOpenAI.name = "openai"`, `AIProviderGoogle.name = "google"` — already on the provider object |

**Key insight:** The hardest part of this phase is not the normalization math — it is getting the raw HTTP response into the instrumentation layer without touching enterprise code. `threading.local()` is the only mechanism that works within the `_inherit` constraint.

---

## Common Pitfalls

### Pitfall 1: Cross-Iteration Token Contamination
**What goes wrong:** Thread-local is read after `get_completions()` returns, but if two agentic loop iterations run on the same thread (they do — synchronous loop), the previous iteration's token data may linger if not explicitly cleared.
**Why it happens:** `threading.local` persists across calls on the same thread. A fast second iteration reads the previous stash if the second `get_completions()` call fails before the response patch runs.
**How to avoid:** Clear `_ai_debug_local.last_completion_response = None` immediately after reading it in the instrumentation layer. Use a pop-style function.
**Warning signs:** Two consecutive iterations show identical token counts.

### Pitfall 2: Embedding/Transcription Endpoint Capture
**What goes wrong:** `_request()` is called for embeddings (`/embeddings`, `:embedContent`, `:batchEmbedContents`) and transcription (`/audio/transcriptions`) too. These responses have no `usage` field and are not LLM completions.
**Why it happens:** The patch is on the base class method, shared by all subclasses.
**How to avoid:** Endpoint filter: only stash when `endpoint` contains `generateContent` or ends with `responses`. Verify the OpenAI endpoint is `/responses` (confirmed: `self._request("post", "/responses", ...)` in `AIApiServiceOpenAI.get_completions`).
**Warning signs:** Token extraction warnings logged on embedding operations.

### Pitfall 3: `total_tokens` Missing from OpenAI Response
**What goes wrong:** Older OpenAI models or the Responses API may return `usage` without `total_tokens`.
**Why it happens:** OpenAI API response shape varies by endpoint/model.
**How to avoid:** Always `.get('total_tokens', 0)` — if `total_tokens` is missing and per TOKN-04 missing fields default to 0. Do not compute `input + output` as substitute (CONTEXT.md: "total uses the raw value from the provider API").
**Warning signs:** `total` always shows 0 despite non-zero input/output — investigate API response shape.

### Pitfall 4: Patch Not Running at Startup
**What goes wrong:** `ai_provider_patch.py` is imported too late (after first request), so the first LLM call is unpatched.
**Why it happens:** Odoo lazy-imports model files; if not added to `models/__init__.py`, the patch never runs.
**How to avoid:** Add `from . import ai_provider_patch` to `models/__init__.py`. The patch executes at import time.
**Warning signs:** First iteration of any trace has no tokens; subsequent ones do.

### Pitfall 5: Loop-Level vs Iteration-Level timing
**What goes wrong:** Phase is expected to emit `duration_ms` per iteration, but `loop_end.duration_ms` (already present) measures the full trace.
**Why it happens:** Loop-level timing is already implemented; iteration-level is the new requirement.
**How to avoid:** The existing `started_at = time.monotonic()` is loop-level. Add iteration-level tracking inside the iteration detection block in `_run_agentic_loop` override. These are independent measurements.
**Warning signs:** All iterations show the same `duration_ms` equal to total trace duration.

### Pitfall 6: TIME-02 Is Already Satisfied
**What goes wrong:** Planner creates a task to implement `loop_end.duration_ms` — but it already exists.
**Why it happens:** REQUIREMENTS.md says TIME-02 is pending, but `_run_agentic_loop` already emits `duration_ms` in `loop_end`.
**How to avoid:** TIME-02 only needs verification (confirm field name and value), not implementation. No code change required. A single verification task is sufficient.
**Warning signs:** N/A — this is a planning concern, not a runtime concern.

---

## Code Examples

Verified patterns from official codebase:

### Existing loop_end duration_ms (already implemented — TIME-02 satisfied)
```python
# ai_debug/models/ai_session.py lines 256-263
self._ai_debug_bus_send('loop_end', {
    'type': 'loop_end',
    'trace_id': trace_id,
    'termination_reason': termination_reason,
    'error': termination_error,
    'iteration_count': iteration_count,
    'tool_call_count': _debug_ctx['tool_call_count'],
    'duration_ms': int((time.monotonic() - started_at) * 1000),  # ← already present
})
```

### OpenAI token field names (verified in ai_api_service_openai.py lines 86-94)
```python
# OpenAI Responses API — response['usage'] shape
usage = response.get('usage')
# Keys: input_tokens, output_tokens, total_tokens
# Nested: input_tokens_details.cached_tokens, output_tokens_details.reasoning_tokens
```

### Google token field names (verified in ai_api_service_google.py lines 75-83)
```python
# Gemini API — response['usageMetadata'] shape
usage = response.get('usageMetadata')
# Keys: promptTokenCount, candidatesTokenCount, totalTokenCount
# Sparse: cachedContentTokenCount, thoughtsTokenCount
```

### Existing iteration bus event (where tokens + timing will be added)
```python
# ai_debug/models/ai_session.py lines 199-208
self._ai_debug_bus_send('iteration', {
    'type': 'iteration',
    'trace_id': trace_id,
    'iteration_id': iteration_id,
    'iteration_index': iteration_count,
    'messages_sent': messages_snapshot,
    'raw_response': item.get('metadata'),
    'has_tool_calls': 'tool_calls' in item,
    'is_final': 'final_message' in item,
    # ← ADD: 'tokens': {...}, 'duration_ms': N, 'llm_duration_ms': N, 'tool_duration_ms': N, 'provider': 'openai'|'google'
})
```

### Provider name extraction (already available on AIProvider subclasses)
```python
from odoo.addons.ai.services.ai_provider import AIProvider
provider = AIProvider.get_by_model(self.env, model)
provider_name = provider.name  # "openai" or "google"
```

### threading.local() pattern (stdlib)
```python
import threading
_local = threading.local()

# In patched _request():
_local.last_completion = response_dict  # stash

# In consumer:
raw = getattr(_local, 'last_completion', None)
_local.last_completion = None  # clear immediately
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tokens only in logs | Tokens in bus events | Phase 16 (this phase) | Frontend can display per-iteration token counts |
| No per-iteration timing | `duration_ms` on iteration events | Phase 16 (this phase) | Frontend can display iteration latency |
| Loop-level timing only | Loop + per-iteration timing | Phase 16 (this phase) | Full timing breakdown available |

**Existing (not deprecated):**
- `loop_end.duration_ms` — already implemented, represents full trace duration

---

## Open Questions

1. **Does the OpenAI Responses API always return `total_tokens` in `usage`?**
   - What we know: The existing log at line 87-94 reads `usage.get('output_tokens', 0)` suggesting `total_tokens` may sometimes be absent (it logs input/output but not total)
   - What's unclear: Whether `total_tokens` is consistently present in the Responses API (vs Chat Completions API)
   - Recommendation: Default to `usage.get('total_tokens', 0)` per TOKN-04; if consistently 0, investigate. The CONTEXT.md decision explicitly says to use the raw value, not compute it.

2. **Endpoint filter reliability for future providers**
   - What we know: Currently only OpenAI (`/responses`) and Google (`:generateContent`) are active providers
   - What's unclear: If a new provider is added with a different endpoint pattern, the filter will miss it
   - Recommendation: Document the endpoint filter as requiring update when new providers are added. No action needed for Phase 16.

3. **Tool call timing granularity for parallel tool calls**
   - What we know: Odoo's agentic loop executes tool calls sequentially (synchronous generator); batching is by iteration not by parallelism
   - What's unclear: Whether `_handle_tool_calls` ever executes tools in parallel (check `_ai_tool_run`)
   - Recommendation: Assume sequential for now. The `_tc_start_times` dict approach works correctly for sequential execution. If parallel execution exists, timing will overestimate (acceptable per CONTEXT.md — "aggregate" is the requirement).

---

## Sources

### Primary (HIGH confidence)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_openai.py` — OpenAI `get_completions()` implementation, `usage` field names at lines 86-94
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service_google.py` — Google `get_completions()` implementation, `usageMetadata` field names at lines 75-83
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/services/ai_api_service.py` — `AIApiService._request()` method signature (lines 82-141)
- `/Users/joseph/clones/odoo/enterprise/.worktrees/master-ai-sub-agents-dpro/ai/models/ai_session.py` — `_run_agentic_loop()` method and `get_completions()` call site (lines 402-437)
- `/Users/joseph/clones/odoo/custom/.worktrees/master-ai-sub-agents-dpro/ai_debug/models/ai_session.py` — existing iteration bus event, `loop_end.duration_ms`, override structure (full file)
- `.planning/STATE.md` line 34 — confirmed decision: "must patch `AIApiService._request` via `threading.local()` in a new `ai_provider_patch.py` file"

### Secondary (MEDIUM confidence)
None required — all findings are directly verified from codebase.

### Tertiary (LOW confidence)
None.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib only, verified usage in codebase
- Architecture: HIGH — token field names directly verified in provider files; threading.local pattern is stdlib-documented
- Pitfalls: HIGH — derived from direct code reading, not speculation

**Research date:** 2026-02-24
**Valid until:** Stable — depends on enterprise `ai` module provider files which change infrequently; re-verify if new providers added
