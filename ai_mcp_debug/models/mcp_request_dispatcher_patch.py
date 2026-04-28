"""Monkey-patch MCP server._call_tool to emit ai_debug bus events.

Follows the same pattern as ai_debug's ai_provider_patch.py: applied at
module load time so every subsequent tools/call request is instrumented.

Each tool invocation emits one 'mcp_tool_call' bus event containing the
tool name, input arguments, result or error, success flag, and wall-clock
duration. Sent on a separate cursor for immediate delivery, consistent with
how _ai_debug_bus_send works in ai_session.py.
"""
import json
import logging
import time
import uuid

from odoo.addons.ai_mcp.mcp_server import mcp_request_dispatcher

_logger = logging.getLogger(__name__)

_original_call_tool = mcp_request_dispatcher._call_tool


def _patched_call_tool(env, params):
    name = params.get('name', 'unknown')
    arguments = params.get('arguments') or {}
    call_id = uuid.uuid4().hex
    t0 = time.monotonic()
    result = {}
    error = None
    error_message = None
    text = None

    try:
        result = _original_call_tool(env, params)
    except Exception as e:
        error = e
        error_message = str(e)
    finally:
        duration_ms = int((time.monotonic() - t0) * 1000)
        if result:
            text = result['content'][0]['text']
            text = json.loads(text) if text[0] in ('{', '[') else text
            if result['isError']:
                error_message = text

    payload = {
        'call_id': call_id,
        'tool_name': name,
        'args': arguments,
        'result': None if error_message else text,
        'error': error_message,
        'success': not error_message,
        'duration_ms': duration_ms,
    }
    with env.registry.cursor() as cr:
        env(cr=cr)['bus.bus']._sendone('ai_debug', 'mcp_tool_call', payload)

    if error:
        raise error
    return result


mcp_request_dispatcher._call_tool = _patched_call_tool
