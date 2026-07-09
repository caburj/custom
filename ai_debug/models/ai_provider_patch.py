"""Monkey-patch AIApiService._execute_prepared_request to capture LLM completions.

The patch intercepts the env-free HTTP phase of the completion pipeline so the
agentic-loop instrumentation in ai_session can read token usage, per-iteration
LLM call duration, and the raw HTTP request body after every iteration. Captured
values are stashed on the shared ``ai_debug_tracker`` thread-local (see
agent_runtime_tracker) and retrieved via ``pop_last_completion_data``.

``_execute_prepared_request`` (not ``_request``) is the seam because the tick
split routes every completion through the three-phase pipeline
(``_prepare_completion_request`` -> ``_execute_prepared_request`` ->
``_finalize_completion_response``); the socket call lives in the middle phase,
which ``requests.request`` performs directly, never via ``_request``. Capturing
here is the only way to read token data without modifying enterprise code:
``get_completions`` strips usage before returning to the loop.

This same-thread capture serves the sync one-shot and the single-frame tick
(both run the pipeline on the thread that instruments the iteration). The
production LLM batch runs the pipeline in a bare worker thread instead, so its
persist seam reads the request/response off the ``call`` bundle rather than this
thread-local (see ai_session ``_persist_llm_reply``). The stash still runs on the
worker thread, but no iteration hook is installed there so it is inert.

Token extraction is provider-specific (OpenAI ``usage`` vs Google
``usageMetadata``); keeping the helpers here keeps all provider-format
knowledge in one place.

The patch is applied at module load time (bottom of this file). It is
imported as the first item in ai_debug/models/__init__.py so it runs before
any provider service is instantiated.
"""
import logging

from odoo.addons.ai.services.ai_api_service import AIApiService
from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker

_logger = logging.getLogger(__name__)

# Preserve the original (env-free) executor so the patch can delegate to it.
# Accessing the staticmethod on the class yields the plain underlying function.
_original_execute_prepared_request = AIApiService._execute_prepared_request


def _patched_execute_prepared_request(prepared):
    """Instrumented replacement for AIApiService._execute_prepared_request.

    For completion requests (URL /responses or :generateContent), records the
    raw JSON response and the LLM API call duration (already measured by the
    executor) on the shared tracker so pop_last_completion_data() can retrieve
    them after each iteration. Any non-completion prepared request is passed
    through unchanged (``_execute_prepared_request`` is completion-only today;
    the URL guard keeps this robust if that ever widens).

    Instrumentation failures are caught and logged -- the call result is always
    returned normally regardless.
    """
    url = prepared.get('url', '') if isinstance(prepared, dict) else ''
    is_completion = url.strip('/').endswith('responses') or 'generateContent' in url
    if not is_completion:
        return _original_execute_prepared_request(prepared)

    # Completion path: stash the request body BEFORE the call so it is available
    # even if the request fails.
    #
    # SNAPSHOT the message list(s) at request time: the single-frame tick reuses
    # ONE `messages` list per step and extends it in place (the assistant event,
    # then the tool outputs) AFTER this call returns. The provider builds its
    # request body around that same list by reference, so a bare `= body` would
    # let those later in-place appends grow the captured `input`/`contents` — the
    # per-iteration `messages_sent` would then read the POST-tool-batch history
    # instead of what was actually sent. Freezing the top-level lists here keeps
    # `messages_sent` == the request as sent; item dicts are shared (never mutated
    # in place, only appended).
    body = prepared.get('body') if isinstance(prepared, dict) else None
    if isinstance(body, dict):
        snapshot = dict(body)
        for _k, _v in snapshot.items():
            if isinstance(_v, list):
                snapshot[_k] = list(_v)
        ai_debug_tracker.last_request_body = snapshot
    else:
        ai_debug_tracker.last_request_body = body

    # Give the agentic-loop instrumentation a chance to create a pending
    # iteration row before the (potentially long) HTTP call begins, so the
    # frontend can render a spinner for the in-flight iteration instead of
    # only seeing it pop in after the response arrives. None on the batch worker
    # thread (no hook installed there) -> skipped.
    start_hook = ai_debug_tracker.iteration_start_hook
    if start_hook is not None:
        try:
            start_hook()
        except Exception:
            _logger.warning(
                "ai_debug: iteration_start_hook failed",
                exc_info=True,
            )

    result = _original_execute_prepared_request(prepared)

    try:
        # The executor returns {ok, raw_response, duration_ms} on success and a
        # structured error dict (no raw_response) on failure — leave the response
        # unstashed on failure so a failed iteration surfaces the request only.
        if isinstance(result, dict) and result.get('ok'):
            ai_debug_tracker.last_completion_response = result.get('raw_response')
            ai_debug_tracker.last_llm_duration_ms = result.get('duration_ms')
    except Exception:
        _logger.warning(
            "ai_debug: failed to stash completion response on tracker",
            exc_info=True,
        )

    return result


# Apply the patch at module load time. Keep it a staticmethod so callers that
# reach it via the class (the LLM batch) or an instance (get_completions) both
# invoke it with the single ``prepared`` argument.
AIApiService._execute_prepared_request = staticmethod(_patched_execute_prepared_request)


def _extract_tokens_openai(raw_response):
    """Extract normalized token data from an OpenAI /responses response dict.

    Returns a canonical dict ``{input, output, total}`` with optional sparse
    fields ``cached`` and ``reasoning`` (only present when non-zero).

    Returns None if the ``usage`` key is absent or extraction fails.
    """
    try:
        usage = raw_response.get('usage')
        if usage is None:
            return None

        tokens = {
            'input': usage.get('input_tokens', 0),
            'output': usage.get('output_tokens', 0),
            'total': usage.get('total_tokens', 0),
        }

        # Sparse fields -- only include when non-zero.
        if cached := usage.get('input_tokens_details', {}).get('cached_tokens', 0):
            tokens['cached'] = cached
        if reasoning := usage.get('output_tokens_details', {}).get('reasoning_tokens', 0):
            tokens['reasoning'] = reasoning

        return tokens

    except Exception:
        _logger.warning(
            "ai_debug: failed to extract OpenAI token data",
            exc_info=True,
        )
        return None


def _extract_tokens_google(raw_response):
    """Extract normalized token data from a Google :generateContent response dict.

    Returns a canonical dict ``{input, output, total}`` with optional sparse
    fields ``cached`` and ``reasoning`` (only present when non-zero).

    Returns None if the ``usageMetadata`` key is absent or extraction fails.
    """
    try:
        usage = raw_response.get('usageMetadata')
        if usage is None:
            return None

        tokens = {
            'input': usage.get('promptTokenCount', 0),
            'output': usage.get('candidatesTokenCount', 0),
            'total': usage.get('totalTokenCount', 0),
        }

        # Sparse fields -- only include when non-zero.
        if cached := usage.get('cachedContentTokenCount', 0):
            tokens['cached'] = cached
        if reasoning := usage.get('thoughtsTokenCount', 0):
            tokens['reasoning'] = reasoning

        return tokens

    except Exception:
        _logger.warning(
            "ai_debug: failed to extract Google token data",
            exc_info=True,
        )
        return None


def pop_last_completion_data():
    """Retrieve and clear the most recent completion response, LLM duration, and request body.

    Called by the ai_session iteration finalizers (the single-frame/sync path via
    ``_ai_debug_finalize_iteration``, the CRON1 persist seam via
    ``_persist_llm_reply``) after each model round. The tracker fields are cleared
    immediately after reading to prevent cross-iteration contamination.

    Returns a dict with four keys:
      - ``tokens``: canonical ``{input, output, total}`` dict (with optional
        ``cached``/``reasoning``) if extraction succeeded, else ``None``.
      - ``llm_duration_ms``: integer milliseconds of the LLM API call, or
        ``None`` if unavailable (e.g. the request raised before timing was set).
      - ``request_body``: the raw dict passed to the HTTP layer (provider-specific
        format: model + messages + tools + generation config), or ``None`` if
        unavailable. This is the genuine serialized request envelope.
      - ``raw_response``: the genuine provider HTTP response dict (the parsed
        JSON the LLM API returned), or ``None`` if unavailable. Distinct from the
        agentic loop's ``item['metadata']`` (which is a post-processed/formatted
        view); this is what the provider actually sent back.

    Never raises -- callers rely on graceful degradation.
    """
    try:
        raw_response = ai_debug_tracker.last_completion_response
        llm_duration_ms = ai_debug_tracker.last_llm_duration_ms
        request_body = ai_debug_tracker.last_request_body

        # Clear immediately -- must happen before any further processing so that
        # a second call within the same thread (or a yielded sub-iteration) does
        # not see stale data from a previous iteration.
        ai_debug_tracker.last_completion_response = None
        ai_debug_tracker.last_llm_duration_ms = None
        ai_debug_tracker.last_request_body = None

        if raw_response is None:
            return {
                'tokens': None, 'llm_duration_ms': llm_duration_ms,
                'request_body': request_body, 'raw_response': None,
            }

        # Detect provider by examining which top-level key is present.
        # OpenAI uses 'usage'; Google uses 'usageMetadata'.
        if 'usage' in raw_response:
            tokens = _extract_tokens_openai(raw_response)
        elif 'usageMetadata' in raw_response:
            tokens = _extract_tokens_google(raw_response)
        else:
            tokens = None

        return {
            'tokens': tokens, 'llm_duration_ms': llm_duration_ms,
            'request_body': request_body, 'raw_response': raw_response,
        }

    except Exception:
        _logger.warning(
            "ai_debug: pop_last_completion_data failed unexpectedly",
            exc_info=True,
        )
        return {
            'tokens': None, 'llm_duration_ms': None,
            'request_body': None, 'raw_response': None,
        }
