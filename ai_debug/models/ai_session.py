"""Override ai.session to create ai.debug.* records during the agentic loop.

Records are written via a separate cursor (self.env.registry.cursor()) so they
survive even if the main agentic loop transaction rolls back. Bus notifications
are sent via debug_env.user._bus_send() so they target the user who triggered
the AI session. Records and bus notifications share the same debug cursor and
commit together for atomicity.

Runtime state (current debug env, loop/iteration ids, per-request LLM capture)
is passed between methods via the shared ``ai_debug_tracker`` thread-local
exposed by agent_runtime_tracker.

All instrumentation is wrapped in try/except -- failures are logged but never
propagated to the main agentic loop.
"""
import json
import logging
import time
from contextlib import contextmanager

from odoo import SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.tools.json import json_default

from odoo.addons.ai.services.ai_provider import AIProvider
from odoo.addons.ai.utils.ai_utils import get_text_from_parts, is_ai_parts, markdown_format
from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker
from odoo.addons.ai_debug.models.ai_provider_patch import pop_last_completion_data

_logger = logging.getLogger(__name__)

class AiSession(models.Model):
    _inherit = 'ai.session'

    # Set on a turn's first tick, cleared at turn end, so one debug loop spans
    # all the turn's cron ticks. Plain Integer (not Many2one): ai.debug.* rows
    # live on a separate debug cursor, so a cross-cursor FK would be wrong.
    current_debug_loop_id = fields.Integer(
        string="Current Debug Loop", copy=False,
        help="ai.debug.loop id of the in-flight turn (spans cron ticks).")

    # The two-cron split fills one model round's iteration across two commits:
    # the LLM-batch persist seam (`_persist_llm_reply`) opens the iteration and
    # writes the response, the tool-batch seam (`_run_tools_and_route`) attaches
    # that round's tool.call rows to the SAME committed iteration. This durable
    # pointer bridges them (mirrors `current_debug_loop_id`; plain Integer, since
    # ai.debug.* rows live on a separate debug cursor). Set by CRON1 for a
    # tool-calling reply, read + cleared by CRON2.
    current_debug_iteration_id = fields.Integer(
        string="Current Debug Iteration", copy=False,
        help="ai.debug.iteration id CRON2's tool rows re-attach to (one round, two commits).")

    # The child persists the spawning parent's spawn/ask tool-call debug-row id
    # on ITS OWN row at its first tick (resolved from its waiting wait edge
    # call_id — NOT written by the parent, which would race the cron claim), then
    # reads it at loop entry to back-link its debug loop across cron ticks.
    parent_tool_call_db_id = fields.Integer(
        string="Parent Debug Tool Call", copy=False,
        help="ai.debug.tool.call id of the spawning parent call (spans cron ticks).")

    # ------------------------------------------------------------------
    # Helpers (ported from the deprecated prototype)
    # ------------------------------------------------------------------

    @staticmethod
    def _ai_debug_is_image_type(mime):
        return mime and 'image' in mime

    def _ai_debug_strip_binary(self, messages):
        """Return a copy of messages with non-image binary content replaced by
        metadata stubs and image data normalized to data URIs.

        Images are preserved as data URIs so the frontend can render previews.
        Non-image files (PDFs, etc.) are replaced with lightweight stubs to
        avoid bloating payloads.
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
                new_parts.append(part)
            elif ptype in ('input_file', 'output_file'):
                new_parts.append({'type': ptype, '_binary_excluded': True})
            else:
                new_parts.append(part)
        return new_parts

    # Keys under which each provider's request body carries the messages list.
    # OpenAI /responses: body['input']; Google :generateContent: body['contents'].
    _AI_DEBUG_REQUEST_MESSAGE_KEYS = ('input', 'contents')

    def _ai_debug_extract_messages_sent(self, stripped_request_body):
        """Return the messages list from a request body already passed through
        ``_ai_debug_strip_request_body`` (keeps ``messages_sent`` byte-identical
        to the messages inside ``raw_request``). None if absent."""
        if not isinstance(stripped_request_body, dict):
            return None
        for key in self._AI_DEBUG_REQUEST_MESSAGE_KEYS:
            messages = stripped_request_body.get(key)
            if isinstance(messages, list):
                return messages
        return None

    def _ai_debug_strip_request_body(self, request_body):
        """Return a shallow copy of the captured request body with its embedded
        messages list binary-stripped (images normalized to data URIs, other
        binary stubbed). Non-dict input is returned unchanged."""
        if not isinstance(request_body, dict):
            return request_body
        try:
            body_copy = dict(request_body)
            for key in self._AI_DEBUG_REQUEST_MESSAGE_KEYS:
                if isinstance(body_copy.get(key), list):
                    body_copy[key] = self._ai_debug_strip_binary(body_copy[key])
            return body_copy
        except Exception:
            _logger.warning(
                "ai_debug: failed to strip binary from raw_request",
                exc_info=True,
            )
            return request_body

    def _ai_debug_resolve_provider_name(self, model):
        """Return the provider name string ('openai', 'google', etc.) for a given model."""
        try:
            provider = AIProvider.get_by_model(self.env, model)
            return provider.name
        except Exception:
            _logger.exception("ai_debug: failed to resolve provider name for model %r", model)
            return None

    @staticmethod
    def _ai_debug_extract_text(message_parts):
        """Extract text from AIMessageParts, returning '' on failure."""
        if not message_parts:
            return ''
        try:
            if is_ai_parts(message_parts):
                result = get_text_from_parts(message_parts)
                return result if isinstance(result, str) else json.dumps(result, default=json_default, ensure_ascii=False)
            return str(message_parts)
        except Exception:
            return ''

    @staticmethod
    def _ai_debug_current_tool_ids(tools_context):
        """Snapshot of currently-available tool IDs.

        Must be called per-iteration, not once at loop start: load_skills /
        enable_tools mutate tools_context['state']['available_tools'] in place
        as the LLM dynamically pulls in more topics, and the Available Tools
        tab should reflect the state at the moment each iteration finished.
        """
        return list(tools_context.get("state", {}).get("available_tools") or [])

    def _ai_debug_finalize_error_iteration(
        self, debug_env, debug_cr, debug_loop, _user, messages,
        prev_messages_len, tools_context, pending_iteration_id,
        iteration_count, exc, error_text, base_instructions,
    ):
        """Finalize the iteration row that was in flight when *exc* was raised.

        If the start hook already created a pending row (the usual case -- the
        LLM request ran and then raised mid-parse or max-iterations tripped
        afterwards), update it in place with the error text and zero metrics
        so the spinner clears. If no pending row exists (failure before any
        LLM call), synthesize a fresh error row. Either way, emit one
        AI_DEBUG_ITERATION so the client stops spinning.
        """
        try:
            completion_data = pop_last_completion_data()
            llm_duration_ms = completion_data.get('llm_duration_ms')
            request_body = completion_data.get('request_body')
        except Exception:
            llm_duration_ms = None
            request_body = None

        # The request body is stashed before the HTTP call, so even a failed
        # iteration can surface what was sent (raw_response stays None).
        raw_request = self._ai_debug_strip_request_body(request_body)
        messages_sent = self._ai_debug_extract_messages_sent(raw_request)

        try:
            delta = self._ai_debug_strip_binary(list(messages)[prev_messages_len:])
        except Exception:
            delta = None

        current_tool_ids = self._ai_debug_current_tool_ids(tools_context)
        # Keep only tool ids visible on the sibling cursor (see the same guard in
        # _ai_debug_finalize_iteration): an uncommitted-in-test tool would
        # FK-violate the available_tool_ids M2M and abort this error-iteration
        # write. Production tools are always committed, so nothing is filtered.
        if current_tool_ids:
            current_tool_ids = list(
                debug_env['ir.actions.server'].sudo().browse(current_tool_ids).exists().ids)

        values = {
            'is_running': False,
            'messages_delta': delta,
            'messages_sent': messages_sent,
            'raw_request': raw_request,
            'raw_response': None,
            'output_message': error_text,
            'tokens_in': 0,
            'tokens_cached': 0,
            'tokens_out': 0,
            'duration_ms': llm_duration_ms or 0,
            'available_tool_ids': [(6, 0, current_tool_ids)],
        }

        try:
            # ``values`` carries the available_tool_ids M2M, which links
            # ir.actions.server rows the triggering user may not be allowed to
            # read. Scope .sudo() to just this link write -- every other debug
            # write stays as the real unprivileged user.
            if pending_iteration_id:
                debug_iteration = debug_env['ai.debug.iteration'].sudo().browse(pending_iteration_id)
                debug_iteration.with_user(SUPERUSER_ID).write(values)
                sequence = debug_iteration.sequence
            else:
                # No pending row: the error fired before any LLM dispatch, so
                # the start hook never ran. Augment the base instructions
                # with whatever topics are currently loaded so the synthesized
                # error row carries the prompt a successful iteration would
                # have sent.
                try:
                    fallback_instructions = self._append_loaded_skills(
                        base_instructions or '', tools_context,
                    )
                except Exception:
                    fallback_instructions = base_instructions or ''
                sequence = iteration_count + 1
                debug_iteration = debug_env['ai.debug.iteration'].sudo().create({
                    'loop_id': debug_loop.id,
                    'sequence': sequence,
                    'instructions': fallback_instructions,
                    **values,
                })

            _user._bus_send("AI_DEBUG_ITERATION", {
                'id': debug_iteration.id,
                'loop_id': debug_loop.id,
                'sequence': sequence,
                'is_running': False,
                'instructions': debug_iteration.instructions,
                'messages_delta': delta,
                'messages_sent': messages_sent,
                'raw_request': raw_request,
                'error': error_text,
                'error_type': type(exc).__name__,
                'has_tool_calls': False,
                'is_final': False,
                'available_tool_ids': current_tool_ids,
            })
            debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to write error iteration")

    # ------------------------------------------------------------------
    # User query capture
    # ------------------------------------------------------------------

    @api.model
    def _get_direct_response(self, model, instructions, message, tools=None,
            record=None, tool_results_collector=None, **completion_options):
        """Own the debug loop for a synchronous one-shot request.

        The base drains ``_advance_one_step(persist=False)`` several times inside
        this one call, so — unlike the cron path, where each tick owns its loop —
        the sync loop must span those steps. Open ONE debug thread + loop here
        (always fresh; ``is_cron_tick`` is False), let each step create+finalize
        its own iteration against the tracker (see ``_ai_debug_step_sync``), and
        finalize the loop when the drain returns/raises. Save+restore the tracker
        so a nested one-shot (e.g. ``generate_image`` calling this mid tool run)
        leaves the enclosing cron loop's instrumentation intact and links its own
        loop under the running tool call (``current_tool_call_db_id``)."""
        user_query = ""
        for part in message or []:
            if isinstance(part, dict) and part.get('type') == 'text':
                content = part.get('content')
                user_query = content.get('data', '') if isinstance(content, dict) else content or ''
                break
        self = self.with_context(agent_loop_user_query=user_query)

        with self._ai_debug_tracker_scope(), self.env.registry.cursor() as debug_cr:
            # tools_context / messages are unavailable here (the base builds them
            # per step); the iteration hook is (re)installed per step by
            # _ai_debug_step_sync, which has both.
            ctx = self._ai_debug_open_loop(debug_cr, model, None, is_cron_tick=False)
            if ctx is None:
                return super()._get_direct_response(
                    model, instructions, message, tools=tools,
                    record=record, tool_results_collector=tool_results_collector,
                    **completion_options)
            termination_reason = 'success'
            error_text = None
            try:
                result = super()._get_direct_response(
                    model, instructions, message, tools=tools,
                    record=record, tool_results_collector=tool_results_collector,
                    **completion_options)
                if result:
                    ctx['last_output'] = self._ai_debug_extract_text(result)
                return result
            except Exception as e:
                termination_reason = self._ai_debug_termination_reason(e)
                error_text = str(e)
                raise
            finally:
                self._ai_debug_finalize_loop(
                    ctx, termination_reason, error_text, is_cron_tick=False)

    def _run_session_tick(self):
        """Reset the per-thread ai_debug tracker at the tick boundary.

        A production cron tick runs in a FRESH worker thread, so its
        ``ai_debug_tracker`` (a ``threading.local``) starts pristine each tick.
        That per-tick-fresh invariant is what keeps a tick whose debug
        thread-create FK-failed (swallowed) from leaking a CLOSED ``debug_env``
        cursor into the next tick's instrumentation. Re-initialising here makes
        that invariant explicit and, crucially, also holds when many ticks run
        in ONE thread — e.g. the ai test pump (`_drive_cron_to_quiescence*`),
        which must therefore stay IGNORANT of ai_debug. Harmless in production
        (the thread-local is already fresh); the tracker is set up afresh inside
        ``_advance_one_step`` regardless. ``_run_session_tick`` is the sole
        per-tick entrypoint and is never nested (tools call ``_advance_one_step``,
        not this), so a blanket reset here is safe (unlike inside the step, whose
        save/restore guards nested calls)."""
        ai_debug_tracker.__init__()
        return super()._run_session_tick()

    # ------------------------------------------------------------------
    # Agentic-step instrumentation
    # ------------------------------------------------------------------

    def _advance_one_step(self, messages, tools_context, *, persist=True,
                          allow_subagents=True, on_resume=False,
                          confirm_pending=False, refusal_reason=None,
                          model, instructions, record=None, **completion_options):
        """Instrument the two drive sites that STILL run a single-frame step.

        The two-cron split moved the cron model round OFF ``_advance_one_step``:
        the model reply is now persisted by ``_persist_llm_reply`` (CRON1) and its
        tools run by ``_run_tools_and_route`` (CRON2), each instrumented on its own
        seam. Only two callers still reach this method, and each keeps its existing
        instrumentation unchanged:
          - confirmation-resume (on_resume=True): no LLM call and the tool.call rows
            already exist — update those rows and record the confirmed final message,
            without opening a new iteration/loop.
          - sync one-shot (persist=False): ``_get_direct_response`` owns the loop
            spanning the drain's steps; here only the per-step iteration is
            created+finalized against the tracker it set up.

        A cron model round (persist=True, on_resume=False) is no longer routed here;
        should any future caller reach it, run it uninstrumented rather than open a
        second loop that would race the seam-driven one.
        """
        if on_resume:
            return self._ai_debug_step_resume(
                messages, tools_context, allow_subagents=allow_subagents,
                confirm_pending=confirm_pending, refusal_reason=refusal_reason,
                model=model, instructions=instructions, record=record,
                **completion_options)
        if not persist:
            return self._ai_debug_step_sync(
                messages, tools_context, allow_subagents=allow_subagents,
                model=model, instructions=instructions, record=record,
                **completion_options)
        return super()._advance_one_step(
            messages, tools_context, persist=persist,
            allow_subagents=allow_subagents, on_resume=on_resume,
            confirm_pending=confirm_pending, refusal_reason=refusal_reason,
            model=model, instructions=instructions, record=record,
            **completion_options)

    # ------------------------------------------------------------------
    # Two-cron seam instrumentation (CRON1 persist / CRON2 tools)
    # ------------------------------------------------------------------

    def _persist_llm_reply(self, response, call):
        """CRON1 seam: instrument the model round the LLM-batch persists.

        Opens (or reuses, across the turn's rounds) the ai.debug.loop, creates
        this round's iteration, and writes the captured request/response/tokens/
        duration onto it. A no-tool reply is the FINAL answer — finalize the
        iteration and the loop (success) here. A tool-calling reply leaves the
        iteration open (is_running, tools pending) and stashes its id on
        ``current_debug_iteration_id`` so CRON2 re-attaches the tool rows to this
        same committed iteration, DEFERRING the loop finalize. Best-effort: any
        debug failure is logged and the base outcome returned unchanged.
        """
        with self._ai_debug_tracker_scope(), self.env.registry.cursor() as debug_cr:
            messages = call.get('messages')
            ctx = self._ai_debug_open_loop(debug_cr, call['model'], messages, is_cron_tick=True)
            if ctx is None:
                return super()._persist_llm_reply(response, call)
            instructions = call.get('instructions')
            tools_context = call.get('tools_context')
            try:
                # Create the pending iteration row NOW (the LLM call already ran —
                # in a worker thread for the batch, or before this seam inline — so
                # the pre-call start hook did not open it on this cursor).
                self._ai_debug_install_iteration_hook(ctx, instructions, tools_context)
                self._before_tool_calls()
                # Bridge the executed request/response onto the thread-local the
                # finalize reads (the batch ran the HTTP on another thread).
                self._ai_debug_stash_completion(call)
                try:
                    outcome = super()._persist_llm_reply(response, call)
                except Exception as e:
                    reason = self._ai_debug_termination_reason(e)
                    self._ai_debug_finalize_error_iteration(
                        ctx['debug_env'], debug_cr, ctx['debug_loop'], ctx['user'],
                        messages, ctx['prev_messages_len'], tools_context,
                        ctx['pending_iteration_id'], ctx['iteration_count'],
                        e, str(e), instructions)
                    self._ai_debug_finalize_loop(ctx, reason, str(e), is_cron_tick=True)
                    self._ai_debug_release_iteration_handle()
                    raise
                has_tools = outcome.get('kind') != 'terminal'
                # Write the response fields. A tools-pending round leaves the
                # iteration running until CRON2 closes it; a terminal round closes it.
                self._ai_debug_finalize_iteration(
                    ctx, outcome, messages, instructions, tools_context,
                    is_running=has_tools)
                if has_tools:
                    if self.id:
                        # On the MAIN cursor: committed with the per-session persist,
                        # read by CRON2's tool batch.
                        self.sudo().current_debug_iteration_id = ai_debug_tracker.iteration_id or False
                else:
                    self._ai_debug_finalize_loop(ctx, 'success', None, is_cron_tick=True)
                    self._ai_debug_release_iteration_handle()
                return outcome
            finally:
                ai_debug_tracker.last_confirmation_message = None

    def _run_tools_and_route(self):
        """CRON2 seam: attach this round's tool.call rows to CRON1's iteration.

        Re-open the loop CRON1 left running (``current_debug_loop_id``) and wire
        the tracker's ``iteration_id`` to the iteration CRON1 committed
        (``current_debug_iteration_id``), so the ``_handle_tool_calls`` override
        attaches this round's tool rows to that SAME iteration. Run the base tool
        batch, close the iteration, then finalize the loop by outcome: continue /
        awaiting_subagents defer (the turn goes on); terminal -> success;
        confirmation -> confirmation; collision -> error. Best-effort.
        """
        iteration_id = self.sudo().current_debug_iteration_id if self.id else False
        loop_id = self.sudo().current_debug_loop_id if self.id else False
        if not iteration_id or not loop_id:
            # CRON1 declined instrumentation (or this is a non-model tool tick) —
            # run the base routing bare.
            return super()._run_tools_and_route()
        original_uid = self.env.uid
        with self._ai_debug_tracker_scope(), self.env.registry.cursor() as debug_cr:
            debug_env = api.Environment(debug_cr, original_uid, {})
            # Acting user not committed on this sibling cursor (uncommitted test
            # user) — run bare, as _ai_debug_open_loop would have declined.
            if not debug_env['res.users'].sudo().browse(original_uid).exists():
                return super()._run_tools_and_route()
            loop = debug_env['ai.debug.loop'].sudo().browse(loop_id).exists()
            iteration = debug_env['ai.debug.iteration'].sudo().browse(iteration_id).exists()
            if not loop or not iteration:
                return super()._run_tools_and_route()
            # Wire the tracker so _handle_tool_calls / _before_tool_calls attach to
            # the committed iteration instead of opening a new one.
            ai_debug_tracker.debug_env = debug_env
            ai_debug_tracker.loop_id = loop_id
            ai_debug_tracker.iteration_id = iteration_id
            ai_debug_tracker.uid = original_uid
            # A confirmation tool sets this on the tracker inside the batch; clear
            # it first so a `confirmation` outcome reads THIS round's message, never
            # a prior round's leftover.
            ai_debug_tracker.last_confirmation_message = None
            try:
                outcome = super()._run_tools_and_route()
            except Exception as e:
                reason = self._ai_debug_termination_reason(e)
                self._ai_debug_close_iteration_after_tools(debug_env, debug_cr, iteration, loop_id, None)
                self._ai_debug_finalize_split_loop(debug_env, debug_cr, loop, reason, str(e))
                self._ai_debug_release_iteration_handle()
                raise
            self._ai_debug_close_iteration_after_tools(debug_env, debug_cr, iteration, loop_id, outcome)
            kind = outcome.get('kind')
            if kind == 'terminal':
                self._ai_debug_finalize_split_loop(
                    debug_env, debug_cr, loop, 'success', None,
                    last_output=self._ai_debug_extract_text(outcome.get('final_message')))
            elif kind == 'confirmation':
                self._ai_debug_finalize_split_loop(
                    debug_env, debug_cr, loop, 'confirmation', None,
                    confirmation_html=ai_debug_tracker.last_confirmation_message)
            elif kind == 'collision':
                self._ai_debug_finalize_split_loop(
                    debug_env, debug_cr, loop, 'error',
                    'unrouted spawn/confirmation collision')
            # 'continue' / 'awaiting_subagents': DEFER the loop finalize (the turn
            # continues on a later round; the loop stays running, handle kept).
            self._ai_debug_release_iteration_handle()
            return outcome

    def _ai_debug_release_iteration_handle(self):
        """Clear the per-round iteration pointer (main cursor). The next model
        round opens its own iteration; leaving a stale id would misdirect CRON2."""
        if self.id and self.sudo().current_debug_iteration_id:
            self.sudo().current_debug_iteration_id = False

    def _ai_debug_stash_completion(self, call):
        """Bridge the CRON1 seam's executed request/response onto the thread-local
        the finalize reads (``pop_last_completion_data``). The LLM batch runs the
        HTTP in a bare worker thread, so the capture travels in
        ``call['prepared']``/``call['result']`` rather than this cron thread's
        tracker — copy it across so the existing finalize path is uniform. The
        inline/sync path leaves both keys absent (the _execute_prepared_request
        patch already stashed on THIS thread during get_completions)."""
        prepared = call.get('prepared')
        result = call.get('result')
        if prepared is None and result is None:
            return
        try:
            body = prepared.get('body') if isinstance(prepared, dict) else None
            if isinstance(body, dict):
                snapshot = dict(body)
                for _k, _v in snapshot.items():
                    if isinstance(_v, list):
                        snapshot[_k] = list(_v)
                ai_debug_tracker.last_request_body = snapshot
            else:
                ai_debug_tracker.last_request_body = body
            if isinstance(result, dict) and result.get('ok'):
                ai_debug_tracker.last_completion_response = result.get('raw_response')
                ai_debug_tracker.last_llm_duration_ms = result.get('duration_ms')
        except Exception:
            _logger.warning("ai_debug: failed to stash completion from call bundle", exc_info=True)

    def _ai_debug_close_iteration_after_tools(self, debug_env, debug_cr, iteration, loop_id, outcome):
        """CRON2: close CRON1's still-running iteration after its tool batch ran.

        The tool.call rows are already attached (via the _handle_tool_calls
        override, to ``current_debug_iteration_id``); here just clear the spinner
        and, if the tools produced the turn's final answer, record it. The
        response fields (raw_request/response/tokens) were written by CRON1 and
        are NOT touched. Best-effort; never raises to the caller."""
        try:
            values = {'is_running': False}
            is_final = bool(outcome) and outcome.get('kind') == 'terminal'
            output_text = ''
            if outcome and (final_msg := outcome.get('final_message')):
                output_text = self._ai_debug_extract_text(final_msg)
                if output_text:
                    values['output_message'] = output_text
            iteration.with_user(SUPERUSER_ID).write(values)
            debug_env.user._bus_send("AI_DEBUG_ITERATION", {
                'id': iteration.id,
                'loop_id': loop_id,
                'sequence': iteration.sequence,
                'is_running': False,
                'instructions': iteration.instructions,
                'messages_delta': iteration.messages_delta,
                'messages_sent': iteration.messages_sent,
                'raw_request': iteration.raw_request,
                'raw_response': iteration.raw_response,
                'output_message': iteration.output_message or output_text or '',
                'tokens_in': iteration.tokens_in,
                'tokens_cached': iteration.tokens_cached,
                'tokens_out': iteration.tokens_out,
                'duration_ms': iteration.duration_ms,
                'has_tool_calls': True,
                'is_final': is_final,
                'available_tool_ids': iteration.available_tool_ids.ids,
            })
            debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to close iteration after tools")
            try:
                debug_cr.rollback()
            except Exception:
                _logger.exception("ai_debug: failed to roll back after iteration-close error")

    def _ai_debug_finalize_split_loop(self, debug_env, debug_cr, loop, termination_reason,
                                      error_text, last_output=None, confirmation_html=None):
        """CRON2 loop finalize: build the minimal ctx ``_ai_debug_finalize_loop``
        needs and delegate to it, so the thread-name refresh + LOOP_END bus + the
        cross-tick handle release stay in one place. Loop duration is measured from
        the persisted ``start_time`` (the loop spans separate CRON1/CRON2
        invocations, so a single monotonic delta cannot bridge them)."""
        ctx = {
            'debug_cr': debug_cr,
            'debug_loop': loop,
            'user': debug_env.user,
            'thread': loop.thread_id,
            'started_at': None,
            'iteration_count': len(loop.iteration_ids),
            'last_output': last_output or '',
        }
        self._ai_debug_finalize_loop(
            ctx, termination_reason, error_text, is_cron_tick=True,
            confirmation_html=confirmation_html)

    def _ai_debug_step_sync(self, messages, tools_context, *, allow_subagents,
                            model, instructions, record, **completion_options):
        """Instrument one sync (persist=False) step. The loop was opened by
        ``_get_direct_response``; here we only create+finalize this step's
        iteration against the tracker it set up. If no sync loop is active
        (tracker not set up), run the base step bare."""
        ctx = ai_debug_tracker.loop_ctx
        if ctx is None or ai_debug_tracker.debug_env is None:
            return super()._advance_one_step(
                messages, tools_context, persist=False,
                allow_subagents=allow_subagents, model=model,
                instructions=instructions, record=record, **completion_options)
        with self._ai_debug_tracker_scope():
            self._ai_debug_install_iteration_hook(ctx, instructions, tools_context)
            outcome = super()._advance_one_step(
                messages, tools_context, persist=False,
                allow_subagents=allow_subagents, model=model,
                instructions=instructions, record=record, **completion_options)
            self._ai_debug_finalize_iteration(
                ctx, outcome, messages, instructions, tools_context)
            return outcome

    def _ai_debug_step_resume(self, messages, tools_context, *, allow_subagents,
                              confirm_pending, refusal_reason, model, instructions,
                              record, **completion_options):
        """Instrument a confirmation-resume step (on_resume=True). No LLM call
        runs, so no new iteration is created — the tool.call rows from the turn
        that asked for confirmation already exist: expose a sibling debug env
        (so parallel tool runs can resolve their rows), then update the resolved
        rows and record the confirmed final message.

        ``iteration_id`` is left None so the ``_handle_tool_calls`` override
        short-circuits and does NOT create duplicate rows."""
        pending_call_ids = set()
        try:
            provider = AIProvider.get_by_name(self.env, self.provider)
            history = self._get_history(1)
            if history:
                last_tool_calls = provider._format_from_llm(history.metadata).get('tool_calls') or []
                tool_outputs_already = self.pending_tools_results or []
                remaining_tool_calls = last_tool_calls[len(tool_outputs_already):]
                pending_call_ids = {tc['call_id'] for tc in remaining_tool_calls}
        except Exception:
            _logger.exception("ai_debug: failed to resolve pending tool call_ids")

        # Captured before super() clears self.pending_tool_call_id.
        confirmed_call_id = self.pending_tool_call_id if confirm_pending else None
        started_at = time.monotonic()
        original_uid = self.env.uid
        with self._ai_debug_tracker_scope(), self.env.registry.cursor() as debug_cr:
            # Sibling cursor (NEVER self.env.cr): committing the held job cursor
            # mid-tick would release the row lock and risk double-running a tool.
            ai_debug_tracker.debug_env = api.Environment(debug_cr, original_uid, {})
            ai_debug_tracker.iteration_id = None
            outcome = super()._advance_one_step(
                messages, tools_context, persist=True,
                allow_subagents=allow_subagents, on_resume=True,
                confirm_pending=confirm_pending, refusal_reason=refusal_reason,
                model=model, instructions=instructions, record=record,
                **completion_options)
            tool_results = outcome.get('tool_results')
            if tool_results:
                try:
                    self._ai_debug_update_confirmation_tool_results(
                        tool_results, pending_call_ids, started_at,
                        refused=not confirm_pending)
                except Exception:
                    _logger.exception(
                        "ai_debug: failed to update confirmation tool_results")
            if (confirm_pending and outcome.get('kind') == 'terminal'
                    and outcome.get('final_message')):
                try:
                    self._ai_debug_record_confirmation_final(
                        outcome['final_message'], confirmed_call_id)
                except Exception:
                    _logger.exception(
                        "ai_debug: failed to record confirmation final message")
            return outcome

    # ----- shared instrumentation helpers (cron + sync) -----

    _AI_DEBUG_TRACKER_SLOTS = (
        'debug_env', 'loop_id', 'iteration_id', 'uid',
        'iteration_start_hook', 'loop_ctx',
    )

    @contextmanager
    def _ai_debug_tracker_scope(self):
        """Snapshot the tracker slots this layer mutates and restore them on exit
        (including on exception), so a nested step -- a tool calling
        _get_direct_response mid tool-run -- restores the enclosing loop's
        instrumentation. Used by every drive site (cron / sync / resume): each
        may mutate only a subset, but a full snapshot+restore is a superset of
        every site's need and leaves untouched slots unchanged."""
        saved = [getattr(ai_debug_tracker, slot) for slot in self._AI_DEBUG_TRACKER_SLOTS]
        try:
            yield
        finally:
            for slot, value in zip(self._AI_DEBUG_TRACKER_SLOTS, saved):
                setattr(ai_debug_tracker, slot, value)

    @staticmethod
    def _ai_debug_termination_reason(exc):
        """Classify a step exception for the loop/iteration termination reason:
        'max_iterations' for the base's successive-tool-call UserError, else
        'error'. One classifier shared by the cron and sync drive sites."""
        return ('max_iterations'
                if isinstance(exc, UserError) and 'successive' in str(exc).lower()
                else 'error')

    def _ai_debug_open_loop(self, debug_cr, model, messages, is_cron_tick):
        """Get-or-create the ai.debug.thread + ai.debug.loop for this step and
        wire the shared tracker. One debug loop spans a cron turn's many ticks
        (reused via ``current_debug_loop_id``); the sync path always opens a
        fresh one. Returns a per-loop ctx dict (also stashed on
        ``ai_debug_tracker.loop_ctx``), or None if the debug records could not be
        created (caller then runs uninstrumented)."""
        started_at = time.monotonic()
        original_uid = self.env.uid
        user_query = self.env.context.get('agent_loop_user_query', '')
        provider_name = self._ai_debug_resolve_provider_name(model)
        debug_env = api.Environment(debug_cr, original_uid, {})

        # Pre-flight: the whole debug env is built around `original_uid` (env.user,
        # create_uid/write_uid stamping, default_get). If that user is NOT visible
        # on this sibling cursor, instrumentation cannot run — this is the normal
        # case for a test that drives the agentic loop as a user created in its own
        # (uncommitted) transaction, invisible on a separate connection. Decline
        # cleanly (uninstrumented, as before) instead of failing mid-create with a
        # logged MissingError/FK. In production the acting user is always committed,
        # so this never triggers. Gates the entire downstream chain (hook / tool
        # rows / finalize) for the session, since the tracker is never wired.
        if not debug_env['res.users'].sudo().browse(original_uid).exists():
            return None

        # Nested one-shot (generate_image et al.): link this child loop under the
        # tool call currently executing (set by ir_actions_server._ai_tool_run).
        nested_parent_tool_call_db_id = ai_debug_tracker.current_tool_call_db_id

        # Parent debug tool-call to link this child thread under — resolved from
        # the child's OWN incoming waiting wait edge (NOT written by the parent,
        # which would race the cron claim's 40001) and persisted on its own row.
        parent_tool_call_db_id = False
        if self.id:
            resolved = self._ai_debug_resolve_parent_tool_call()
            if resolved:
                parent_tool_call_db_id = resolved
                if self.sudo().parent_tool_call_db_id != resolved:
                    self.sudo().parent_tool_call_db_id = resolved
        if not parent_tool_call_db_id and self.id:
            parent_tool_call_db_id = self.sudo().parent_tool_call_db_id or False
        if not parent_tool_call_db_id and nested_parent_tool_call_db_id:
            parent_tool_call_db_id = nested_parent_tool_call_db_id

        try:
            session_id_str = str(self.id) if self.id else str(id(self))
            thread = debug_env['ai.debug.thread'].sudo().search(
                [('session_id', '=', session_id_str)], limit=1)
            thread_existed = bool(thread)
            session_is_background = bool(getattr(self, 'is_background', False))
            agent = self.agent_id if hasattr(self, 'agent_id') and self.agent_id else False
            # Link the agent only if it is VISIBLE on the sibling debug cursor. An
            # agent created in the caller's own uncommitted transaction (tests) is
            # invisible on this separate connection, so linking it would
            # FK-violate — failing the whole thread/loop create and dropping
            # instrumentation for the turn. In production the agent is always
            # committed, so it is always linked.
            agent_id_val = (
                agent.id if agent and debug_env['ai.agent'].sudo().browse(agent.id).exists()
                else False)
            # Same guard for the acting user: in tests the session runs as a user
            # created in the caller's uncommitted transaction, invisible on this
            # sibling cursor, so stamping it as user_id (or letting it become
            # create_uid/write_uid) raises MissingError / FK-violates. Fall back to
            # unset in that case; in production the user is always committed.
            user_id_val = (
                original_uid if original_uid
                and debug_env['res.users'].sudo().browse(original_uid).exists()
                else False)
            if not thread:
                thread_name = ''
                if hasattr(self, 'channel_id') and self.channel_id:
                    thread_name = self.channel_id.name or ''
                if not thread_name:
                    agent_name = agent.name if agent else ''
                    thread_name = agent_name or f'Session {session_id_str}'
                thread = debug_env['ai.debug.thread'].sudo().create({
                    'session_id': session_id_str,
                    'name': thread_name,
                    'agent_id': agent_id_val,
                    'user_id': user_id_val,
                    'is_background': session_is_background,
                })
            elif thread.is_background != session_is_background:
                thread.is_background = session_is_background

            # One debug loop spans the turn's many cron ticks: reuse a LIVE
            # current_debug_loop_id whose input_message still matches this turn's
            # user_query, else supersede the stale one and open fresh. The sync
            # path (is_cron_tick False) always creates.
            debug_loop = None
            loop_existed = False
            if is_cron_tick and self.id and self.sudo().current_debug_loop_id:
                candidate = debug_env['ai.debug.loop'].sudo().browse(
                    self.sudo().current_debug_loop_id).exists()
                if candidate and candidate.is_running:
                    if candidate.input_message == user_query:
                        debug_loop = candidate
                        loop_existed = True
                    else:
                        self._ai_debug_supersede_stale_loop(
                            debug_env, debug_cr, candidate, thread)
            if not debug_loop:
                # Post-approval continuation reuses the same user_query; label it
                # as an approval marker instead of re-pasting the input bubble.
                loop_input = user_query
                if is_cron_tick and user_query:
                    prev_loop = debug_env['ai.debug.loop'].sudo().search(
                        [('thread_id', '=', thread.id)], order='id desc', limit=1)
                    if (prev_loop and not prev_loop.is_running
                            and prev_loop.termination_reason == 'confirmation'
                            and prev_loop.input_message == user_query):
                        loop_input = '(confirmed)'
                debug_loop = debug_env['ai.debug.loop'].sudo().create({
                    'thread_id': thread.id,
                    'parent_tool_call_id': parent_tool_call_db_id or False,
                    'model_name': model,
                    'input_message': loop_input,
                    'is_running': True,
                    'start_time': fields.Datetime.now(),
                })
                if is_cron_tick and self.id:
                    # On the MAIN cursor: committed by the tick's terminal commit,
                    # reused by the next tick.
                    self.sudo().current_debug_loop_id = debug_loop.id

            _user = debug_env.user

            parent_thread_db_id = None
            if parent_tool_call_db_id:
                parent_call = debug_env['ai.debug.tool.call'].sudo().browse(
                    parent_tool_call_db_id)
                parent_thread_db_id = (
                    parent_call.iteration_id.loop_id.thread_id.id or None)

            if not thread_existed:
                _user._bus_send("AI_DEBUG_NEW_THREAD", {
                    'id': thread.id,
                    'session_id': session_id_str,
                    'name': thread.name,
                    'agent_id': self.agent_id.id if hasattr(self, 'agent_id') and self.agent_id else None,
                    'agent_name': self.agent_id.name if hasattr(self, 'agent_id') and self.agent_id else '',
                    'user_id': original_uid,
                    'user_name': self.env.user.name,
                    'loop_count': 0,
                    'parent_thread_id': parent_thread_db_id,
                    'is_background': session_is_background,
                })
            if not loop_existed:
                _user._bus_send("AI_DEBUG_NEW_LOOP", {
                    'id': debug_loop.id,
                    'thread_id': thread.id,
                    'session_id': session_id_str,
                    'parent_tool_call_id': parent_tool_call_db_id or None,
                    'agent_id': self.agent_id.id if hasattr(self, 'agent_id') and self.agent_id else None,
                    'agent_name': self.agent_id.name if hasattr(self, 'agent_id') and self.agent_id else '',
                    'model_name': model,
                    'provider': provider_name,
                    'input_message': debug_loop.input_message,
                    'input_message_html': debug_loop.input_message_html or False,
                    'is_running': True,
                    'start_time': debug_loop.start_time.isoformat(),
                    'is_background': session_is_background,
                })
            debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to create thread/loop records")
            return None

        # Wire the shared tracker for _handle_tool_calls / the iteration hook.
        ai_debug_tracker.debug_env = debug_env
        ai_debug_tracker.loop_id = debug_loop.id
        ai_debug_tracker.iteration_id = None
        ai_debug_tracker.uid = original_uid

        iteration_count = 0
        prev_messages_len = 0
        if loop_existed:
            # Continue numbering across ticks; seed the delta so only THIS tick's
            # appended messages are logged (not the whole rebuilt history).
            iteration_count = debug_env['ai.debug.iteration'].sudo().search_count(
                [('loop_id', '=', debug_loop.id)])
            prev_messages_len = len(messages) if messages is not None else 0

        ctx = {
            'debug_env': debug_env,
            'debug_cr': debug_cr,
            'debug_loop': debug_loop,
            'thread': thread,
            'user': _user,
            'provider_name': provider_name,
            'iteration_count': iteration_count,
            'pending_iteration_id': None,
            'prev_messages_len': prev_messages_len,
            'started_at': started_at,
            'original_uid': original_uid,
            'last_output': '',
        }
        ai_debug_tracker.loop_ctx = ctx
        return ctx

    def _ai_debug_install_iteration_hook(self, ctx, instructions, tools_context):
        """Install the pre-request hook that ai_provider_patch fires right before
        each LLM HTTP call, so the pending iteration row (and its spinner) exist
        before the (potentially long) call — and so tool.call rows can attach to
        ``ai_debug_tracker.iteration_id``."""
        debug_env = ctx['debug_env']
        debug_cr = ctx['debug_cr']
        debug_loop = ctx['debug_loop']
        _user = ctx['user']
        provider_name = ctx['provider_name']

        def _start_iteration():
            next_sequence = ctx['iteration_count'] + 1
            try:
                iteration_instructions = self._append_loaded_skills(instructions, tools_context)
            except Exception:
                _logger.warning(
                    "ai_debug: failed to augment instructions for iteration",
                    exc_info=True)
                iteration_instructions = instructions
            pending = debug_env['ai.debug.iteration'].sudo().create({
                'loop_id': debug_loop.id,
                'sequence': next_sequence,
                'is_running': True,
                'instructions': iteration_instructions,
            })
            ctx['iteration_count'] = next_sequence
            ctx['pending_iteration_id'] = pending.id
            ai_debug_tracker.iteration_id = pending.id
            _user._bus_send("AI_DEBUG_ITERATION_STARTED", {
                'id': pending.id,
                'loop_id': debug_loop.id,
                'sequence': next_sequence,
                'is_running': True,
                'tokens_in': 0,
                'tokens_cached': 0,
                'tokens_out': 0,
                'duration_ms': 0,
                'output_message': '',
                'messages_delta': None,
                'raw_response': None,
                'has_tool_calls': False,
                'is_final': False,
                'provider': provider_name,
                'available_tool_ids': [],
                'instructions': iteration_instructions,
            })
            debug_cr.commit()

        ai_debug_tracker.iteration_start_hook = _start_iteration

    def _ai_debug_finalize_iteration(self, ctx, outcome, messages, instructions,
                                     tools_context, is_running=False):
        """Finalize the iteration row for this step: token usage + timing from
        the patched request, per-tick messages delta, terminal output text, and
        the end-of-step tool ids. Prefers the pending row created by the start
        hook; synthesizes one if the hook never fired.

        ``is_running`` is left True by the CRON1 persist seam for a tool-calling
        reply: the model half is written now, but the iteration stays in-flight
        until CRON2 attaches its tool rows and closes it. Every other caller (the
        single-frame terminal step, the sync one-shot) closes the iteration here."""
        debug_env = ctx['debug_env']
        debug_cr = ctx['debug_cr']
        debug_loop = ctx['debug_loop']
        _user = ctx['user']
        provider_name = ctx['provider_name']

        try:
            completion_data = pop_last_completion_data()
            tokens = completion_data.get('tokens')
            llm_duration_ms = completion_data.get('llm_duration_ms')
            request_body = completion_data.get('request_body')
            raw_response = completion_data.get('raw_response')
        except Exception:
            _logger.warning("ai_debug: failed to pop completion data", exc_info=True)
            tokens = llm_duration_ms = request_body = raw_response = None

        raw_request = self._ai_debug_strip_request_body(request_body)
        messages_sent = self._ai_debug_extract_messages_sent(raw_request)

        extracted_text = ''
        if final_msg := outcome.get('final_message'):
            extracted_text = self._ai_debug_extract_text(final_msg)
            ctx['last_output'] = extracted_text

        try:
            full = list(messages) if messages is not None else []
            delta = self._ai_debug_strip_binary(full[ctx['prev_messages_len']:])
            full_len = len(full)
        except Exception:
            delta = None
            full_len = None

        current_tool_ids = self._ai_debug_current_tool_ids(tools_context)
        # Keep only tool ids visible on the sibling debug cursor: a tool created
        # in the caller's uncommitted transaction (tests) is invisible here, so
        # linking it via `available_tool_ids` would FK-violate and abort this
        # cursor — rolling back the WHOLE iteration finalize (stuck spinner) and
        # poisoning the loop finalize that follows. In production every tool is
        # committed, so nothing is filtered.
        if current_tool_ids:
            current_tool_ids = list(
                debug_env['ir.actions.server'].sudo().browse(current_tool_ids).exists().ids)
        has_tool_calls = bool(outcome.get('has_tool_calls'))
        is_final = outcome.get('kind') == 'terminal'

        try:
            values = {
                'is_running': is_running,
                'messages_delta': delta,
                'messages_sent': messages_sent,
                'raw_request': raw_request,
                'raw_response': raw_response,
                'output_message': extracted_text,
                'tokens_in': tokens.get('input', 0) if tokens else 0,
                'tokens_cached': tokens.get('cached', 0) if tokens else 0,
                'tokens_out': tokens.get('output', 0) if tokens else 0,
                'duration_ms': llm_duration_ms or 0,
                'available_tool_ids': [(6, 0, current_tool_ids)],
            }
            if ctx['pending_iteration_id']:
                debug_iteration = debug_env['ai.debug.iteration'].sudo().browse(
                    ctx['pending_iteration_id'])
                debug_iteration.with_user(SUPERUSER_ID).write(values)
            else:
                # Start hook never fired (e.g. a non-intercepted completion, or
                # the terminal step of a resume). Synthesize the row here.
                try:
                    fallback_instructions = self._append_loaded_skills(instructions, tools_context)
                except Exception:
                    fallback_instructions = instructions
                ctx['iteration_count'] += 1
                debug_iteration = debug_env['ai.debug.iteration'].sudo().create({
                    'loop_id': debug_loop.id,
                    'sequence': ctx['iteration_count'],
                    'instructions': fallback_instructions,
                    **values,
                })
            ai_debug_tracker.iteration_id = debug_iteration.id
            ctx['pending_iteration_id'] = None

            _user._bus_send("AI_DEBUG_ITERATION", {
                'id': debug_iteration.id,
                'loop_id': debug_loop.id,
                'sequence': ctx['iteration_count'],
                'is_running': is_running,
                'instructions': debug_iteration.instructions,
                'messages_delta': delta,
                'messages_sent': messages_sent,
                'raw_request': raw_request,
                'raw_response': raw_response,
                'output_message': extracted_text,
                'tokens_in': tokens.get('input', 0) if tokens else 0,
                'tokens_cached': tokens.get('cached', 0) if tokens else 0,
                'tokens_out': tokens.get('output', 0) if tokens else 0,
                'duration_ms': llm_duration_ms or 0,
                'has_tool_calls': has_tool_calls,
                'is_final': is_final,
                'provider': provider_name,
                'available_tool_ids': current_tool_ids,
            })
            debug_cr.commit()

            # Advance the delta cursor only after the commit succeeds so a failed
            # write is subsumed by the NEXT step's delta rather than lost.
            if full_len is not None:
                ctx['prev_messages_len'] = full_len
        except Exception:
            _logger.exception("ai_debug: failed to finalize iteration record")
            try:
                debug_cr.rollback()
            except Exception:
                _logger.exception(
                    "ai_debug: failed to rollback after iteration write error")

    def _ai_debug_finalize_loop(self, ctx, termination_reason, error_text,
                                is_cron_tick, confirmation_html=None):
        """Finalize the ai.debug.loop: clear is_running, store the terminal
        output / termination reason / duration, refresh the thread name, emit
        AI_DEBUG_LOOP_END, and (cron only) release the cross-tick handle so the
        next turn opens a fresh loop. Best-effort; never raises to the caller."""
        debug_cr = ctx['debug_cr']
        debug_loop = ctx['debug_loop']
        _user = ctx['user']
        thread = ctx['thread']
        started_at = ctx['started_at']
        try:
            if confirmation_html:
                # Already HTML (built in the tool): store as-is.
                output_html = confirmation_html
            elif ctx.get('last_output'):
                try:
                    output_html = markdown_format(ctx['last_output'])
                except Exception:
                    output_html = ctx['last_output']
            else:
                output_html = None
            if started_at is not None:
                duration_ms = int((time.monotonic() - started_at) * 1000)
            else:
                # The CRON2 seam finalizes a loop opened in a SEPARATE CRON1
                # invocation, so no single monotonic origin bridges them — measure
                # from the loop's persisted wall-clock start instead.
                start_time = debug_loop.start_time
                duration_ms = (
                    int((fields.Datetime.now() - start_time).total_seconds() * 1000)
                    if start_time else 0)
            debug_loop.with_user(SUPERUSER_ID).write({
                'is_running': False,
                'output_message': output_html,
                'termination_reason': termination_reason,
                'error_message': error_text,
                'duration_ms': duration_ms,
            })

            thread_name_update = None
            try:
                if hasattr(self, 'channel_id') and self.channel_id and self.channel_id.name:
                    if thread.name != self.channel_id.name:
                        thread.with_user(SUPERUSER_ID).write({'name': self.channel_id.name})
                        thread_name_update = self.channel_id.name
            except Exception:
                _logger.debug(
                    "ai_debug: could not update thread name at loop end", exc_info=True)

            loop_end_payload = {
                'id': debug_loop.id,
                'thread_id': thread.id,
                'is_running': False,
                'output_message': output_html,
                'termination_reason': termination_reason,
                'error_message': error_text,
                'duration_ms': duration_ms,
                'iteration_count': ctx['iteration_count'],
            }
            if thread_name_update:
                loop_end_payload['thread_name'] = thread_name_update
            _user._bus_send("AI_DEBUG_LOOP_END", loop_end_payload)
            debug_cr.commit()
            if is_cron_tick and self.id and self.sudo().current_debug_loop_id:
                self.sudo().current_debug_loop_id = False
            # The loop ended: drop any dangling per-round iteration pointer too
            # (a tools-pending round whose loop was finalized before CRON2 ran).
            if is_cron_tick and self.id and self.sudo().current_debug_iteration_id:
                self.sudo().current_debug_iteration_id = False
        except Exception:
            _logger.exception("ai_debug: failed to finalize loop record")

    def _ai_debug_supersede_stale_loop(self, debug_env, debug_cr, candidate, thread,
                                       termination_reason='superseded'):
        """Finalize a still-running loop left open by a deferred finalize, closing
        it with *termination_reason* and announcing the loop end. Two callers:
        ``superseded`` (default) when a paused-then-folded turn is overtaken by a
        base-level FRESH turn (a free-text refusal queued as a new root prompt),
        and ``cancelled`` when a cancel/Stop terminates the session at tick-top
        (``_ai_debug_close_cancelled_loop``). The caller repoints/clears the
        cross-tick handle. Best-effort: a failure here must never break the
        agentic loop (the worst case is the old behaviour)."""
        try:
            duration_ms = 0
            if candidate.start_time:
                delta = fields.Datetime.now() - candidate.start_time
                duration_ms = int(delta.total_seconds() * 1000)
            candidate.with_user(SUPERUSER_ID).write({
                'is_running': False,
                'termination_reason': termination_reason,
                'duration_ms': duration_ms,
            })
            debug_env.user._bus_send("AI_DEBUG_LOOP_END", {
                'id': candidate.id,
                'thread_id': thread.id,
                'is_running': False,
                'output_message': candidate.output_message or False,
                'termination_reason': termination_reason,
                'error_message': None,
                'duration_ms': duration_ms,
                'iteration_count': len(candidate.iteration_ids),
            })
            debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to finalize stale debug loop")

    # ------------------------------------------------------------------
    # Confirmation final-message instrumentation
    # ------------------------------------------------------------------

    def _ai_debug_update_confirmation_tool_results(
        self, tool_results, pending_call_ids, started_at, refused=False,
    ):
        """Finalize ai.debug.tool.call rows for both kinds of calls that
        surface in super()'s aggregated tool_outputs:

          1. Tools queued up behind the confirmation-triggering one
             (call_id in pending_call_ids) -- they actually run in this
             turn, so we record a fresh duration alongside the result.
          2. Tools that ran successfully *before* the confirmation
             interrupt in the original iteration (call_id NOT in
             pending_call_ids, e.g. a search_tool called in parallel with
             an update_tool). Base code stashes their results in
             pending_tools_results but turn-1's instrumented
             _handle_tool_calls returned on the confirmation before it
             could yield tool_results for them, so their rows are still
             at result=None. Write their result now; leave duration_ms
             untouched since turn-1's timing wasn't captured and
             overwriting with turn-2 time would be misleading.

        Idempotent: skip rows that already carry a non-null result so
        repeated passes (e.g. bus retries) don't clobber known data.

        ``refused`` (True only on the refusal-resume) marks the genuinely-
        declined confirmation calls -- those in ``pending_call_ids`` (the ones
        the user refused), never the parallel calls that ran before the
        interrupt -- so the viewer renders the refused pill on exactly the
        declined call.
        """
        original_uid = self.env.uid
        with self.env.registry.cursor() as debug_cr:
            debug_env = api.Environment(debug_cr, original_uid, {})
            _user = debug_env.user

            for result_item in tool_results:
                tool_call_data = result_item.get('tool_call', {})
                call_id = tool_call_data.get('call_id')
                if not call_id:
                    continue

                # Scope to THIS session's debug thread: call_id is unique only
                # within a session, so an unscoped search could resolve (and
                # later refuse-mark) another session's row sharing the call_id.
                tc_record = debug_env['ai.debug.tool.call'].search(
                    [('call_id', '=', call_id),
                     ('iteration_id.loop_id.thread_id.session_id', '=', str(self.id))],
                    limit=1,
                )
                if not tc_record or tc_record.result:
                    continue

                result = result_item.get('result')
                success = result_item.get('success', True)

                if is_ai_parts(result):
                    result_text = get_text_from_parts(result)
                    if not isinstance(result_text, str):
                        result_text = json.dumps(
                            result_text, default=json_default, ensure_ascii=False,
                        )
                elif result is not None:
                    result_text = result if isinstance(result, str) else json.dumps(
                        result, default=json_default, ensure_ascii=False,
                    )
                else:
                    result_text = None

                write_values: dict[str, object] = {'result': result_text}
                if call_id in pending_call_ids:
                    write_values['duration_ms'] = int(
                        (time.monotonic() - started_at) * 1000,
                    )
                    # Only the pending (declined) calls get the refused mark;
                    # parallel calls that ran before the interrupt succeeded.
                    if refused:
                        write_values['refused'] = True
                tc_record.with_user(SUPERUSER_ID).write(write_values)

                bus_payload = {
                    'id': tc_record.id,
                    'iteration_id': tc_record.iteration_id.id,
                    'loop_id': tc_record.iteration_id.loop_id.id,
                    'call_id': call_id,
                    'name': tc_record.name,
                    'result': result_text,
                    'success': success,
                }
                if 'duration_ms' in write_values:
                    bus_payload['duration_ms'] = write_values['duration_ms']
                if write_values.get('refused'):
                    bus_payload['refused'] = True
                _user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", bus_payload)
            debug_cr.commit()

    def _ai_debug_record_confirmation_final(self, final_message, confirmed_call_id=None):
        """Record a confirmed tool call's __final_message as a NEW loop.

        Called from the confirmation-resume step (`_ai_debug_step_resume`),
        which records the resolved confirmation without opening a spanning loop,
        so we open a dedicated debug cursor and look up the thread from the DB
        via session_id.

        The previous loop (which ended in the 'confirmation' state with the
        confirmation prompt as output_message) is deliberately left intact so
        its warning-styled agent bubble stays visible. Instead, we create a
        fresh loop representing the user's "Let's do it" turn: its output is
        the tool's final message text. The input bubble shows ``(confirmed:
        <tool_name>)`` -- there's no new user message driving this loop (the
        "Let's do it" reply lands on the root session's thread, not here when
        the confirmation came from a subagent), so labelling with the tool
        name is the most informative anchor.
        """
        session_id_str = str(self.id) if self.id else str(id(self))
        original_uid = self.env.uid

        # Plain text for the iteration record; HTML (via markdown_format) for
        # the loop's output_message so the chat bubble renders identically to
        # the core chatter.
        output_text = self._ai_debug_extract_text(final_message) if final_message else ''
        try:
            output_html = markdown_format(output_text) if output_text else ''
        except Exception:
            output_html = output_text

        with self.env.registry.cursor() as debug_cr:
            debug_env = api.Environment(debug_cr, original_uid, {})

            thread = debug_env['ai.debug.thread'].sudo().search(
                [('session_id', '=', session_id_str)], limit=1,
            )
            if not thread:
                return

            # Previous loop (the one that ended awaiting confirmation) -- used
            # to copy agent/model metadata so the new loop displays
            # consistently. Leave its fields untouched.
            prev_loop = debug_env['ai.debug.loop'].sudo().search(
                [('thread_id', '=', thread.id)],
                order='id desc', limit=1,
            )

            tool_name = ''
            if confirmed_call_id:
                tool_name = debug_env['ai.debug.tool.call'].sudo().search(
                    [('call_id', '=', confirmed_call_id)], limit=1,
                ).name or ''
            input_message = f'(confirmed: `{tool_name}`)' if tool_name else '(confirmed)'

            new_loop = debug_env['ai.debug.loop'].sudo().create({
                'thread_id': thread.id,
                'model_name': prev_loop.model_name if prev_loop else '',
                'input_message': input_message,
                'is_running': False,
                'output_message': output_html,
                'termination_reason': 'success',
                'start_time': fields.Datetime.now(),
                'duration_ms': 0,
            })

            debug_iteration = debug_env['ai.debug.iteration'].sudo().create({
                'loop_id': new_loop.id,
                'sequence': 1,
                'is_running': False,
                'output_message': output_text,
                'tokens_in': 0,
                'tokens_cached': 0,
                'tokens_out': 0,
                'duration_ms': 0,
            })

            _user = debug_env.user
            _user._bus_send("AI_DEBUG_NEW_LOOP", {
                'id': new_loop.id,
                'thread_id': thread.id,
                'session_id': session_id_str,
                'parent_tool_call_id': None,
                'agent_id': self.agent_id.id if hasattr(self, 'agent_id') and self.agent_id else None,
                'agent_name': self.agent_id.name if hasattr(self, 'agent_id') and self.agent_id else '',
                'model_name': new_loop.model_name,
                'provider': None,
                'input_message': input_message,
                'input_message_html': new_loop.input_message_html or False,
                'output_message': output_html,
                'is_running': False,
                'termination_reason': 'success',
                'start_time': new_loop.start_time.isoformat(),
            })
            # Synthetic confirmation iteration has no tools attached.
            _user._bus_send("AI_DEBUG_ITERATION", {
                'id': debug_iteration.id,
                'loop_id': new_loop.id,
                'sequence': 1,
                'is_running': False,
                'output_message': output_text,
                'tokens_in': 0,
                'tokens_cached': 0,
                'tokens_out': 0,
                'duration_ms': 0,
                'has_tool_calls': False,
                'is_final': True,
                'available_tool_ids': [],
            })
            _user._bus_send("AI_DEBUG_LOOP_END", {
                'id': new_loop.id,
                'thread_id': thread.id,
                'is_running': False,
                'output_message': output_html,
                'termination_reason': 'success',
                'error_message': None,
                'duration_ms': 0,
                'iteration_count': 1,
            })
            debug_cr.commit()

    # ------------------------------------------------------------------
    # Tool call instrumentation
    # ------------------------------------------------------------------

    def _ai_debug_commit_tracked(self, debug_env):
        """Commit the debug cursor -- but NEVER the job/request cursor (tripwire).

        Under the cron loop this runs inside the job tick, where ``self.env.cr``
        is the job cursor whose row lock must stay held, unbroken, until the
        tick's single terminal commit. The debug layer always writes on a
        dedicated sibling cursor, which is safe to commit. But the tracker's
        ``debug_env`` can be populated by any caller (the easy mistake is in
        ``_ai_debug_step_resume``, on the confirmation-resume path): if
        it ever aliases the job cursor, committing it here would silently
        release the held lock mid-tick and let a second worker SKIP-LOCKED-claim
        the still-paused row and double-run the confirmed tool. This guard turns
        that silent, data-corrupting lock-break into a loud, immediate failure.
        """
        if debug_env.cr is self.env.cr:
            raise RuntimeError(
                "ai_debug tried to commit the job/request cursor (debug_env.cr "
                "is self.env.cr). Under the held-lock cron loop this would "
                "release the row lock mid-tick and risk double-running a tool. "
                "The debug layer must commit only its own sibling cursor."
            )
        debug_env.cr.commit()

    def _before_tool_calls(self):
        """Ensure the pending iteration row exists before the tool batch runs, so
        the ``_handle_tool_calls`` override can attach tool.call rows to it.

        When the LLM request is intercepted (``ai_provider_patch._patched_request``
        fires ``iteration_start_hook`` right before the HTTP call), the pending row
        already exists and ``ai_debug_tracker.iteration_id`` is set — this is then a
        no-op. But the behavioural cron suites mock ``get_completions`` directly,
        which bypasses ``_patched_request``, so the hook never fires; without this
        seam ``iteration_id`` would still be ``None`` during the batch and every
        tool.call row would be skipped (the old generator avoided this by creating
        the row on its ``{'tool_calls'}`` yield, ahead of the batch). Idempotent:
        guarded on ``iteration_id`` so it never double-creates. Only fires the
        installed ``iteration_start_hook`` (fresh/sync steps that installed one);
        on the confirmation-resume step no hook is installed and the rows already
        exist, so this correctly does nothing."""
        if ai_debug_tracker.iteration_id:
            return
        start_hook = ai_debug_tracker.iteration_start_hook
        if start_hook is None:
            return
        try:
            start_hook()
        except Exception:
            _logger.warning(
                "ai_debug: _before_tool_calls failed to create the "
                "pending iteration row", exc_info=True)

    def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record, confirmed_tool_id=None, refuse_all=False, **kwargs):
        """Override to create ai.debug.tool.call records before/after each tool execution.

        Accesses the debug env and current iteration ID via the shared tracker
        set by _advance_one_step. If the tracker is not populated
        (instrumentation not active), delegates to super() without any overhead.

        ``**kwargs`` is an opaque forward of base-only arguments (e.g. the base's
        ``refusal_reason``) so a new base kwarg never breaks this override again.
        """
        debug_env = ai_debug_tracker.debug_env
        iteration_id = ai_debug_tracker.iteration_id
        loop_id = ai_debug_tracker.loop_id

        if not debug_env or not iteration_id:
            yield from super()._handle_tool_calls(
                tool_calls, tools_by_name, tools_context, record,
                confirmed_tool_id, refuse_all, **kwargs,
            )
            return

        # Tripwire: OUTSIDE the per-tool try/except below (whose `except Exception`
        # would swallow it); see _ai_debug_commit_tracked for why this is fatal.
        if debug_env.cr is self.env.cr:
            raise RuntimeError(
                "ai_debug._handle_tool_calls ran with debug_env aliased to the "
                "job/request cursor (debug_env.cr is self.env.cr). Committing it "
                "would release the held row lock mid-tick and risk double-running "
                "a tool. The debug layer must use its own sibling cursor."
            )

        _user = debug_env.user

        # Build lookup maps
        tool_calls_by_id = {tc['call_id']: tc for tc in tool_calls}

        # Which tool ids actually EXIST on the sibling debug cursor. A tool built
        # in the caller's own (uncommitted) transaction — common in tests — is
        # invisible on this separate connection, so linking `tool_id` to it would
        # FK-violate and ABORT the cursor mid-batch (poisoning the remaining rows,
        # the result writes, and the tool's own debug linkage → a corrupted tool
        # result). Store `tool_id=False` for such tools: the row (name/call_id/
        # args/result) is still captured, and in production — where tools are
        # always committed — every id is visible so `tool_id` is always set.
        batch_tool_ids = [t.id for t in tools_by_name.values() if t and t.id]
        visible_tool_ids = set(
            debug_env['ir.actions.server'].sudo().browse(batch_tool_ids).exists().ids
        ) if batch_tool_ids else set()

        # Create tool_call records BEFORE execution (one per tool in the batch)
        tc_records = {}  # call_id -> tool_call record
        tc_start_times = {}
        for tc in tool_calls:
            try:
                tool_action = tools_by_name.get(tc['name'])
                tool_id_val = tool_action.id if (tool_action and tool_action.id in visible_tool_ids) else False
                # sudo throughout: ai.debug.* rows are internal instrumentation
                # bookkeeping. The triggering user may lack ai.debug access (or,
                # in tests, not be committed on this sibling cursor), so writing
                # as the real user would AccessError / write_uid-FK and abort the
                # cursor. Keeping the record sudo makes later result/duration
                # writes privileged too (create_uid/write_uid = the committed
                # superuser). In production this is transparent.
                tc_record = debug_env['ai.debug.tool.call'].sudo().create({
                    'iteration_id': iteration_id,
                    'tool_id': tool_id_val,
                    'call_id': tc['call_id'],
                    'name': tc['name'],
                    'arguments': tc.get('args', {}),
                })
                tc_records[tc['call_id']] = tc_record

                _user._bus_send("AI_DEBUG_TOOL_CALL_STARTED", {
                    'id': tc_record.id,
                    'iteration_id': iteration_id,
                    'loop_id': loop_id,
                    'call_id': tc['call_id'],
                    'tool_name': tc['name'],
                    'name': tc['name'],
                    'tool_id': tool_id_val,
                    'arguments': tc.get('args', {}),
                })
                self._ai_debug_commit_tracked(debug_env)
            except Exception:
                _logger.exception("ai_debug: failed to create tool_call record for %s", tc.get('name'))
                # A failed create (most often an UNCOMMITTED tool_id — e.g. tools
                # built in a test's own transaction that the sibling debug cursor
                # cannot see → FK violation) leaves this sibling cursor ABORTED.
                # Roll it back to the last commit (the pending iteration row / a
                # prior tool-call row) so the rest of the batch degrades
                # gracefully: the remaining tool-call rows, the post-execution
                # result writes, and — crucially — the tool's OWN debug linkage
                # (ir_actions_server._ai_tool_run does a same-cursor search) don't
                # all fail with "current transaction is aborted" and corrupt the
                # actual tool result. SIBLING cursor only — never the job cr
                # (the tripwire above guarantees they are distinct).
                try:
                    debug_env.cr.rollback()
                except Exception:
                    _logger.exception(
                        "ai_debug: failed to roll back the debug cursor after a "
                        "tool_call create error")

            tc_start_times[tc['call_id']] = time.monotonic()

        for item in super()._handle_tool_calls(
            tool_calls, tools_by_name, tools_context, record,
            confirmed_tool_id, refuse_all, **kwargs,
        ):
            if tool_results := item.get('tool_results'):
                for result_item in tool_results:
                    try:
                        tool_call_data = result_item.get('tool_call', {})
                        call_id = tool_call_data.get('call_id')
                        result = result_item.get('result')
                        success = result_item.get('success', True)

                        # Serialize result to text
                        if is_ai_parts(result):
                            result_text = get_text_from_parts(result)
                            if not isinstance(result_text, str):
                                result_text = json.dumps(result_text, default=json_default, ensure_ascii=False)
                        elif result is not None:
                            result_text = result if isinstance(result, str) else json.dumps(result, default=json_default, ensure_ascii=False)
                        else:
                            result_text = None

                        tc_start = tc_start_times.get(call_id, time.monotonic())
                        duration = int((time.monotonic() - tc_start) * 1000)

                        tc_record = tc_records.get(call_id)
                        if tc_record:
                            tc_record.with_user(SUPERUSER_ID).write({
                                'result': result_text,
                                'duration_ms': duration,
                            })
                            _user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", {
                                'id': tc_record.id,
                                'iteration_id': iteration_id,
                                'loop_id': loop_id,
                                'call_id': call_id,
                                'name': tool_call_data.get('name'),
                                'result': result_text,
                                'success': success,
                                'duration_ms': duration,
                            })
                            self._ai_debug_commit_tracked(debug_env)
                    except Exception:
                        _logger.exception("ai_debug: failed to update tool_call record")

            elif confirmation := item.get('tool_confirmation_request'):
                # Stash for _advance_one_step: it labels the loop that parks
                # awaiting confirmation with this (already-HTML) message.
                ai_debug_tracker.last_confirmation_message = confirmation.get('message', '')
                try:
                    call_id = confirmation.get('call_id')
                    tc_record = tc_records.get(call_id)
                    tc_start = tc_start_times.get(call_id, time.monotonic())
                    duration = int((time.monotonic() - tc_start) * 1000)

                    if tc_record:
                        tc_record.with_user(SUPERUSER_ID).write({
                            'triggered_confirmation': True,
                            'confirmation_message': confirmation.get('message', ''),
                            'duration_ms': duration,
                        })
                        _user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", {
                            'id': tc_record.id,
                            'iteration_id': iteration_id,
                            'loop_id': loop_id,
                            'call_id': call_id,
                            'name': tool_calls_by_id.get(call_id, {}).get('name', 'unknown'),
                            'triggered_confirmation': True,
                            'confirmation_message': confirmation.get('message', ''),
                            'duration_ms': duration,
                        })
                        self._ai_debug_commit_tracked(debug_env)
                except Exception:
                    _logger.exception("ai_debug: failed to update tool_call confirmation")

            yield item

    # ------------------------------------------------------------------
    # Cron subagent debug linkage
    # ------------------------------------------------------------------

    def _lookup_tool_call_db_id_by_call_id(self, call_id):
        """Search the ai.debug.tool.call db id by its call_id on a FRESH debug
        cursor (the row was committed on the spawning parent's debug cursor;
        self.env.cr's REPEATABLE-READ snapshot may predate it)."""
        if not call_id:
            return False
        try:
            with self.env.registry.cursor() as debug_cr:
                debug_env = api.Environment(debug_cr, self.env.uid, {})
                rec = debug_env['ai.debug.tool.call'].sudo().search(
                    [('call_id', '=', str(call_id))], limit=1,
                )
                return rec.id or False
        except Exception:
            _logger.exception("ai_debug: failed to look up tool call db id by call_id")
            return False

    def _ai_debug_resolve_parent_tool_call(self):
        """Resolve the spawning parent's debug tool-call db id from THIS child's
        own incoming waiting wait edge call_id. This replaces the parent-side
        write of `child.parent_tool_call_db_id` (which committed an update to the
        child's ai.session row from the parent's cron cursor — the row the parent
        does not hold the tick lock on — and raced the cron claim's 40001). The
        child resolves it on its OWN tick, where it holds its own row lock. A
        re-asked subagent gets a fresh waiting edge each turn, so reading the live
        `waiting` edge always reflects the CURRENT turn's parent call (matching
        the old overwrite-on-each-link behaviour). Bypasses the runtime tracker
        on purpose: at the child's loop entry the tracker holds the child's own
        context, not the parent spawn call."""
        if not self.id:
            return False
        edge = self.env['ai.session.wait'].sudo().search(
            [('child_session_id', '=', self.id), ('state', '=', 'waiting')],
            order='id desc', limit=1,
        )
        if not edge:
            return False
        return self._lookup_tool_call_db_id_by_call_id(edge.call_id)

    def _finalize_subagent_tool_call_result(self, call_id, result_text, success=True, tool_action=None):
        """Flip the spawn/ask debug tool-call row to the child's report when
        the parent drains its wait edge. OVERWRITES any existing result — the
        spawn iteration already wrote a placeholder result on the row."""
        super()._finalize_subagent_tool_call_result(
            call_id, result_text, success=success, tool_action=tool_action)
        original_uid = self.env.uid
        try:
            with self.env.registry.cursor() as debug_cr:
                debug_env = api.Environment(debug_cr, original_uid, {})
                # Skip cleanly if the acting user is not committed on this sibling
                # cursor (an uncommitted test user): every write/bare-assignment/bus
                # send below would otherwise stamp/read that missing user and
                # FK-violate or MissingError. Production users are always committed.
                if not debug_env['res.users'].sudo().browse(original_uid).exists():
                    return
                tc_record = debug_env['ai.debug.tool.call'].sudo().search(
                    [('call_id', '=', str(call_id))], limit=1,
                )
                if not tc_record:
                    return
                tc_record.with_user(SUPERUSER_ID).write({'result': result_text})
                debug_env.user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", {
                    'id': tc_record.id,
                    'iteration_id': tc_record.iteration_id.id,
                    'loop_id': tc_record.iteration_id.loop_id.id,
                    'call_id': call_id,
                    'name': tc_record.name,
                    'result': result_text,
                    'success': success,
                })
                debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to finalize subagent tool_call row")

    def _on_tool_calls_refused(self, refused):
        """Flip the refused pill on tool-call rows when a session folds out of a
        superseded turn (`ai.session._fold_superseded`). `refused` is a list of
        (session_id, call_id) pairs: the holder's OWN refused confirmation call
        (scoped to the holder's thread) and the parent's spawn/ask call this fold
        resolves (scoped to the parent's thread). Data-driven, by call_id, never
        by row position — and replaces the old `refused_fold` wait-edge marker."""
        super()._on_tool_calls_refused(refused)
        by_session = {}
        for session_id, call_id in refused:
            by_session.setdefault(session_id, set()).add(str(call_id))
        for session_id, call_ids in by_session.items():
            self.browse(session_id)._ai_debug_mark_tool_calls_refused(call_ids)

    def _on_turn_superseded(self):
        """Finalize this session's still-running debug loop as `superseded` when a
        paused ancestor folds out of a turn without re-entering `_advance_one_step`
        (its loop was left running by a deferred finalize). Best-effort; releases
        the cross-tick handle so a later turn opens a fresh loop."""
        super()._on_turn_superseded()
        try:
            loop_id = self.sudo().current_debug_loop_id if self.id else False
            if not loop_id:
                return
            with self.env.registry.cursor() as debug_cr:
                debug_env = api.Environment(debug_cr, self.env.uid, {})
                candidate = debug_env['ai.debug.loop'].sudo().browse(loop_id).exists()
                if candidate and candidate.is_running:
                    self._ai_debug_supersede_stale_loop(
                        debug_env, debug_cr, candidate, candidate.thread_id)
            self.sudo().current_debug_loop_id = False
            self._ai_debug_release_iteration_handle()
        except Exception:
            _logger.exception("ai_debug: failed to close superseded loop on fold")

    def _consume_cancel_signal(self):
        """Finalize the in-flight debug loop as ``cancelled`` when a cancel/Stop
        TERMINATES the session at the top of the tick.

        The base consumes the cancel before ``_advance_one_step`` ever runs, so
        the loop's own ``finally`` (the only place that clears ``is_running`` and
        writes a ``termination_reason``) never fires: a cancelled session's
        ``ai.debug.loop`` would otherwise stay ``is_running=True`` /
        ``termination_reason=NULL`` forever and the viewer would show a perpetual
        spinner. Close the loop ONLY on an actual termination
        (``queue_state='terminated'``) — a foreground subagent cancel parks
        resumable-idle and a Stop+queued-prompt restarts, both of which keep their
        loop live (it continues, or is superseded by the next turn). Best-effort:
        a debug failure here must never break the cancel."""
        handled = super()._consume_cancel_signal()
        try:
            if handled and self.id and self.queue_state == 'terminated':
                self._ai_debug_close_cancelled_loop()
        except Exception:
            _logger.exception("ai_debug: failed to close cancelled debug loop")
        return handled

    def _ai_debug_close_cancelled_loop(self):
        """Finalize this session's still-running debug loop as ``cancelled`` (a
        cancel terminated the session at tick-top without re-entering
        ``_advance_one_step``, so its deferred finalize never ran). Mirrors
        ``_on_turn_superseded``: own sibling cursor, best-effort,
        releases the cross-tick handle so any later turn opens a fresh loop."""
        loop_id = self.sudo().current_debug_loop_id if self.id else False
        if not loop_id:
            return
        with self.env.registry.cursor() as debug_cr:
            debug_env = api.Environment(debug_cr, self.env.uid, {})
            candidate = debug_env['ai.debug.loop'].sudo().browse(loop_id).exists()
            # Skip the write path if the acting user is uncommitted on this sibling
            # cursor (an uncommitted test user) — supersede would stamp write_uid
            # with the missing user and FK-violate. Always release the cross-tick
            # handle below regardless. Production users are always committed.
            user_ok = debug_env['res.users'].sudo().browse(self.env.uid).exists()
            if candidate and candidate.is_running and user_ok:
                self._ai_debug_supersede_stale_loop(
                    debug_env, debug_cr, candidate, candidate.thread_id,
                    termination_reason='cancelled')
        self.sudo().current_debug_loop_id = False
        self._ai_debug_release_iteration_handle()

    def _ai_debug_mark_tool_calls_refused(self, call_ids):
        """Persist ``refused=True`` on the ai.debug.tool.call rows for *call_ids*
        and announce the change on the bus. Own sibling cursor; best-effort
        (a failure here must never break the agentic loop). Idempotent: rows
        already refused are skipped so a re-drain doesn't double-fire the bus."""
        if not call_ids:
            return
        original_uid = self.env.uid
        try:
            with self.env.registry.cursor() as debug_cr:
                debug_env = api.Environment(debug_cr, original_uid, {})
                # Skip cleanly for an uncommitted acting user (test): the bare
                # `tc.refused = True` write + bus send below would stamp/read that
                # missing user and FK-violate. Production users are committed.
                if not debug_env['res.users'].sudo().browse(original_uid).exists():
                    return
                # Scope to THIS session's debug thread: call_id is unique only
                # within a session (provider-global uniqueness is an unstated
                # invariant imports/replays/custom providers can break), so an
                # unscoped search would falsely mark another session's row that
                # happens to share the call_id.
                rows = debug_env['ai.debug.tool.call'].search([
                    ('call_id', 'in', list(call_ids)), ('refused', '=', False),
                    ('iteration_id.loop_id.thread_id.session_id', '=', str(self.id)),
                ])
                for tc in rows:
                    tc.refused = True
                    debug_env.user._bus_send("AI_DEBUG_TOOL_CALL_COMPLETED", {
                        'id': tc.id,
                        'iteration_id': tc.iteration_id.id,
                        'loop_id': tc.iteration_id.loop_id.id,
                        'call_id': tc.call_id,
                        'name': tc.name,
                        'refused': True,
                    })
                debug_cr.commit()
        except Exception:
            _logger.exception("ai_debug: failed to mark tool calls refused")
