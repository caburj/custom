import copy
import logging
import time
import uuid

from odoo import api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiSession(models.TransientModel):
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

    def _ai_debug_strip_binary(self, messages):
        """Return a copy of messages with binary content replaced by metadata stubs.

        Prevents base64-encoded image/file data from bloating bus payloads.
        Replaces input_image and input_file parts with a lightweight placeholder.
        """
        result = []
        for msg in messages:
            msg_copy = dict(msg)
            if isinstance(msg_copy.get('content'), list):
                new_content = []
                for part in msg_copy['content']:
                    if part.get('type') in ('input_image', 'input_file'):
                        new_content.append({'type': part['type'], '_binary_excluded': True})
                    else:
                        new_content.append(part)
                msg_copy['content'] = new_content
            result.append(msg_copy)
        return result

    def _ai_debug_serialize_tools(self, tools, model):
        """Return provider-formatted tool definitions (full JSON schemas) for new_trace payload.

        Calls _prepare_tools to get the same formatted list that will be sent to the LLM,
        including name, description, and full parameter schemas.
        """
        if not tools:
            return []
        try:
            from odoo.addons.ai.services.ai_provider import AIProvider
            provider = AIProvider.get_by_model(self.env, model)
            tools_by_name = self._get_tools_by_name(tools)
            return self._prepare_tools(tools_by_name, provider)
        except Exception:
            _logger.exception("ai_debug: failed to serialize tools for new_trace")
            return []

    def _generate_next_response(self, message, confirm_pending=False):
        """Override to capture the raw user query before provider formatting.

        _generate_next_response receives the user message in Odoo's internal
        format ({role, parts: [{type: 'text', content: '...'}]}) before it
        gets transformed by _format_to_llm into provider-specific structures.
        We extract the text here and thread it via env context so
        _run_agentic_loop can include it in the new_trace bus event.
        """
        user_query = ""
        if not confirm_pending and message.get('parts'):
            for part in message['parts']:
                if part.get('type') == 'text':
                    user_query = part['content']
                    break
        self = self.with_context(_ai_debug_user_query=user_query)
        yield from super()._generate_next_response(message, confirm_pending=confirm_pending)

    @api.model
    def _get_direct_response(self, model, instructions, message, temperature=0.5, tools=None,
            schema=None, web_grounding=False, record=None, tool_results_collector=None):
        """Override to capture the raw user query before provider formatting.

        _get_direct_response receives message as a raw parts list
        ([{type: 'text', content: '...'}]) before _format_to_llm.
        """
        user_query = ""
        for part in message or []:
            if isinstance(part, dict) and part.get('type') == 'text':
                user_query = part['content']
                break
        self = self.with_context(_ai_debug_user_query=user_query)
        return super()._get_direct_response(
            model, instructions, message, temperature=temperature, tools=tools,
            schema=schema, web_grounding=web_grounding, record=record,
            tool_results_collector=tool_results_collector,
        )

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, temperature, tools, tools_context, record=None, schema=None, web_grounding=False):
        """Override to instrument the agentic loop with bus events.

        Emits four event types over the 'ai_debug' bus channel:
          - new_trace: once at loop start (agent name, model, system prompt, tools, state)
          - iteration: once per LLM API call (messages sent, raw response, or error)
          - tool_call: once per tool executed (via _handle_tool_calls override)
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

        # User query is captured from the raw message in _generate_next_response
        # or _get_direct_response (before provider formatting) and threaded here
        # via env context — no need to reverse-parse provider-specific formats.
        user_query = self.env.context.get('_ai_debug_user_query', '')

        self._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': trace_id,
            'agent_name': self.agent_id.name if self.agent_id else None,
            'model_name': model,
            'user_query': user_query,
            # system prompt only; RAG context is in messages (captured in iteration events)
            'instructions': instructions,
            'tools': self._ai_debug_serialize_tools(tools, model),
            'state_snapshot': self._ai_debug_state_snapshot(tools_context),
        })

        # Track termination state — finally block always emits loop_end.
        # This handles the common case where _add_user_message returns early
        # on final_message, abandoning the generator via GeneratorExit.
        termination_reason = 'success'
        termination_error = None

        try:
            for item in super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding,
            ):
                if 'tool_calls' in item or 'final_message' in item:
                    # LLM responded — emit iteration event before yielding to caller
                    iteration_count += 1
                    iteration_id = uuid.uuid4().hex
                    _debug_ctx['iteration_id'] = iteration_id

                    # Shallow-copy message list and strip binary content before sending.
                    # Captured here (after super yields) so it reflects what was actually
                    # sent to the LLM for this iteration (full accumulated history).
                    messages_snapshot = self._ai_debug_strip_binary(list(messages))

                    self._ai_debug_bus_send('iteration', {
                        'type': 'iteration',
                        'trace_id': trace_id,
                        'iteration_id': iteration_id,
                        'iteration_index': iteration_count,
                        'messages_sent': messages_snapshot,
                        'raw_response': item.get('metadata'),
                        'has_tool_calls': 'tool_calls' in item,
                        'is_final': 'final_message' in item,
                    })

                yield item

        except UserError as e:
            # max_successive_calls UserError: "Number of successive API calls exceeded..."
            termination_reason = 'max_iterations' if 'successive' in str(e).lower() else 'error'
            termination_error = str(e)

            # Emit a failed iteration event so it appears in the sidebar tree.
            # Per locked decision: LLM API failures emit an iteration event with error
            # field instead of raw_response, before loop_end.
            self._ai_debug_bus_send('iteration', {
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
            })
            raise

        except Exception as e:
            # Unexpected error — emit failed iteration before loop_end (via finally)
            termination_reason = 'error'
            termination_error = str(e)

            self._ai_debug_bus_send('iteration', {
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
            })
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
        """Override to emit tool_call bus events for each tool executed.

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

        # State capture disabled — no built-in Odoo AI tool modifies
        # tools_context['state'], so the diff is always empty.
        # state_before_batch = copy.deepcopy(tools_context.get('state') or {})

        # Build a call_id -> tool_call lookup so confirmation events (which only
        # carry call_id) can recover tool_name and args from the original request.
        tool_calls_by_id = {tc['call_id']: tc for tc in tool_calls}

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
                    error = result if not success else None

                    _debug_ctx['tool_call_count'] += 1

                    self._ai_debug_bus_send('tool_call', {
                        'type': 'tool_call',
                        'trace_id': _debug_ctx['trace_id'],
                        'iteration_id': _debug_ctx['iteration_id'],
                        'tool_call_id': uuid.uuid4().hex,
                        'tool_name': tool_name,
                        'call_id': call_id,
                        'args': args,
                        'result': result,
                        'success': success,
                        'error': error,
                    })

            elif confirmation := item.get('tool_confirmation_request'):
                call_id = confirmation.get('call_id')
                originating_tc = tool_calls_by_id.get(call_id, {})
                _debug_ctx['tool_call_count'] += 1

                self._ai_debug_bus_send('tool_call', {
                    'type': 'tool_call',
                    'trace_id': _debug_ctx['trace_id'],
                    'iteration_id': _debug_ctx['iteration_id'],
                    'tool_call_id': uuid.uuid4().hex,
                    'tool_name': originating_tc.get('name', 'unknown'),
                    'call_id': call_id,
                    'args': originating_tc.get('args', {}),
                    'result': None,
                    'success': None,
                    'error': None,
                    'triggered_confirmation': True,
                    'confirmation_message': confirmation.get('message', ''),
                })

            yield item
