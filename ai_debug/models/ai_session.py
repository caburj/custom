import copy
import logging
import time

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class AiSessionDebug(models.TransientModel):
    """Generator yield passthrough instrumentation for ai.session agentic loop.

    Inherits ai.session (TransientModel) and overrides three methods to capture
    full observability data into ai.debug.* persistent models without altering
    the loop's streaming behavior.

    All writes use a separate registry cursor so debug data survives transaction
    rollbacks on the main cursor. All failures are swallowed with a warning — the
    loop is NEVER interrupted by instrumentation errors.
    """

    _inherit = 'ai.session'

    # -------------------------------------------------------------------------
    # Config helper
    # -------------------------------------------------------------------------

    def _is_debug_enabled(self):
        """Return True unless ai_debugger.enabled is explicitly disabled.

        Default is True so the module is active immediately on install.
        Disable by setting ir.config_parameter ai_debugger.enabled = False.
        """
        return (
            self.env['ir.config_parameter']
            .sudo()
            .get_bool('ai_debugger.enabled', True)
        )

    # -------------------------------------------------------------------------
    # Binary stripping helper
    # -------------------------------------------------------------------------

    def _debug_strip_binaries(self, data):
        """Deep-copy data and replace large binary-looking strings with placeholders.

        Walks lists and dicts recursively. Any string longer than 1000 characters
        in a content field that is not 'text' type is replaced with a summary dict.

        # TODO: future enhancement — save stripped binaries to ir.attachment and link back
        """
        data = copy.deepcopy(data)

        def _walk(obj):
            if isinstance(obj, list):
                for i, item in enumerate(obj):
                    if isinstance(item, dict):
                        part_type = item.get('type', 'text')
                        content = item.get('content')
                        if part_type != 'text' and isinstance(content, str) and len(content) > 1000:
                            original_len = len(content)
                            item['content'] = {'binary': part_type, 'size': original_len}
                        else:
                            _walk(item)
                    else:
                        _walk(item)
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if isinstance(value, str) and len(value) > 1000 and key not in ('content', 'text'):
                        obj[key] = {'binary': key, 'size': len(value)}
                    else:
                        _walk(value)

        _walk(data)
        return data

    # -------------------------------------------------------------------------
    # Context sanitizer helper
    # -------------------------------------------------------------------------

    def _debug_safe_context(self):
        """Return a sanitized copy of self.env.context for use in a separate cursor.

        Strips BaseModel instances (replaces with .id or .ids) to prevent
        'cursor already closed' errors when the context is serialised into a new
        environment (Pitfall 3 from research).
        """
        safe = {}
        for key, value in self.env.context.items():
            # Skip our own mutable debug state dict — it contains non-serialisable refs
            if key == '_debug_ctx':
                continue
            if isinstance(value, models.BaseModel):
                safe[key] = value.ids if len(value) != 1 else value.id
            else:
                safe[key] = value
        return safe

    # -------------------------------------------------------------------------
    # Separate-cursor write helpers
    # -------------------------------------------------------------------------

    def _debug_write_trace(self, vals):
        """Create an ai.debug.trace record using a separate cursor.

        Returns a tuple (trace_id, bus_channel) on success, or (False, False) on failure.
        Failures are logged at WARNING level and never re-raised.
        """
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self._debug_safe_context())
                trace = env['ai.debug.trace'].create(vals)
                trace_id = trace.id
                bus_channel = trace.bus_channel
                # Broadcast new trace on global channel so listening panels auto-attach.
                try:
                    env['bus.bus']._sendone('ai_debug:traces', 'ai_debug/new_trace', {
                        'trace_id': trace_id,
                        'bus_channel': bus_channel,
                        'llm_model': vals.get('llm_model'),
                        'state': vals.get('state', 'running'),
                    })
                except Exception:
                    _logger.warning('ai_debug: failed to broadcast new trace', exc_info=True)
            return trace_id, bus_channel
        except Exception:
            _logger.warning('ai_debug: failed to write trace', exc_info=True)
            return False, False

    def _debug_write_iteration(self, trace_id, vals):
        """Create an ai.debug.iteration record linked to trace_id using a separate cursor.

        Returns the new record ID (int), or False on failure.
        Fires a bus notification inside the cursor block so pg_notify fires on commit.
        """
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self._debug_safe_context())
                vals = dict(vals, trace_id=trace_id)
                iteration = env['ai.debug.iteration'].create(vals)
                iteration_id = iteration.id
                self._debug_bus_send(env, 'ai_debug/iteration', {
                    'trace_id': trace_id,
                    'iteration_id': iteration_id,
                    'index': vals.get('index'),
                    'duration_ms': vals.get('duration_ms'),
                    'tool_call_count': 0,
                })
            return iteration_id
        except Exception:
            _logger.warning('ai_debug: failed to write iteration (trace_id=%s)', trace_id, exc_info=True)
            return False

    def _debug_update_trace(self, trace_id, vals):
        """Update an existing ai.debug.trace record using a separate cursor.

        Failures are logged at WARNING level and never re-raised.
        Fires a bus notification inside the cursor block so pg_notify fires on commit.
        """
        if not trace_id:
            return
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self._debug_safe_context())
                env['ai.debug.trace'].browse(trace_id).write(vals)
                self._debug_bus_send(env, 'ai_debug/trace_update', {
                    'trace_id': trace_id,
                    'state': vals.get('state'),
                    'termination_reason': vals.get('termination_reason'),
                    'iteration_count': vals.get('iteration_count'),
                })
        except Exception:
            _logger.warning('ai_debug: failed to update trace (trace_id=%s)', trace_id, exc_info=True)

    def _debug_write_tool_call(self, trace_id, iteration_id, vals):
        """Create an ai.debug.tool.call record using a separate cursor.

        Returns the new record ID (int), or False on failure.
        Fires a bus notification inside the cursor block so pg_notify fires on commit.
        """
        if not iteration_id:
            return False
        try:
            with self.env.registry.cursor() as cr:
                env = api.Environment(cr, self.env.uid, self._debug_safe_context())
                vals = dict(vals, iteration_id=iteration_id)
                tool_call = env['ai.debug.tool.call'].create(vals)
                tool_call_id = tool_call.id
                self._debug_bus_send(env, 'ai_debug/tool_call', {
                    'trace_id': trace_id,
                    'tool_call_id': tool_call_id,
                    'iteration_id': iteration_id,
                    'tool_name': vals.get('tool_name'),
                    'duration_ms': vals.get('duration_ms'),
                    'success': vals.get('success'),
                })
            return tool_call_id
        except Exception:
            _logger.warning('ai_debug: failed to write tool call (iteration_id=%s)', iteration_id, exc_info=True)
            return False

    # -------------------------------------------------------------------------
    # Bus notification helper
    # -------------------------------------------------------------------------

    def _debug_bus_send(self, env, event_type, payload):
        """Send a bus.bus notification on the global ai_debug:traces channel.

        All events are sent on the global channel so that listen-mode panels
        (subscribed before any trace exists) receive them without race conditions.

        The payload MUST already include trace_id (callers are responsible).

        Must be called inside a `with self.env.registry.cursor() as cr:` block
        using the `env` created from that cursor.  This ensures pg_notify fires
        when the separate cursor commits rather than waiting for the HTTP response.

        Payloads must be small (summary only) — do NOT include messages_sent,
        raw_response, state_before, or state_after.
        """
        try:
            env['bus.bus']._sendone('ai_debug:traces', event_type, payload)
        except Exception:
            _logger.warning('ai_debug: failed to send bus notification', exc_info=True)

    # -------------------------------------------------------------------------
    # _run_agentic_loop override
    # -------------------------------------------------------------------------

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, temperature, tools,
                          tools_context, record=None, schema=None, web_grounding=False):
        """Instrumented override of _run_agentic_loop.

        Captures one ai.debug.trace per invocation, one ai.debug.iteration per
        LLM call (tool_calls yield), and delegates per-tool captures to the
        _handle_tool_calls override via a shared mutable context dict.

        Falls through to super() unchanged when debug is disabled (CONF-01).
        All yielded items pass through to the consumer — streaming is unchanged.
        """
        if not self._is_debug_enabled():
            yield from super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            )
            return

        # Read instructions/RAG context injected by _generate_next_response override.
        # Falls back to the instructions parameter when called via _get_direct_response.
        captured_instructions = self.env.context.get('_debug_instructions') or instructions
        captured_rag = self.env.context.get('_debug_rag_context') or ''

        trace_id, bus_channel = self._debug_write_trace({
            'llm_model': model,
            'state': 'running',
            'instructions': captured_instructions,
            'rag_context': captured_rag,
        })

        if not trace_id:
            # Instrumentation failed — fall through without any debug capture.
            yield from super()._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            )
            return

        # Mutable dict passed via context so _handle_tool_calls can read the
        # current iteration_id without re-entering the context machinery.
        # bus_channel enables _debug_bus_send to publish real-time notifications.
        debug_ctx = {'trace_id': trace_id, 'iteration_id': None, 'bus_channel': bus_channel}

        trace_start = time.perf_counter()
        iteration_index = 0
        iter_start = time.perf_counter()

        # Pass mutable debug_ctx down the call chain via Odoo context.
        debug_self = self.with_context(_debug_ctx=debug_ctx)

        try:
            for item in super(AiSessionDebug, debug_self)._run_agentic_loop(
                model, instructions, messages, temperature, tools,
                tools_context, record, schema, web_grounding
            ):
                if 'tool_calls' in item and 'metadata' in item:
                    # LLM responded with tool call requests.
                    # Snapshot messages at this yield point — messages list was NOT
                    # yet extended (base method does messages.extend AFTER this yield).
                    iter_duration_ms = round((time.perf_counter() - iter_start) * 1000)
                    messages_snapshot = self._debug_strip_binaries(list(messages))
                    raw_response = item.get('metadata')

                    iteration_id = self._debug_write_iteration(trace_id, {
                        'index': iteration_index,
                        'messages_sent': messages_snapshot,
                        'raw_response': raw_response,
                        'duration_ms': iter_duration_ms,
                    })

                    # Update mutable context so _handle_tool_calls can link tool calls.
                    debug_ctx['iteration_id'] = iteration_id

                    iteration_index += 1
                    iter_start = time.perf_counter()

                elif 'final_message' in item:
                    # Loop completed — capture the final iteration.
                    iter_duration_ms = round((time.perf_counter() - iter_start) * 1000)
                    messages_snapshot = self._debug_strip_binaries(list(messages))
                    raw_response = item.get('metadata')

                    iteration_id = self._debug_write_iteration(trace_id, {
                        'index': iteration_index,
                        'messages_sent': messages_snapshot,
                        'raw_response': raw_response,
                        'final_message': item.get('final_message'),
                        'duration_ms': iter_duration_ms,
                    })
                    debug_ctx['iteration_id'] = iteration_id
                    iteration_index += 1

                    total_duration_ms = round((time.perf_counter() - trace_start) * 1000)
                    self._debug_update_trace(trace_id, {
                        'state': 'done',
                        'termination_reason': 'final_message',
                        'total_duration_ms': total_duration_ms,
                        'iteration_count': iteration_index,
                    })

                elif 'tool_confirmation_request' in item:
                    # Loop paused — awaiting user confirmation.
                    total_duration_ms = round((time.perf_counter() - trace_start) * 1000)
                    self._debug_update_trace(trace_id, {
                        'state': 'paused',
                        'termination_reason': 'confirmation_pause',
                        'total_duration_ms': total_duration_ms,
                        'iteration_count': iteration_index,
                    })

                # Always yield — streaming behavior is unchanged.
                yield item

            # Generator exhausted without final_message — max iterations reached.
            # (The base method raises UserError in this case, so this branch is
            # defensive; the except block below will normally handle it.)
            total_duration_ms = round((time.perf_counter() - trace_start) * 1000)
            self._debug_update_trace(trace_id, {
                'state': 'done',
                'termination_reason': 'max_iterations',
                'total_duration_ms': total_duration_ms,
                'iteration_count': iteration_index,
            })

        except Exception as e:
            self._debug_update_trace(trace_id, {
                'state': 'error',
                'error_message': str(e),
                'total_duration_ms': round((time.perf_counter() - trace_start) * 1000),
                'iteration_count': iteration_index,
            })
            raise  # Re-raise — loop behavior unchanged (CAPT-08)

    # -------------------------------------------------------------------------
    # _handle_tool_calls override
    # -------------------------------------------------------------------------

    def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record,
                           confirmed_tool_id=None, refuse_all=False):
        """Instrumented override of _handle_tool_calls.

        Captures per-tool-call state snapshots, timing, and confirmation flags
        into ai.debug.tool.call records.  Falls through to super() unchanged when
        debug is disabled or when no trace context is available.

        All yielded items pass through to the consumer — streaming is unchanged.
        """
        if not self._is_debug_enabled():
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                confirmed_tool_id, refuse_all
            )
            return

        debug_ctx = self.env.context.get('_debug_ctx')
        if not debug_ctx or not debug_ctx.get('trace_id'):
            # No trace context — fall through without capture.
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                confirmed_tool_id, refuse_all
            )
            return

        trace_id = debug_ctx['trace_id']
        iteration_id = debug_ctx.get('iteration_id')

        # Per-tool-call tracking state.
        # We track one pending tool at a time; the base method processes tool_calls
        # sequentially and yields one 'tool_results' event covering all of them,
        # or a 'tool_confirmation_request' that aborts mid-batch.
        # We capture state_before/after around the entire batch yield.
        state_before_batch = copy.deepcopy(tools_context.get('state', {}))
        tool_start = time.perf_counter()
        pending_confirmation = {'triggered': False, 'message': None}

        for item in super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            confirmed_tool_id, refuse_all
        ):
            if 'tool_confirmation_request' in item:
                # One of the tool calls requires user confirmation.
                pending_confirmation['triggered'] = True
                tc_info = item['tool_confirmation_request']
                pending_confirmation['message'] = tc_info.get('message')

                # Capture the tool that triggered the confirmation.
                # The confirmed call_id is available in tc_info['call_id'].
                triggered_call_id = tc_info.get('call_id')
                tool_duration_ms = round((time.perf_counter() - tool_start) * 1000)
                state_after = copy.deepcopy(tools_context.get('state', {}))

                # Find the matching tool call to capture name/args.
                matching_tc = next(
                    (tc for tc in tool_calls if str(tc.get('call_id')) == str(triggered_call_id)),
                    None
                )
                if matching_tc:
                    self._debug_write_tool_call(trace_id, iteration_id, {
                        'tool_name': matching_tc.get('name'),
                        'call_id': str(triggered_call_id),
                        'args': matching_tc.get('args'),
                        'result': None,
                        'success': False,
                        'triggered_confirmation': True,
                        'confirmation_message': pending_confirmation['message'],
                        'state_before': state_before_batch,
                        'state_after': state_after,
                        'duration_ms': tool_duration_ms,
                    })
                yield item

            elif 'tool_results' in item:
                # All tool calls in the batch have been executed.
                tool_duration_ms = round((time.perf_counter() - tool_start) * 1000)
                state_after_batch = copy.deepcopy(tools_context.get('state', {}))

                for tool_result in item['tool_results']:
                    tc = tool_result.get('tool_call', {})
                    self._debug_write_tool_call(trace_id, iteration_id, {
                        'tool_name': tc.get('name'),
                        'call_id': str(tc.get('call_id', '')),
                        'args': tc.get('args'),
                        'result': str(tool_result.get('result', '')) if tool_result.get('result') is not None else None,
                        'success': tool_result.get('success', True),
                        'triggered_confirmation': pending_confirmation['triggered'],
                        'confirmation_message': pending_confirmation['message'],
                        'state_before': state_before_batch,
                        'state_after': state_after_batch,
                        'duration_ms': tool_duration_ms,
                    })

                yield item

            else:
                yield item

    # -------------------------------------------------------------------------
    # _generate_next_response override
    # -------------------------------------------------------------------------

    def _generate_next_response(self, message, confirm_pending=False):
        """Instrumented override of _generate_next_response.

        Captures the system prompt (instructions) and RAG context before
        calling super(), and injects them into the Odoo context so the
        _run_agentic_loop override can attach them to the trace record.

        Falls through to super() unchanged when debug is disabled.
        All yielded items pass through to the consumer — streaming is unchanged.
        """
        self.ensure_one()

        if not self._is_debug_enabled():
            yield from super()._generate_next_response(message, confirm_pending)
            return

        # Capture system instructions (CAPT-09).
        try:
            captured_instructions = self._get_instructions()
        except Exception:
            _logger.warning('ai_debug: failed to capture instructions', exc_info=True)
            captured_instructions = ''

        # Capture RAG context (CAPT-09).
        # _get_context_input expects the user message text; extract from parts if available.
        try:
            text = ''
            if isinstance(message, dict):
                parts = message.get('parts', [])
                for part in parts:
                    if isinstance(part, dict) and part.get('type') == 'text':
                        text = part.get('content', '')
                        break
            captured_rag = self._get_context_input(text) if text else ''
        except Exception:
            _logger.warning('ai_debug: failed to capture RAG context', exc_info=True)
            captured_rag = ''

        # Pass captured data via context so _run_agentic_loop can read it.
        instrumented_self = self.with_context(
            _debug_instructions=captured_instructions,
            _debug_rag_context=captured_rag,
        )

        yield from super(AiSessionDebug, instrumented_self)._generate_next_response(
            message, confirm_pending
        )
