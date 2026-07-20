import copy
import logging
import time
import uuid

from odoo import api, models
from odoo.exceptions import UserError
from odoo.addons.ai_debug.models.ai_provider_patch import pop_last_completion_data

_logger = logging.getLogger(__name__)


class AiSession(models.Model):
    _inherit = 'ai.session'

    def _ai_debug_bus_send(self, notification_type, payload):
        """Send an ai_debug bus event using a separate cursor for real-time delivery.

        Uses registry.cursor() so the event is committed and NOTIFY'd immediately,
        before the next iteration of the agentic loop begins. This is the same
        pattern used in ai/controllers/thread.py lines 44-46.

        Never raises — instrumentation must never disrupt the main agentic loop.
        """
        try:
            with self.env.registry.cursor() as cr:
                env = self.env(cr=cr)
                env['bus.bus']._sendone('ai_debug', notification_type, payload)
        except Exception:
            _logger.exception("ai_debug: failed to send bus event '%s'", notification_type)

    def _ai_debug_state_snapshot(self, tools_context):
        """Return a JSON-safe snapshot of the current session environment and tool state."""
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

    @staticmethod
    def _ai_debug_is_image_type(mime):
        return mime and 'image' in mime

    def _ai_debug_strip_binary(self, messages):
        """Return a copy of messages with non-image binary content replaced by
        metadata stubs and image data normalized to data URIs.

        Images are preserved as data URIs so the frontend can render previews.
        Non-image files (PDFs, etc.) are replaced with lightweight stubs to
        avoid bloating bus payloads.
        """
        result = []
        for msg in messages:
            msg_copy = dict(msg)

            # OpenAI image_generation_call: normalize raw base64 result to data URI
            if msg_copy.get('type') == 'image_generation_call' and 'result' in msg_copy:
                fmt = msg_copy.get('output_format', 'png')
                msg_copy['result'] = f'data:image/{fmt};base64,{msg_copy["result"]}'

            # OpenAI format: content is a list of typed parts
            if isinstance(msg_copy.get('content'), list):
                msg_copy['content'] = self._ai_debug_process_openai_parts(msg_copy['content'])

            # OpenAI function_call_output: output list has the same part structure
            if isinstance(msg_copy.get('output'), list):
                msg_copy['output'] = self._ai_debug_process_openai_parts(msg_copy['output'])

            # Google format: parts list with inline_data dicts
            if isinstance(msg_copy.get('parts'), list):
                new_parts = []
                for part in msg_copy['parts']:
                    if 'inline_data' in part:
                        mime = part['inline_data'].get('mimeType', '')
                        if self._ai_debug_is_image_type(mime):
                            data = part['inline_data'].get('data', '')
                            new_parts.append({
                                'inline_data': {
                                    'mimeType': mime,
                                    'data': f'data:{mime};base64,{data}',
                                },
                            })
                        else:
                            new_parts.append({
                                'inline_data': {
                                    'mimeType': mime,
                                    '_binary_excluded': True,
                                },
                            })
                    else:
                        new_parts.append(part)
                msg_copy['parts'] = new_parts

            result.append(msg_copy)
        return result

    @staticmethod
    def _ai_debug_process_openai_parts(parts):
        """Process a list of OpenAI-format parts: keep images, strip other binary."""
        new_parts = []
        for part in parts:
            ptype = part.get('type', '')
            if ptype in ('input_image', 'output_image'):
                # Preserve image — image_url is already a data URI
                new_parts.append(part)
            elif ptype in ('input_file', 'output_file'):
                new_parts.append({'type': ptype, '_binary_excluded': True})
            else:
                new_parts.append(part)
        return new_parts

    def _ai_debug_serialize_tools(self, tools, model):
        """Return provider-formatted tool definitions (full JSON schemas) for the iteration payload.

        Calls _prepare_tools to get the same formatted list that will be sent to the LLM,
        including name, description, and full parameter schemas.
        """
        if not tools:
            return []
        try:
            from odoo.addons.ai.services.ai_provider import AIProvider
            provider = AIProvider.get_by_model(self.env, model)
            tools_by_name = {tool.sudo().ai_tool_name: tool for tool in tools}
            return self._prepare_tools(tools_by_name, provider)
        except Exception:
            _logger.exception("ai_debug: failed to serialize tools for iteration event")
            return []

    def _ai_debug_current_tools(self, tools_context):
        """Resolve the current tools recordset from tools_context["state"]["available_tools"].

        Mirrors the parent _run_agentic_loop lookup so serialized tools in each
        iteration event reflect the exact set available to the LLM at that point.
        Returns an empty recordset on any failure.
        """
        try:
            tool_ids = (tools_context.get('state') or {}).get('available_tools') or []
            # Mirror parent's search() so serialized order matches what the LLM
            # actually sees (model _order), not the available_tools list order.
            return self.env['ir.actions.server'].sudo().search([('id', 'in', tool_ids)])
        except Exception:
            _logger.exception("ai_debug: failed to resolve current tools from tools_context")
            return self.env['ir.actions.server']

    def _ai_debug_resolve_provider_name(self, model):
        """Return the provider name string ('openai', 'google', etc.) for a given model.

        Uses the same AIProvider.get_by_model lookup that _ai_debug_serialize_tools uses.
        Returns None on any failure — callers include it in bus events only when non-None.
        """
        try:
            from odoo.addons.ai.services.ai_provider import AIProvider
            provider = AIProvider.get_by_model(self.env, model)
            return provider.name
        except Exception:
            _logger.exception("ai_debug: failed to resolve provider name for model %r", model)
            return None

    def _generate_next_response(self, message, updated_session_config={}, pending_tool_response=None):
        """Override to capture the raw user query before provider formatting.

        _generate_next_response receives the user message as AIMessageParts
        ([{type: 'text', content: {data: '...'}}]) before it gets transformed
        by _format_to_llm into provider-specific structures. We extract the
        text here and thread it via env context so _run_agentic_loop can
        include it in the new_trace bus event.
        """
        user_query = ""
        if not pending_tool_response and message:
            for part in message:
                if isinstance(part, dict) and part.get('type') == 'text':
                    content = part.get('content')
                    user_query = content.get('data', '') if isinstance(content, dict) else content or ''
                    break
        self = self.with_context(_ai_debug_user_query=user_query)
        yield from super()._generate_next_response(message, updated_session_config, pending_tool_response=pending_tool_response)

    @api.model
    def _get_direct_response(self, model, instructions, message, tools=None,
            record=None, tool_results_collector=None, **completion_options):
        """Override to capture the raw user query before provider formatting.

        _get_direct_response receives message as AIMessageParts
        ([{type: 'text', content: {data: '...'}}]) before _format_to_llm.
        """
        user_query = ""
        for part in message or []:
            if isinstance(part, dict) and part.get('type') == 'text':
                content = part.get('content')
                user_query = content.get('data', '') if isinstance(content, dict) else content or ''
                break
        self = self.with_context(_ai_debug_user_query=user_query)
        return super()._get_direct_response(
            model, instructions, message, tools=tools,
            record=record, tool_results_collector=tool_results_collector,
            **completion_options,
        )

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, tools_context, record=None, **completion_options):
        """Override to instrument the agentic loop with bus events.

        Emits five event types over the 'ai_debug' bus channel:
          - new_trace: once at loop start (session_id, parent linkage, agent name, model, instructions)
          - iteration: once per LLM API call (messages sent, raw response, or error)
          - tool_call_started: once per tool BEFORE execution (name, args, stable tool_call_id)
          - tool_call_completed: once per tool AFTER execution (result, success, same tool_call_id)
          - loop_end: once at loop termination (reason, stats, duration)

        All events use separate cursors (registry.cursor()) so they arrive in the
        browser one-by-one during loop execution, not batched at HTTP commit.

        All instrumentation is wrapped in try/except — failures are logged but never
        propagated to the main agentic loop.
        """
        trace_id = uuid.uuid4().hex
        _debug_ctx = {
            'trace_id': trace_id,
            'iteration_id': None,
            'tool_call_count': 0,
        }

        # Propagate _debug_ctx to _handle_tool_calls via env context
        self = self.with_context(_debug_ctx=_debug_ctx)

        iteration_count = 0
        started_at = time.monotonic()

        # Resolve provider name once — a single _run_agentic_loop call uses one model.
        provider_name = self._ai_debug_resolve_provider_name(model)

        # User query is captured from the raw message in _generate_next_response
        # or _get_direct_response (before provider formatting) and threaded here
        # via env context — no need to reverse-parse provider-specific formats.
        user_query = self.env.context.get('_ai_debug_user_query', '')

        # INST-02: Read parent linkage from env context — set by _handle_tool_calls
        # (via ai_parent_trace_id) and ir.actions.server override (via ai_parent_tool_call_id)
        # when a subagent session is spawned. None for root sessions.
        parent_trace_id = self.env.context.get('ai_parent_trace_id')        # None for root
        parent_tool_call_id = self.env.context.get('ai_parent_tool_call_id')  # None for root

        self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': trace_id,
            'session_id': self.id,                       # INST-01: own ORM ID
            'parent_trace_id': parent_trace_id,          # INST-02: UUID hex or None
            'parent_tool_call_id': parent_tool_call_id,  # INST-02: LLM call_id or None
            'agent_name': self.agent_id.name if self.agent_id else None,
            'model_name': model,
            'user_query': user_query,
            # system prompt only; RAG context is in messages (captured in iteration events)
            'instructions': instructions,
            'state_snapshot': self._ai_debug_state_snapshot(tools_context),
        })

        # Track termination state — finally block always emits loop_end.
        # This handles the common case where _add_user_message returns early
        # on final_message, abandoning the generator via GeneratorExit.
        termination_reason = 'success'
        termination_error = None

        try:
            for item in super()._run_agentic_loop(
                model, instructions, messages,
                tools_context, record, **completion_options,
            ):
                if 'tool_calls' in item or 'final_message' in item:
                    # LLM responded — emit iteration event before yielding to caller.
                    # pop_last_completion_data() MUST be called first, immediately after
                    # the item arrives, to avoid reading data from the next iteration.
                    try:
                        completion_data = pop_last_completion_data()
                        tokens = completion_data.get('tokens')
                        llm_duration_ms = completion_data.get('llm_duration_ms')
                        request_body = completion_data.get('request_body')
                    except Exception:
                        _logger.warning("ai_debug: failed to pop completion data", exc_info=True)
                        tokens = None
                        llm_duration_ms = None
                        request_body = None

                    iteration_count += 1
                    iteration_id = uuid.uuid4().hex
                    _debug_ctx['iteration_id'] = iteration_id

                    # Shallow-copy message list and strip binary content before sending.
                    # Captured here (after super yields) so it reflects what was actually
                    # sent to the LLM for this iteration (full accumulated history).
                    messages_snapshot = self._ai_debug_strip_binary(list(messages))

                    # Resolve tools per-iteration: with on-demand topic loading,
                    # available tools can change between iterations as the LLM
                    # calls load_topic to bring new tools into scope.
                    current_tools = self._ai_debug_current_tools(tools_context)
                    iteration_tools = self._ai_debug_serialize_tools(current_tools, model)

                    iteration_payload = {
                        'type': 'iteration',
                        'trace_id': trace_id,
                        'iteration_id': iteration_id,
                        'iteration_index': iteration_count,
                        'messages_sent': messages_snapshot,
                        'raw_response': item.get('metadata'),
                        'has_tool_calls': 'tool_calls' in item,
                        'is_final': 'final_message' in item,
                        'provider': provider_name,
                        'tools': iteration_tools,
                    }
                    # tokens is conditional — absence signals failed/unavailable extraction
                    if tokens is not None:
                        iteration_payload['tokens'] = tokens
                    if llm_duration_ms is not None:
                        iteration_payload['duration_ms'] = llm_duration_ms

                    # Strip binary data from request body message arrays before bus transmission.
                    # OpenAI uses 'input'; Google uses 'contents'.
                    if request_body is not None:
                        request_body = copy.copy(request_body)  # shallow copy to avoid mutating original
                        if isinstance(request_body.get('input'), list):
                            request_body['input'] = self._ai_debug_strip_binary(request_body['input'])
                        if isinstance(request_body.get('contents'), list):
                            request_body['contents'] = self._ai_debug_strip_binary(request_body['contents'])
                        iteration_payload['request_body'] = request_body

                    self._ai_debug_bus_send('iteration', iteration_payload)

                yield item

        except UserError as e:
            # max_successive_calls UserError: "Number of successive API calls exceeded..."
            termination_reason = 'max_iterations' if 'successive' in str(e).lower() else 'error'
            termination_error = str(e)

            # Capture any partial timing data — tokens are skipped on errored iterations
            # per CONTEXT.md locked decision ("absence signals failure").
            try:
                err_completion_data = pop_last_completion_data()
                err_llm_duration_ms = err_completion_data.get('llm_duration_ms')
            except Exception:
                err_llm_duration_ms = None

            # Emit a failed iteration event so it appears in the sidebar tree.
            # Per locked decision: LLM API failures emit an iteration event with error
            # field instead of raw_response, before loop_end.
            err_tools = self._ai_debug_serialize_tools(
                self._ai_debug_current_tools(tools_context), model,
            )
            err_iteration_payload = {
                'type': 'iteration',
                'trace_id': trace_id,
                'iteration_id': uuid.uuid4().hex,
                'iteration_index': iteration_count + 1,
                'messages_sent': self._ai_debug_strip_binary(list(messages)),
                'raw_response': None,
                'error': termination_error,
                'error_type': type(e).__name__,
                'has_tool_calls': False,
                'is_final': False,
                'provider': provider_name,
                'tools': err_tools,
            }
            if err_llm_duration_ms is not None:
                err_iteration_payload['duration_ms'] = err_llm_duration_ms
            self._ai_debug_bus_send('iteration', err_iteration_payload)
            raise

        except Exception as e:
            # Unexpected error — emit failed iteration before loop_end (via finally)
            termination_reason = 'error'
            termination_error = str(e)

            try:
                err_completion_data = pop_last_completion_data()
                err_llm_duration_ms = err_completion_data.get('llm_duration_ms')
            except Exception:
                err_llm_duration_ms = None

            err_tools = self._ai_debug_serialize_tools(
                self._ai_debug_current_tools(tools_context), model,
            )
            err_iteration_payload = {
                'type': 'iteration',
                'trace_id': trace_id,
                'iteration_id': uuid.uuid4().hex,
                'iteration_index': iteration_count + 1,
                'messages_sent': self._ai_debug_strip_binary(list(messages)),
                'raw_response': None,
                'error': termination_error,
                'error_type': type(e).__name__,
                'has_tool_calls': False,
                'is_final': False,
                'provider': provider_name,
                'tools': err_tools,
            }
            if err_llm_duration_ms is not None:
                err_iteration_payload['duration_ms'] = err_llm_duration_ms
            self._ai_debug_bus_send('iteration', err_iteration_payload)
            raise

        finally:
            # Always emit loop_end — handles normal completion, GeneratorExit
            # (consumer abandoned generator), and exceptions (after re-raise).
            self._ai_debug_bus_send('loop_end', {
                'type': 'loop_end',
                'trace_id': trace_id,
                'termination_reason': termination_reason,
                'error': termination_error,
                'iteration_count': iteration_count,
                'tool_call_count': _debug_ctx['tool_call_count'],
                'duration_ms': int((time.monotonic() - started_at) * 1000),
            })

    def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record, confirmed_tool_id=None, refuse_all=False):
        """Override to emit tool_call_started and tool_call_completed bus events per tool.

        Each tool call emits two events:
          - tool_call_started: fired BEFORE super() delegation with tool name, args, and a
            stable tool_call_id UUID (pre-generated so started and completed share the same ID)
          - tool_call_completed: fired AFTER super() yields tool_results with the same
            tool_call_id, result, success, and error fields

        Also injects ai_parent_trace_id into env.context so any subagent sessions spawned
        during tool execution can identify their parent trace in their new_trace bus event.

        State capture (state_before/state_after via deepcopy) is disabled — no built-in
        Odoo AI tool modifies tools_context['state'], so the diff is always empty. The
        commented-out lines can be re-enabled if custom tools begin mutating state.

        If _debug_ctx is not in context (instrumentation not active), delegates to super()
        without any instrumentation overhead.
        """
        _debug_ctx = self.env.context.get('_debug_ctx')
        if not _debug_ctx:
            # Instrumentation not active — skip all overhead
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                confirmed_tool_id, refuse_all,
            )
            return

        # Thread parent trace ID via tools_context (mutable dict passed to tool functions)
        # rather than env.context, because tool records (ir.actions.server) are fetched
        # in _generate_next_response BEFORE _run_agentic_loop sets _debug_ctx, so they
        # never carry _debug_ctx in their env. tools_context reaches the agent via the
        # tool_context parameter in _ai_tool_request_sub_agent.
        tools_context['_debug_trace_id'] = _debug_ctx['trace_id']

        # State capture disabled — no built-in Odoo AI tool modifies
        # tools_context['state'], so the diff is always empty.
        # state_before_batch = copy.deepcopy(tools_context.get('state') or {})

        # Build a call_id -> tool_call lookup so confirmation events (which only
        # carry call_id) can recover tool_name and args from the original request.
        tool_calls_by_id = {tc['call_id']: tc for tc in tool_calls}

        # Pre-generate stable tool_call_id UUIDs keyed by LLM call_id.
        # Same UUID is used in tool_call_started and tool_call_completed events
        # so the JS can link them together.
        _tc_id_map = {tc['call_id']: uuid.uuid4().hex for tc in tool_calls}

        # Emit tool_call_started for each tool in the batch — fires BEFORE
        # tool execution begins. This ensures the parent tool call node exists
        # in the JS tree before any subagent trace event arrives.
        for tc in tool_calls:
            self._ai_debug_bus_send('tool_call_started', {
                'type': 'tool_call_started',
                'trace_id': _debug_ctx['trace_id'],
                'iteration_id': _debug_ctx['iteration_id'],
                'tool_call_id': _tc_id_map[tc['call_id']],
                'call_id': tc['call_id'],
                'tool_name': tc['name'],
                'args': tc.get('args', {}),
            })

        # Record start time per call_id just before tool execution begins.
        # For batch execution these are all the same moment, giving us the
        # aggregate duration from batch start to each individual result.
        _tc_start_times = {tc['call_id']: time.monotonic() for tc in tool_calls}

        for item in super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            confirmed_tool_id, refuse_all,
        ):
            if tool_results := item.get('tool_results'):
                # state_after_batch = copy.deepcopy(tools_context.get('state') or {})

                for result_item in tool_results:
                    tool_call_data = result_item.get('tool_call', {})
                    tool_name = tool_call_data.get('name')
                    call_id = tool_call_data.get('call_id')  # LLM's original call ID
                    args = tool_call_data.get('args', {})
                    result = result_item.get('result')
                    success = result_item.get('success', True)
                    error = str(result) if not success and result is not None else None

                    _debug_ctx['tool_call_count'] += 1

                    _tc_start = _tc_start_times.get(call_id, time.monotonic())
                    self._ai_debug_bus_send('tool_call_completed', {
                        'type': 'tool_call_completed',
                        'trace_id': _debug_ctx['trace_id'],
                        'iteration_id': _debug_ctx['iteration_id'],
                        'tool_call_id': _tc_id_map.get(call_id, uuid.uuid4().hex),
                        'call_id': call_id,
                        'tool_name': tool_name,
                        'result': result,
                        'success': success,
                        'error': error,
                        'duration_ms': int((time.monotonic() - _tc_start) * 1000),
                    })

            elif confirmation := item.get('tool_confirmation_request'):
                call_id = confirmation.get('call_id')
                originating_tc = tool_calls_by_id.get(call_id, {})
                _debug_ctx['tool_call_count'] += 1

                _tc_start = _tc_start_times.get(call_id, time.monotonic())
                self._ai_debug_bus_send('tool_call_completed', {
                    'type': 'tool_call_completed',
                    'trace_id': _debug_ctx['trace_id'],
                    'iteration_id': _debug_ctx['iteration_id'],
                    'tool_call_id': _tc_id_map.get(call_id, uuid.uuid4().hex),
                    'call_id': call_id,
                    'tool_name': originating_tc.get('name', 'unknown'),
                    'args': originating_tc.get('args', {}),
                    'result': None,
                    'success': None,
                    'error': None,
                    'triggered_confirmation': True,
                    'confirmation_message': confirmation.get('message', ''),
                    'duration_ms': int((time.monotonic() - _tc_start) * 1000),
                })

            yield item
