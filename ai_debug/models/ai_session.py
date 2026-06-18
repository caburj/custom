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

from odoo import api, fields, models
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
                debug_iteration = debug_env['ai.debug.iteration'].browse(pending_iteration_id)
                debug_iteration.sudo().write(values)
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
        """Override to capture the raw user query before provider formatting."""
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
        ``_run_agentic_loop`` regardless. ``_run_session_tick`` is the sole
        per-tick entrypoint and is never nested (tools call ``_run_agentic_loop``,
        not this), so a blanket reset here is safe (unlike inside the loop, whose
        save/restore guards nested calls)."""
        ai_debug_tracker.__init__()
        return super()._run_session_tick()

    # ------------------------------------------------------------------
    # Main loop instrumentation
    # ------------------------------------------------------------------

    @api.model
    def _run_agentic_loop(self, model, instructions, messages, tools_context, record=None, **completion_options):
        """Override to create ai.debug.* records during the agentic loop.

        Opens a separate cursor at loop start for all debug writes. Records are
        committed incrementally after each significant write point. Bus
        notifications go through the same debug env for atomicity.

        The debug env and current record IDs are stored on the shared tracker
        so _handle_tool_calls can create tool_call records without requiring
        changes to the method signature.
        """
        started_at = time.monotonic()
        termination_reason = 'success'
        termination_error = None
        last_output = ''
        pending_confirmation_message = None
        # Tracks how many messages have been written into previous iterations'
        # deltas; advanced after each successful create so failed writes are
        # subsumed by the next successful iteration's delta.
        prev_messages_len = 0

        # Under the cron loop (_run_session_tick) this method runs FRESH per
        # tick; the cron-only branches below keep one turn = one debug loop,
        # with continuous iteration numbering and per-tick deltas. The
        # synchronous (HTTP) path sets no flag.
        is_cron_tick = bool(self.env.context.get('_ai_cron_tick'))
        # Distinguish a terminal final_message (finalize) from the consumer
        # closing us mid-turn (continuation tick → defer the loop finalize).
        saw_final_message = False
        generator_exited = False

        # Capture the original user ID before switching to SUPERUSER for the
        # debug cursor.  Bus notifications must target this user so the
        # frontend (which subscribes to the user's own channel) receives them.
        original_uid = self.env.uid

        # Set in context by _get_direct_response, _run_session_tick and
        # _resume_pending_confirmation.
        user_query = self.env.context.get('_ai_debug_user_query', '')

        # Nested _run_agentic_loop fallback: tools like generate_image call
        # _get_direct_response internally, which re-enters this method on an
        # empty recordset (no parent_session_id, no self.id). The
        # ir.actions.server._ai_tool_run override sets
        # ai_debug_tracker.current_tool_call_db_id to the debug id of the
        # tool that is mid-execution, so we can link the synthetic child
        # thread to that tool call instead of leaving it orphaned.
        nested_parent_tool_call_db_id = ai_debug_tracker.current_tool_call_db_id

        # Provider name resolved once per loop
        provider_name = self._ai_debug_resolve_provider_name(model)

        # Open a dedicated cursor for debug records. This cursor lives for the
        # entire loop and is closed in the with-block's __exit__.
        with self.env.registry.cursor() as debug_cr:
            # Run as the real triggering user (no su): create_uid, ownership,
            # record rules and the bus target all stay the real user. The only
            # writes that need elevation are the ir.actions.server links, which
            # are scoped via .sudo() at their individual call sites.
            debug_env = api.Environment(debug_cr, original_uid, {})

            # Parent debug tool-call to link this child thread under. Resolved
            # from the child's OWN incoming waiting wait edge call_id and
            # persisted on the child's OWN held row (NOT written from the parent's
            # cursor — that raced the cron claim's 40001; see
            # _ai_debug_resolve_parent_tool_call / _link_subagent_for_debug). The
            # live edge always reflects the current turn, so a re-asked subagent
            # re-links correctly. Fall back to a previously-persisted value, then
            # to the nested-tool tracker (generate_image et al.).
            parent_tool_call_db_id = False
            if self.id:
                resolved = self._ai_debug_resolve_parent_tool_call()
                if resolved:
                    parent_tool_call_db_id = resolved
                    # Persist on our own held row for downstream reads/records;
                    # only write when it actually changes to avoid a needless
                    # per-tick UPDATE.
                    if self.sudo().parent_tool_call_db_id != resolved:
                        self.sudo().parent_tool_call_db_id = resolved
            if not parent_tool_call_db_id and self.id:
                parent_tool_call_db_id = self.sudo().parent_tool_call_db_id or False
            if not parent_tool_call_db_id and nested_parent_tool_call_db_id:
                parent_tool_call_db_id = nested_parent_tool_call_db_id

            # ----------------------------------------------------------
            # Get or create thread
            # ----------------------------------------------------------
            try:
                session_id_str = str(self.id) if self.id else str(id(self))
                thread = debug_env['ai.debug.thread'].search(
                    [('session_id', '=', session_id_str)], limit=1,
                )
                thread_existed = bool(thread)
                # ``is_background`` is PER-CALL on the session: it is (re)written
                # at every dispatch (``_cron_dispatch_child``), so a session first
                # run in background then continued in foreground flips it to False.
                # The debug thread caches a copy -- captured at create and
                # reconciled on every later turn (below) so the tree node's flag
                # tracks the latest run mode in both directions (bg->fg clears it,
                # fg->bg sets it). The live node is refreshed via the per-turn
                # AI_DEBUG_NEW_LOOP payload further down.
                session_is_background = bool(getattr(self, 'is_background', False))
                if not thread:
                    # Determine thread name: channel name may be empty when the
                    # conversation just started (Odoo generates it async after
                    # the first AI response via _generate_channel_name).
                    thread_name = ''
                    if hasattr(self, 'channel_id') and self.channel_id:
                        thread_name = self.channel_id.name or ''
                    if not thread_name:
                        agent_name = self.agent_id.name if hasattr(self, 'agent_id') and self.agent_id else ''
                        thread_name = agent_name or f'Session {session_id_str}'
                    thread = debug_env['ai.debug.thread'].create({
                        'session_id': session_id_str,
                        'name': thread_name,
                        'agent_id': self.agent_id.id if hasattr(self, 'agent_id') and self.agent_id else False,
                        'user_id': original_uid,
                        'is_background': session_is_background,
                    })
                elif thread.is_background != session_is_background:
                    thread.is_background = session_is_background

                # One debug loop spans the turn's many cron ticks: reuse a LIVE
                # current_debug_loop_id, else create one and (cron only) persist
                # its id for the next tick. The synchronous path always creates.
                debug_loop = None
                loop_existed = False
                if is_cron_tick and self.id and self.sudo().current_debug_loop_id:
                    candidate = debug_env['ai.debug.loop'].browse(
                        self.sudo().current_debug_loop_id).exists()
                    if candidate and candidate.is_running:
                        # The handle survives a paused-then-folded turn: a turn
                        # that parked `awaiting_subagents` defers its finalize, so
                        # the loop stays running across ticks. A genuinely-
                        # continuing turn re-enters with the SAME user_query
                        # (`user_query_for_loop` is rewritten only on a fresh-turn
                        # prompt drain), which equals the loop's input_message — so
                        # reuse and keep one loop. But a free-text refusal folds the
                        # paused turn and queues a NEW root prompt: the next tick is
                        # a base-level FRESH turn whose user_query (the refusal)
                        # DIFFERS from the stale loop's input_message. Reusing then
                        # would fold the refusal into the original prompt's loop;
                        # instead finalize the stale loop and open a fresh one below
                        # so the refusal renders as its own root turn.
                        if candidate.input_message == user_query:
                            debug_loop = candidate
                            loop_existed = True
                        else:
                            self._ai_debug_supersede_stale_loop(
                                debug_env, debug_cr, candidate, thread)
                if not debug_loop:
                    # Post-APPROVAL continuation: when the user approves a pending
                    # confirmation, the holder's loop was already finalized
                    # `confirmation` (its handle cleared), and the resume continues
                    # the SAME turn — so `user_query_for_loop` is UNCHANGED (no fresh
                    # user prompt drives an approval). Re-entering here with that same
                    # query would re-paste the prior input bubble (the duplicate the
                    # owner saw). Label the continuation as an approval marker
                    # instead. A genuine NEW turn after a confirmation (a redirect /
                    # re-ask) carries a DIFFERENT query and keeps its own text — the
                    # equality test below distinguishes the two, exactly like the
                    # live-loop seam above.
                    loop_input = user_query
                    if is_cron_tick and user_query:
                        prev_loop = debug_env['ai.debug.loop'].search(
                            [('thread_id', '=', thread.id)], order='id desc', limit=1)
                        if (prev_loop and not prev_loop.is_running
                                and prev_loop.termination_reason == 'confirmation'
                                and prev_loop.input_message == user_query):
                            loop_input = '(confirmed)'
                    # parent_tool_call_id is set on every loop (not just the
                    # first): a subagent session is reused across spawn/ask
                    # calls, each getting its own loop and parent back-link.
                    debug_loop = debug_env['ai.debug.loop'].create({
                        'thread_id': thread.id,
                        'parent_tool_call_id': parent_tool_call_db_id or False,
                        'model_name': model,
                        'input_message': loop_input,
                        'is_running': True,
                        'start_time': fields.Datetime.now(),
                    })
                    if is_cron_tick and self.id:
                        # On the main cursor: committed by the tick's
                        # _commit_progress, reused by the next tick.
                        self.sudo().current_debug_loop_id = debug_loop.id

                _user = debug_env.user

                # Resolve parent_thread_id for the bus payload. The thread's
                # ``parent_thread_id`` compute depends on ``loop_ids
                # .parent_tool_call_id`` -- accurate, but it's a stored
                # compute and we'd rather not bet on lazy-recompute timing
                # between create() and bus_send. Just walk the chain
                # directly from the parent tool-call we already have:
                # parent_call.iteration -> parent_call's loop -> that loop's
                # thread. Sidesteps any compute-flush ordering questions.
                parent_thread_db_id = None
                if parent_tool_call_db_id:
                    parent_call = debug_env['ai.debug.tool.call'].sudo().browse(
                        parent_tool_call_db_id,
                    )
                    parent_thread_db_id = (
                        parent_call.iteration_id.loop_id.thread_id.id or None
                    )

                # Send bus notification for new thread (if just created).
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
                        'is_background': bool(getattr(self, 'is_background', False)),
                    })

                # A reused cron loop was already announced on its first tick.
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
                        # Carries the thread's CURRENT run mode so the live node
                        # re-syncs its background flag each turn (see the JS
                        # AI_DEBUG_NEW_LOOP handler).
                        'is_background': session_is_background,
                    })
                debug_cr.commit()
            except Exception:
                _logger.exception("ai_debug: failed to create thread/loop records")
                # Fall through -- yield from super() without instrumentation
                yield from super()._run_agentic_loop(
                    model, instructions, messages,
                    tools_context, record, **completion_options,
                )
                return

            # Snapshot previous tracker state so nested loops (e.g.
            # generate_image -> _get_direct_response) can be restored on exit,
            # leaving the outer loop's instrumentation intact for its later
            # iterations. current_tool_call_db_id is owned by the
            # ir.actions.server._ai_tool_run override and not mirrored here.
            _saved_tracker = (
                ai_debug_tracker.debug_env,
                ai_debug_tracker.loop_id,
                ai_debug_tracker.iteration_id,
                ai_debug_tracker.uid,
                ai_debug_tracker.iteration_start_hook,
            )

            # Store on the shared tracker for _handle_tool_calls access
            ai_debug_tracker.debug_env = debug_env
            ai_debug_tracker.loop_id = debug_loop.id
            ai_debug_tracker.iteration_id = None
            ai_debug_tracker.uid = original_uid

            # Register a pre-request hook on the shared tracker so that
            # _patched_request can create the pending iteration row right
            # before each LLM HTTP call is dispatched. The hook mutates variables
            # in this function's scope (iteration_count, pending_iteration_id)
            # via a nonlocal binding so the post-response branch below can pick
            # up the row that was created at dispatch time and update it in
            # place instead of creating a second row.
            iteration_count = 0
            pending_iteration_id = None
            if loop_existed:
                # Continue numbering: this tick's iteration is N+1, not a
                # second "1".
                iteration_count = debug_env['ai.debug.iteration'].search_count(
                    [('loop_id', '=', debug_loop.id)])
                # `messages` already holds the full rebuilt history at entry;
                # seed so the delta is only what THIS tick appends (else the
                # whole history would re-log every tick).
                prev_messages_len = len(messages)

            def _start_iteration():
                nonlocal iteration_count, pending_iteration_id
                # Tentative sequence; only committed to iteration_count after
                # the create succeeds so a failed insert doesn't leave the
                # counter ahead of the real row count (which would shift every
                # subsequent iteration's sequence number).
                next_sequence = iteration_count + 1
                # Mirror the base loop's _append_loaded_skills call: the hook
                # fires right before the HTTP request is dispatched, after the
                # base loop has already computed and sent updated_instructions
                # to the provider. Recomputing here yields the same string
                # (tools_context hasn't mutated between those two points) and
                # lets us store what the LLM actually saw for this iteration.
                try:
                    iteration_instructions = self._append_loaded_skills(instructions, tools_context)
                except Exception:
                    _logger.warning(
                        "ai_debug: failed to augment instructions for iteration",
                        exc_info=True,
                    )
                    iteration_instructions = instructions
                # available_tool_ids left empty at start; the post-response
                # branch snapshots the end-of-iteration state so load_skills
                # additions made mid-iteration are reflected (see
                # _ai_debug_current_tool_ids docstring).
                pending = debug_env['ai.debug.iteration'].create({
                    'loop_id': debug_loop.id,
                    'sequence': next_sequence,
                    'is_running': True,
                    'instructions': iteration_instructions,
                })
                iteration_count = next_sequence
                pending_iteration_id = pending.id
                ai_debug_tracker.iteration_id = pending.id
                _user._bus_send("AI_DEBUG_ITERATION_STARTED", {
                    'id': pending.id,
                    'loop_id': debug_loop.id,
                    'sequence': iteration_count,
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

            try:
                for item in super()._run_agentic_loop(
                    model, instructions, messages,
                    tools_context, record, **completion_options,
                ):
                    if 'final_message' in item:
                        saw_final_message = True
                    if 'tool_calls' in item or 'final_message' in item:
                        # Pop completion data (tokens, timing) -- must happen immediately
                        # after the item arrives to avoid reading stale data.
                        try:
                            completion_data = pop_last_completion_data()
                            tokens = completion_data.get('tokens')
                            llm_duration_ms = completion_data.get('llm_duration_ms')
                            request_body = completion_data.get('request_body')
                            raw_response = completion_data.get('raw_response')
                        except Exception:
                            _logger.warning("ai_debug: failed to pop completion data", exc_info=True)
                            tokens = None
                            llm_duration_ms = None
                            request_body = None
                            raw_response = None

                        raw_request = self._ai_debug_strip_request_body(request_body)
                        messages_sent = self._ai_debug_extract_messages_sent(raw_request)

                        # Extract text from final message
                        extracted_text = ''
                        if final_msg := item.get('final_message'):
                            extracted_text = self._ai_debug_extract_text(final_msg)
                            last_output = extracted_text

                        # Compute per-iteration delta (strip binary for storage)
                        try:
                            full = list(messages)
                            delta = self._ai_debug_strip_binary(full[prev_messages_len:])
                            full_len = len(full)
                        except Exception:
                            delta = None
                            full_len = None

                        # Snapshot tool ids at the moment this iteration finished
                        # (load_skills can have mutated available_tools since loop start).
                        current_tool_ids = self._ai_debug_current_tool_ids(tools_context)

                        try:
                            # Prefer updating the pending row created by the
                            # start hook; fall back to creating a new row if the
                            # hook failed or never fired (e.g. a non-intercepted
                            # completion path).
                            values = {
                                'is_running': False,
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
                            # .sudo() scoped to the available_tool_ids link write
                            # (see _ai_debug_finalize_error_iteration).
                            if pending_iteration_id:
                                debug_iteration = debug_env['ai.debug.iteration'].browse(pending_iteration_id)
                                debug_iteration.sudo().write(values)
                            else:
                                # Fallback path: the start hook never fired, so
                                # there's no pre-existing row with the augmented
                                # instructions. Compute them here so the fresh
                                # row isn't missing that field.
                                try:
                                    fallback_instructions = self._append_loaded_skills(instructions, tools_context)
                                except Exception:
                                    fallback_instructions = instructions
                                iteration_count += 1
                                debug_iteration = debug_env['ai.debug.iteration'].sudo().create({
                                    'loop_id': debug_loop.id,
                                    'sequence': iteration_count,
                                    'instructions': fallback_instructions,
                                    **values,
                                })
                            ai_debug_tracker.iteration_id = debug_iteration.id
                            pending_iteration_id = None

                            # Bus notification + commit together (atomic).
                            # ``instructions`` is resent here (already on the
                            # STARTED payload) so a client that missed the
                            # STARTED bus message still gets the augmented
                            # system prompt and can render the System Prompt
                            # tab without needing a full thread reload.
                            _user._bus_send("AI_DEBUG_ITERATION", {
                                'id': debug_iteration.id,
                                'loop_id': debug_loop.id,
                                'sequence': iteration_count,
                                'is_running': False,
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
                                'has_tool_calls': 'tool_calls' in item,
                                'is_final': 'final_message' in item,
                                'provider': provider_name,
                                'available_tool_ids': current_tool_ids,
                            })
                            debug_cr.commit()

                            # Advance prev_messages_len only after commit succeeds. If the commit
                            # fails (or create/bus_send raise), the except branch swallows the
                            # error and prev_messages_len stays put, so the NEXT iteration's
                            # delta subsumes the skipped content rather than losing it.
                            if full_len is not None:
                                prev_messages_len = full_len
                        except Exception:
                            _logger.exception("ai_debug: failed to finalize iteration record")
                            try:
                                debug_cr.rollback()
                            except Exception:
                                _logger.exception("ai_debug: failed to rollback after iteration write error")

                    elif confirmation := item.get('tool_confirmation_request'):
                        pending_confirmation_message = confirmation.get('message', '') or ''

                    yield item

            except GeneratorExit:
                # The consumer closed us; record it so the finally block can
                # defer the loop finalize on a cron continuation tick. Must
                # re-raise (a generator may not swallow GeneratorExit).
                generator_exited = True
                raise

            except UserError as e:
                termination_reason = 'max_iterations' if 'successive' in str(e).lower() else 'error'
                termination_error = str(e)
                self._ai_debug_finalize_error_iteration(
                    debug_env, debug_cr, debug_loop, _user, messages,
                    prev_messages_len, tools_context, pending_iteration_id,
                    iteration_count, e, termination_error, instructions,
                )
                raise

            except Exception as e:
                termination_reason = 'error'
                termination_error = str(e)
                self._ai_debug_finalize_error_iteration(
                    debug_env, debug_cr, debug_loop, _user, messages,
                    prev_messages_len, tools_context, pending_iteration_id,
                    iteration_count, e, termination_error, instructions,
                )
                raise

            finally:
                # If a pending iteration is still flagged is_running (GeneratorExit
                # from a client disconnect, or a BaseException not routed through
                # the except branches above), clear the spinner so the frontend
                # doesn't show a forever-loading row. Best-effort: swallow any
                # DB/bus failure here since we're already in a finally clause.
                if pending_iteration_id:
                    try:
                        debug_env['ai.debug.iteration'].browse(pending_iteration_id).write({
                            'is_running': False,
                        })
                        _user._bus_send("AI_DEBUG_ITERATION", {
                            'id': pending_iteration_id,
                            'loop_id': debug_loop.id,
                            'sequence': iteration_count,
                            'is_running': False,
                            'tokens_in': 0,
                            'tokens_cached': 0,
                            'tokens_out': 0,
                            'duration_ms': 0,
                            'has_tool_calls': False,
                            'is_final': False,
                            'available_tool_ids': [],
                        })
                        debug_cr.commit()
                    except Exception:
                        _logger.exception("ai_debug: failed to clear pending iteration spinner")

                # A cron continuation tick (GeneratorExit, no terminal
                # final_message, no error) defers the loop finalize: the turn
                # continues on the next tick. Every other exit finalizes.
                defer_finalize = (
                    is_cron_tick and generator_exited
                    and not saw_final_message and termination_error is None
                    # A confirmation tick also GeneratorExits but parks the turn:
                    # finalize as 'confirmation' rather than leak a running loop.
                    and not pending_confirmation_message
                )

                if not defer_finalize:
                    try:
                        # A pending tool-confirmation takes precedence over any
                        # last_output: the confirmation prompt IS the agent's
                        # final message until the user confirms/refuses.
                        if pending_confirmation_message:
                            termination_reason = 'confirmation'
                            # Already HTML (markupsafe.Markup built in the tool):
                            # store as-is, do NOT run through markdown_format.
                            output_html = pending_confirmation_message
                        elif last_output:
                            try:
                                # markdown_format keeps the debug viewer's
                                # rendering identical to the core chatter.
                                output_html = markdown_format(last_output)
                            except Exception:
                                output_html = last_output
                        else:
                            output_html = None
                        debug_loop.write({
                            'is_running': False,
                            'output_message': output_html,
                            'termination_reason': termination_reason,
                            'error_message': termination_error,
                            'duration_ms': int((time.monotonic() - started_at) * 1000),
                        })

                        # Update thread name if channel now has a real name
                        # (Odoo generates channel names async after the first AI response)
                        thread_name_update = None
                        try:
                            if hasattr(self, 'channel_id') and self.channel_id and self.channel_id.name:
                                if thread.name != self.channel_id.name:
                                    thread.write({'name': self.channel_id.name})
                                    thread_name_update = self.channel_id.name
                        except Exception:
                            _logger.debug("ai_debug: could not update thread name at loop end", exc_info=True)

                        loop_end_payload = {
                            'id': debug_loop.id,
                            'thread_id': thread.id,
                            'is_running': False,
                            'output_message': output_html,
                            'termination_reason': termination_reason,
                            'error_message': termination_error,
                            'duration_ms': int((time.monotonic() - started_at) * 1000),
                            'iteration_count': iteration_count,
                        }
                        if thread_name_update:
                            loop_end_payload['thread_name'] = thread_name_update
                        _user._bus_send("AI_DEBUG_LOOP_END", loop_end_payload)
                        debug_cr.commit()
                        # Turn ended: release the cross-tick handle so the next
                        # turn on this session starts a fresh loop.
                        if is_cron_tick and self.id and self.sudo().current_debug_loop_id:
                            self.sudo().current_debug_loop_id = False
                    except Exception:
                        _logger.exception("ai_debug: failed to finalize loop record")

                # Restore (not clear) tracker state so an outer _run_agentic_loop
                # that is mid-tool-execution keeps its debug_env / loop_id /
                # iteration_id and its later iterations stay instrumented.
                (
                    ai_debug_tracker.debug_env,
                    ai_debug_tracker.loop_id,
                    ai_debug_tracker.iteration_id,
                    ai_debug_tracker.uid,
                    ai_debug_tracker.iteration_start_hook,
                ) = _saved_tracker

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
            candidate.write({
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

    def _handle_remaining_tool_calls(self, tools_context, confirm_pending=False, **kwargs):
        """Override to record the confirmation / refusal flow in the debug trace.

        ``**kwargs`` is an opaque forward of base-only arguments (e.g. the base's
        ``refusal_reason``) so a new base kwarg never breaks this override again.

        This path runs before _run_agentic_loop sets up the tracker, so
        _handle_tool_calls short-circuits via its tracker-empty guard and the
        previously-created ai.debug.tool.call row (from the turn that asked
        for confirmation) would stay at result=None forever. We therefore:
          1. Capture the call_ids about to be resolved (confirmed or refused).
          2. Watch super()'s yields: when tool_results arrives, find the
             existing debug row by call_id and write the actual result +
             duration so the frontend can flip it off "running".
          3. When a __final_message arrives from a confirmed tool, record it
             as a synthetic follow-up loop (existing behaviour).
        """
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

        # Capture the specific call_id that the user just confirmed before
        # super() clears self.pending_tool_call_id. Used to label the synthetic
        # confirmation-followup loop's input bubble with the tool's name --
        # otherwise the bubble would be empty (no new user message drives the
        # resume, only the user's "Let's do it" reply on the parent thread).
        confirmed_call_id = self.pending_tool_call_id if confirm_pending else None

        started_at = time.monotonic()

        # Expose a debug env on the shared tracker so that ir_actions_server
        # ._ai_tool_run can resolve each tool_call_id back to its original
        # ai.debug.tool.call row. Without this, parallel tool calls that ran
        # alongside the confirmation-triggering one (e.g. a second
        # start_session emitted in the same iteration) end up with an empty
        # tracker when they execute here: a fresh nested _run_agentic_loop
        # then reads current_tool_call_db_id=None and creates an unparented
        # thread instead of linking to its spawning tool call.
        #
        # Open a dedicated sibling cursor for that env — never alias it to
        # self.env, whose cursor is the job cursor under the cron tick:
        # see _ai_debug_commit_tracked for why committing it would be fatal.
        original_uid = self.env.uid
        saved_debug_env = ai_debug_tracker.debug_env
        with self.env.registry.cursor() as debug_cr:
            ai_debug_tracker.debug_env = api.Environment(debug_cr, original_uid, {})
            try:
                for item in super()._handle_remaining_tool_calls(tools_context, confirm_pending, **kwargs):
                    if tool_results := item.get('tool_results'):
                        try:
                            self._ai_debug_update_confirmation_tool_results(
                                tool_results, pending_call_ids, started_at,
                                # confirm_pending is False on the refusal resume:
                                # the pending calls were declined by the user, so
                                # mark them refused (data-driven, not by position).
                                refused=not confirm_pending,
                            )
                        except Exception:
                            _logger.exception(
                                "ai_debug: failed to update confirmation tool_results",
                            )

                    if confirm_pending and 'final_message' in item:
                        try:
                            self._ai_debug_record_confirmation_final(
                                item['final_message'], confirmed_call_id,
                            )
                        except Exception:
                            _logger.exception("ai_debug: failed to record confirmation final message")
                    yield item
            finally:
                ai_debug_tracker.debug_env = saved_debug_env

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
                tc_record = debug_env['ai.debug.tool.call'].sudo().search(
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

                write_values = {'result': result_text}
                if call_id in pending_call_ids:
                    write_values['duration_ms'] = int(
                        (time.monotonic() - started_at) * 1000,
                    )
                    # Only the pending (declined) calls get the refused mark;
                    # parallel calls that ran before the interrupt succeeded.
                    if refused:
                        write_values['refused'] = True
                tc_record.write(write_values)

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

        Called outside of _run_agentic_loop (fresh HTTP request thread for the
        confirmation reply), so we open a dedicated debug cursor and look up
        the thread from the DB via session_id.

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

            thread = debug_env['ai.debug.thread'].search(
                [('session_id', '=', session_id_str)], limit=1,
            )
            if not thread:
                return

            # Previous loop (the one that ended awaiting confirmation) -- used
            # to copy agent/model metadata so the new loop displays
            # consistently. Leave its fields untouched.
            prev_loop = debug_env['ai.debug.loop'].search(
                [('thread_id', '=', thread.id)],
                order='id desc', limit=1,
            )

            tool_name = ''
            if confirmed_call_id:
                tool_name = debug_env['ai.debug.tool.call'].search(
                    [('call_id', '=', confirmed_call_id)], limit=1,
                ).name or ''
            input_message = f'(confirmed: `{tool_name}`)' if tool_name else '(confirmed)'

            new_loop = debug_env['ai.debug.loop'].create({
                'thread_id': thread.id,
                'model_name': prev_loop.model_name if prev_loop else '',
                'input_message': input_message,
                'is_running': False,
                'output_message': output_html,
                'termination_reason': 'success',
                'start_time': fields.Datetime.now(),
                'duration_ms': 0,
            })

            debug_iteration = debug_env['ai.debug.iteration'].create({
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
        ``_handle_remaining_tool_calls``, on the confirmation-resume path): if
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

    def _handle_tool_calls(self, tool_calls, tools_by_name, tools_context, record, confirmed_tool_id=None, refuse_all=False, **kwargs):
        """Override to create ai.debug.tool.call records before/after each tool execution.

        Accesses the debug env and current iteration ID via the shared tracker
        set by _run_agentic_loop. If the tracker is not populated
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

        # Create tool_call records BEFORE execution (one per tool in the batch)
        tc_records = {}  # call_id -> tool_call record
        tc_start_times = {}
        for tc in tool_calls:
            try:
                tool_action = tools_by_name.get(tc['name'])
                # .sudo() scoped to this create because tool_id is a M2O to
                # ir.actions.server, which the triggering user may not read.
                # Drop sudo for storage so later result/duration writes run as
                # the real user.
                tc_record = debug_env['ai.debug.tool.call'].sudo().create({
                    'iteration_id': iteration_id,
                    'tool_id': tool_action.id if tool_action else False,
                    'call_id': tc['call_id'],
                    'name': tc['name'],
                    'arguments': tc.get('args', {}),
                }).with_user(debug_env.uid)
                tc_records[tc['call_id']] = tc_record

                _user._bus_send("AI_DEBUG_TOOL_CALL_STARTED", {
                    'id': tc_record.id,
                    'iteration_id': iteration_id,
                    'loop_id': loop_id,
                    'call_id': tc['call_id'],
                    'tool_name': tc['name'],
                    'name': tc['name'],
                    'tool_id': tool_action.id if tool_action else False,
                    'arguments': tc.get('args', {}),
                })
                self._ai_debug_commit_tracked(debug_env)
            except Exception:
                _logger.exception("ai_debug: failed to create tool_call record for %s", tc.get('name'))

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
                            tc_record.write({
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
                try:
                    call_id = confirmation.get('call_id')
                    tc_record = tc_records.get(call_id)
                    tc_start = tc_start_times.get(call_id, time.monotonic())
                    duration = int((time.monotonic() - tc_start) * 1000)

                    if tc_record:
                        tc_record.write({
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

    def _link_subagent_for_debug(self, child, call_id):
        """Intentionally a no-op: the parent→child debug linkage is NO LONGER
        persisted here. This used to do `child.parent_tool_call_db_id = db_id` on
        the parent's MAIN cron cursor — a COMMITTED update to the child's
        ai.session row the parent does NOT hold the tick lock on. That committed
        write to a claim-candidate row raced a sibling worker's claim and raised a
        serialization 40001 on the cron claim (the canary that claim now keeps
        visible). The linkage is instead resolved on the CHILD's first tick, from
        its own incoming waiting wait edge call_id and persisted on its OWN held
        row — see `_ai_debug_resolve_parent_tool_call`. Kept as a documented seam
        over the core hook."""
        super()._link_subagent_for_debug(child, call_id)

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
                tc_record = debug_env['ai.debug.tool.call'].sudo().search(
                    [('call_id', '=', str(call_id))], limit=1,
                )
                if not tc_record:
                    return
                tc_record.write({'result': result_text})
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

    def _ai_debug_mark_refused_calls(self, refused):
        """Flip the refused pill on tool-call rows when a session folds out of a
        superseded turn (`ai.session._fold_superseded`). `refused` is a list of
        (session_id, call_id) pairs: the holder's OWN refused confirmation call
        (scoped to the holder's thread) and the parent's spawn/ask call this fold
        resolves (scoped to the parent's thread). Data-driven, by call_id, never
        by row position — and replaces the old `refused_fold` wait-edge marker."""
        super()._ai_debug_mark_refused_calls(refused)
        by_session = {}
        for session_id, call_id in refused:
            by_session.setdefault(session_id, set()).add(str(call_id))
        for session_id, call_ids in by_session.items():
            self.browse(session_id)._ai_debug_mark_tool_calls_refused(call_ids)

    def _ai_debug_close_superseded_loop(self):
        """Finalize this session's still-running debug loop as `superseded` when a
        paused ancestor folds out of a turn without re-entering `_run_agentic_loop`
        (its loop was left running by a deferred finalize). Best-effort; releases
        the cross-tick handle so a later turn opens a fresh loop."""
        super()._ai_debug_close_superseded_loop()
        try:
            loop_id = self.sudo().current_debug_loop_id if self.id else False
            if not loop_id:
                return
            with self.env.registry.cursor() as debug_cr:
                debug_env = api.Environment(debug_cr, self.env.uid, {})
                candidate = debug_env['ai.debug.loop'].browse(loop_id).exists()
                if candidate and candidate.is_running:
                    self._ai_debug_supersede_stale_loop(
                        debug_env, debug_cr, candidate, candidate.thread_id)
            self.sudo().current_debug_loop_id = False
        except Exception:
            _logger.exception("ai_debug: failed to close superseded loop on fold")

    def _consume_cancel_signal(self):
        """Finalize the in-flight debug loop as ``cancelled`` when a cancel/Stop
        TERMINATES the session at the top of the tick.

        The base consumes the cancel before ``_run_agentic_loop`` ever runs, so
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
        ``_run_agentic_loop``, so its deferred finalize never ran). Mirrors
        ``_ai_debug_close_superseded_loop``: own sibling cursor, best-effort,
        releases the cross-tick handle so any later turn opens a fresh loop."""
        loop_id = self.sudo().current_debug_loop_id if self.id else False
        if not loop_id:
            return
        with self.env.registry.cursor() as debug_cr:
            debug_env = api.Environment(debug_cr, self.env.uid, {})
            candidate = debug_env['ai.debug.loop'].browse(loop_id).exists()
            if candidate and candidate.is_running:
                self._ai_debug_supersede_stale_loop(
                    debug_env, debug_cr, candidate, candidate.thread_id,
                    termination_reason='cancelled')
        self.sudo().current_debug_loop_id = False

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
                # Scope to THIS session's debug thread: call_id is unique only
                # within a session (provider-global uniqueness is an unstated
                # invariant imports/replays/custom providers can break), so an
                # unscoped search would falsely mark another session's row that
                # happens to share the call_id.
                rows = debug_env['ai.debug.tool.call'].sudo().search([
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
