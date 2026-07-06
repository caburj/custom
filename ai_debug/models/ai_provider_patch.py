"""Monkey-patch AIApiService._request to capture LLM completion responses.

The patch intercepts the low-level HTTP layer so the agentic-loop
instrumentation in ai_session can read token usage, per-iteration LLM call
duration, and the raw HTTP request body after every iteration. Captured
values are stashed on the shared ``ai_debug_tracker`` thread-local (see
agent_runtime_tracker) and retrieved via ``pop_last_completion_data``.

Token extraction is provider-specific (OpenAI ``usage`` vs Google
``usageMetadata``); keeping the helpers here keeps all provider-format
knowledge in one place.

Intercepting _request is the only way to access token data without modifying
enterprise code: get_completions() in each provider strips usage data before
returning to the agentic loop.

The patch is applied at module load time (bottom of this file). It is
imported as the first item in ai_debug/models/__init__.py so it runs before
any provider service is instantiated.
"""
import logging
import time

from odoo.addons.ai.services.ai_api_service import AIApiService
from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker

_logger = logging.getLogger(__name__)

# Preserve the original _request so the patch can delegate to it.
_original_request = AIApiService._request


def _patched_request(self, method, endpoint, body, **kwargs):
    """Instrumented replacement for AIApiService._request.

    For completion endpoints (/responses, :generateContent), records the raw
    JSON response and wall-clock LLM API call duration on the shared tracker
    so pop_last_completion_data() can retrieve them after each iteration.

    All other endpoints (embeddings, transcriptions, etc.) are passed through
    unchanged.

    Instrumentation failures are caught and logged -- the LLM call result is
    always returned normally regardless.
    """
    # Only intercept completion endpoints.
    # OpenAI: endpoint == "/responses"
    # Google: endpoint contains ":generateContent"
    is_completion = (
        endpoint.strip('/').endswith('responses')
        or 'generateContent' in endpoint
    )

    if not is_completion:
        return _original_request(self, method, endpoint, body, **kwargs)

    # Completion path: stash request body, time the call, and stash the raw response.
    # Request body is captured BEFORE the call so it's available even if the request fails.
    #
    # SNAPSHOT the message list(s) at request time: the straight-line
    # `_advance_one_step` reuses ONE `messages` list per step and extends it in
    # place (the assistant event, then the tool outputs) AFTER this call returns.
    # The provider builds its request body around that same list by reference, so
    # a bare `= body` would let those later in-place appends grow the captured
    # `input`/`contents` — the per-iteration `messages_sent` would then read the
    # POST-tool-batch history instead of what was actually sent this iteration
    # (the old generator dodged this by popping at its pre-batch yield seam).
    # Freezing the top-level lists here keeps `messages_sent` == the request as
    # sent; the item dicts are shared (never mutated in place, only appended).
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
    # only seeing it pop in after the response arrives.
    start_hook = ai_debug_tracker.iteration_start_hook
    if start_hook is not None:
        try:
            start_hook()
        except Exception:
            _logger.warning(
                "ai_debug: iteration_start_hook failed",
                exc_info=True,
            )

    t0 = time.monotonic()
    result = _original_request(self, method, endpoint, body, **kwargs)

    try:
        ai_debug_tracker.last_completion_response = result
        ai_debug_tracker.last_llm_duration_ms = int((time.monotonic() - t0) * 1000)
    except Exception:
        _logger.warning(
            "ai_debug: failed to stash completion response on tracker",
            exc_info=True,
        )

    return result


# Apply the patch at module load time.
AIApiService._request = _patched_request


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

    Called by ai_session._advance_one_step immediately after each iteration
    item arrives from the generator. The tracker fields are cleared
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
