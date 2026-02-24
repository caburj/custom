"""Monkey-patch AIApiService._request to capture LLM completion responses.

This module intercepts the low-level HTTP layer of the AI provider service
to extract token usage and per-iteration LLM call duration via threading.local().
This is the only way to access token data without modifying enterprise code:
get_completions() in each provider strips usage data before returning to the
agentic loop, so instrumentation must intercept _request directly.

The patch is applied at module load time (bottom of this file). It is imported
as the first item in ai_debug/models/__init__.py so it runs before any provider
service is instantiated.

Thread-local storage ensures that concurrent requests (e.g. sub-agents running
on separate threads) do not cross-contaminate each other's token data.
"""
import logging
import threading
import time

from odoo.addons.ai.services.ai_api_service import AIApiService

_logger = logging.getLogger(__name__)

# Thread-local storage: one slot per OS thread.
# Fields set here: last_completion_response, last_llm_duration_ms
_ai_debug_local = threading.local()

# Preserve the original _request so the patch can delegate to it.
_original_request = AIApiService._request


def _patched_request(self, method, endpoint, body, **kwargs):
    """Instrumented replacement for AIApiService._request.

    For completion endpoints (/responses, :generateContent), records the raw
    JSON response and wall-clock LLM API call duration in thread-local storage
    so pop_last_completion_data() can retrieve them after each iteration.

    All other endpoints (embeddings, transcriptions, etc.) are passed through
    unchanged.

    Instrumentation failures are caught and logged — the LLM call result is
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

    # Completion path: time the call and stash the raw response.
    t0 = time.monotonic()
    result = _original_request(self, method, endpoint, body, **kwargs)

    try:
        _ai_debug_local.last_completion_response = result
        _ai_debug_local.last_llm_duration_ms = int((time.monotonic() - t0) * 1000)
    except Exception:
        _logger.warning(
            "ai_debug: failed to stash completion response in thread-local",
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

        # Sparse fields — only include when non-zero.
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

        # Sparse fields — only include when non-zero.
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
    """Retrieve and clear the most recent completion response and LLM duration.

    Called by ai_session._run_agentic_loop immediately after each iteration
    item arrives from the generator. The thread-local fields are cleared
    immediately after reading to prevent cross-iteration contamination.

    Returns a dict with two keys:
      - ``tokens``: canonical ``{input, output, total}`` dict (with optional
        ``cached``/``reasoning``) if extraction succeeded, else ``None``.
      - ``llm_duration_ms``: integer milliseconds of the LLM API call, or
        ``None`` if unavailable (e.g. the request raised before timing was set).

    Never raises — callers rely on graceful degradation.
    """
    try:
        raw_response = getattr(_ai_debug_local, 'last_completion_response', None)
        llm_duration_ms = getattr(_ai_debug_local, 'last_llm_duration_ms', None)

        # Clear immediately — must happen before any further processing so that
        # a second call within the same thread (or a yielded sub-iteration) does
        # not see stale data from a previous iteration.
        _ai_debug_local.last_completion_response = None
        _ai_debug_local.last_llm_duration_ms = None

        if raw_response is None:
            return {'tokens': None, 'llm_duration_ms': llm_duration_ms}

        # Detect provider by examining which top-level key is present.
        # OpenAI uses 'usage'; Google uses 'usageMetadata'.
        if 'usage' in raw_response:
            tokens = _extract_tokens_openai(raw_response)
        elif 'usageMetadata' in raw_response:
            tokens = _extract_tokens_google(raw_response)
        else:
            tokens = None

        return {'tokens': tokens, 'llm_duration_ms': llm_duration_ms}

    except Exception:
        _logger.warning(
            "ai_debug: pop_last_completion_data failed unexpectedly",
            exc_info=True,
        )
        return {'tokens': None, 'llm_duration_ms': None}
