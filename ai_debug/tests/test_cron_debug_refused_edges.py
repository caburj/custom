# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Adversarial reviewer coverage for the data-driven `refused` mark
(commits 28867332896 / f9ed9f7c4e8). The whole point of the pill is HONESTY, so
these tests try to make the mark land on a call that was NOT refused:

  (b) the CONFIRM (approved) path must NOT mark refused.
  (c) a parallel tool call that ran BEFORE the confirmation interrupt
      (success) must NOT be marked when the confirmation is later refused.
  (d) call_id COLLISION across sessions: ``_ai_debug_mark_tool_calls_refused``
      searches ai.debug.tool.call by call_id with NO session/thread scoping. If
      two sessions share a call_id, one session's refusal bleeds the mark onto
      the other session's (successful) row. KNOWN-DEFECT (xfail): latent because
      provider call_ids are globally unique in production; the fix is to scope
      the mark to the session's thread. See reviewer.md.
  (e) a normal turn with no refusal anywhere marks nothing.

Reuses the dual-cursor harness of ``test_cron_debug_refused.TestCronDebugRefused``."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import mock_post_ai_response__flush_bus

from .test_cron_debug_refused import TestCronDebugRefused


@tagged('post_install', '-at_install', 'ai_cron_refused')
class TestCronDebugRefusedEdges(TestCronDebugRefused):

    def setUp(self):
        super().setUp()
        # A second, NON-confirming code tool, COMMITTED before the worker cursor
        # opens (so the worker env's snapshot can see it). Always returns a
        # result -> a successful sibling call in the same iteration as a
        # confirmation call (case (c)).
        self.plain_tool_id = self._commit_plain_tool()
        self.addCleanup(self._unlink_id, self.plain_tool_id)

    def _commit_plain_tool(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            tool = env['ir.actions.server'].create({
                'model_id': env['ir.model']._get_id('ai.agent'),
                'state': 'code', 'name': 'tool_plain_ok', 'use_in_ai': True,
                'code': "ai['result'] = 'plain ok'\n",
                'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            })
            tid = tool.id
            cr.commit()
            return tid
        finally:
            cr.close()

    def _unlink_id(self, tid):
        cr = self.registry.cursor()
        try:
            Environment(cr, SUPERUSER_ID, {})['ir.actions.server'].browse(tid).exists().unlink()
            cr.commit()
        except Exception:
            cr.rollback()
        finally:
            cr.close()

    def _refused_in_session(self, session_id, call_id):
        """Refused flag of the tool-call row scoped to ONE session's thread, so a
        cross-session call_id collision can be told apart (the by-call_id reader
        cannot). Fresh connection: the override commits on its own cursor."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            rec = env['ai.debug.tool.call'].search([
                ('call_id', '=', str(call_id)),
                ('iteration_id.loop_id.thread_id.session_id', '=', str(session_id)),
            ], order='id desc', limit=1)
            return rec.refused if rec else None
        finally:
            cr.close()

    def _plain_call(self, env, call_id):
        return {'type': 'function_call', 'name': make_tool_name(
            env['ir.actions.server'].browse(self.plain_tool_id)),
            'arguments': json.dumps({}), 'call_id': call_id}

    # ----------------------------------------------------------------- (b)
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_confirm_approved_path_does_not_mark_refused(self):
        """User APPROVES the confirmation (confirm=True). The confirmed call ran
        successfully — it must NOT carry the refused mark."""
        cr, env = self._worker()
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        root = self._running_root(env, 'please do it')

        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_ok')]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child = self._children_of(env, root)[-1]
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_ok')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.paused_reason, 'awaiting_user_confirmation')

        # APPROVE.
        env['ai.session']._route_confirmation(
            root.channel_id, child.pending_request_message_id.id)
        # child resume: confirmed tool runs, child produces its report.
        with self.mock_openai_api_request([self.mock_text_response("Done as asked.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()

        self.assertFalse(self._refused('call_conf_ok'),
            "an APPROVED confirmation call must never be marked refused")
        self.assertFalse(self._refused('call_spawn_ok'),
            "a spawn whose child approved+succeeded must not be marked refused")

    # ----------------------------------------------------------------- (c)
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_parallel_preinterrupt_success_call_not_marked_on_refusal(self):
        """In one child iteration a PLAIN tool runs (success, stashed) alongside a
        confirmation call. The user then refuses. Only the declined confirmation
        call may be marked — the parallel success call must stay refused=False."""
        cr, env = self._worker()
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        plain_tool = env['ir.actions.server'].browse(self.plain_tool_id)
        root = self._running_root(env, 'do two things')

        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_par')]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child = self._children_of(env, root)[-1]

        # one iteration, TWO calls: plain (runs first, stashed) + confirm (interrupts)
        parallel_resp = [self._plain_call(env, 'call_plain_par'),
                         self._confirm_call(env, 'call_conf_par')[0]]
        with self.mock_openai_api_request([parallel_resp]), \
                self.mock_default_tools(confirm_tool | plain_tool), \
                mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.paused_reason, 'awaiting_user_confirmation')

        root._add_user_message(
            [{'type': 'text', 'content': {'data': 'no thanks'}}], False)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool | plain_tool), \
                mock_post_ai_response__flush_bus():
            child._run_session_tick()                          # supersede → fold

        self.assertFalse(self._refused('call_plain_par'),
            "a parallel tool call that succeeded before the interrupt must NOT be "
            "marked refused when a sibling confirmation is later declined")

    # ----------------------------------------------------------------- (d)
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_call_id_collision_across_sessions_does_not_bleed_refused(self):
        """HONESTY STRESS (now FIXED, commit f1554ae351d): two independent root
        sessions reuse the SAME spawn call_id. Session A refuses+folds; session B
        parks (never refused). The refused-mark searches
        (``_ai_debug_mark_tool_calls_refused`` and
        ``_ai_debug_update_confirmation_tool_results``) are scoped to THIS
        session's debug thread (``iteration_id.loop_id.thread_id.session_id``), so
        A's refusal marks ONLY A's row — B's honest, non-refused spawn stays
        refused=False despite the shared call_id.

        call_id is unique only WITHIN a session; provider-global uniqueness is an
        unstated invariant imports/replays/custom providers can break, which is
        why the mark must be session-scoped rather than rely on it."""
        cr, env = self._worker()
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        dup = 'call_spawn_DUP'

        # Session B first: spawn `dup` and PARK (row B exists, refused=False).
        root_b = self._running_root(env, 'B task')
        with self.mock_openai_api_request([self._spawn_call(env, dup)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root_b._run_session_tick()
        self.assertEqual(root_b.paused_reason, 'awaiting_subagents')
        self.assertFalse(self._refused_in_session(root_b.id, dup),
                         "B's freshly-spawned row starts honest (not refused)")

        # Session A: spawn the SAME call_id, child confirm, refuse → fold → drain.
        root_a = self._running_root(env, 'A task')
        with self.mock_openai_api_request([self._spawn_call(env, dup)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root_a._run_session_tick()
        child_a = self._children_of(env, root_a)[-1]
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_A')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child_a._run_session_tick()
        root_a._add_user_message([{'type': 'text', 'content': {'data': 'no'}}], False)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child_a._run_session_tick()                       # supersede → fold (marks A's spawn refused)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root_a._run_session_tick()                        # drain child report
            root_a._run_session_tick()                        # root folds itself

        # A genuinely refused → marked.
        self.assertTrue(self._refused_in_session(root_a.id, dup),
                        "A's folded spawn is honestly marked refused")
        # B never refused → stays honest despite the shared call_id (the mark is
        # scoped to A's session/thread, so it cannot bleed onto B's row).
        self.assertFalse(self._refused_in_session(root_b.id, dup),
            "B's spawn was NOT refused; A's refusal must not bleed onto it via the "
            "shared call_id (mark search is session-scoped)")

    # ----------------------------------------------------------------- (e)
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_normal_subagent_turn_marks_nothing_refused(self):
        """A plain spawn → child success → drain → root terminal. No refusal
        anywhere: no tool-call row may carry refused."""
        cr, env = self._worker()
        root = self._running_root(env, 'just delegate')
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_clean')]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child = self._children_of(env, root)[-1]
        with self.mock_openai_api_request([self.mock_text_response("child report")]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        with self.mock_openai_api_request([self.mock_text_response("all done")]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()                          # drain
            root._run_session_tick()                          # terminal
        self.assertFalse(self._refused('call_spawn_clean'),
            "a normal subagent turn must not mark any tool call refused")
