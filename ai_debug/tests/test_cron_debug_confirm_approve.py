# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Loop-input rendering of an APPROVED confirmation that CONTINUES the turn.

When the user approves a pending confirmation, the holder's debug loop was already
finalized `confirmation` (its cross-tick handle cleared), and the confirm-resume
continues the SAME turn WITHOUT a fresh user prompt — so `user_query_for_loop` is
unchanged. The post-approval continuation tick must NOT re-paste that prior input
bubble (the duplicate the owner saw in /ai-debug); it must render as an approval
marker `(confirmed)`. A genuine NEW turn after a confirmation (a redirect/re-ask)
carries a DIFFERENT query and keeps its own text.

Exercises the owner's exact repro on a deep subagent: spawn → 1st confirmation →
free-text SUPERSEDE → re-ask → 2nd confirmation → APPROVE → continue → success.
Reuses the dual-cursor harness of ``test_cron_debug_fold.TestCronDebugFold``."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import TestAICommon, mock_post_ai_response__flush_bus


@tagged('post_install', '-at_install', 'ai_cron_confirm')
class TestCronDebugConfirmApprove(TestAICommon):

    def setUp(self):
        super().setUp()
        self.parent_agent_id, self.specialist_id, self.confirm_tool_id = self._commit_fixtures()
        self.spawn_tool = self.env.ref('ai.ir_actions_server_start_session')
        self.ask_tool = self.env.ref('ai.ir_actions_server_continue_session')
        self.addCleanup(self._cleanup_fixtures)

    def _commit_fixtures(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            parent = env['ai.agent'].create({
                'name': 'Confirm Approve Parent', 'provider': 'openai', 'system_prompt': 'x'})
            specialist = env['ai.agent'].create({
                'name': 'Confirm Approve Specialist', 'provider': 'openai', 'system_prompt': 'x'})
            tool = env['ir.actions.server'].create({
                'model_id': env['ir.model']._get_id('ai.agent'),
                'state': 'code', 'name': 'tool_w_confirm_appr', 'use_in_ai': True,
                'code': "if not ai['tool_request_confirmed']:\n"
                        "    ai['tool_request_message'] = 'Do this?'\n"
                        "else:\n"
                        "    ai['result'] = 'Confirmed!'\n",
                'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            })
            ids = (parent.id, specialist.id, tool.id)
            cr.commit()
            return ids
        finally:
            cr.close()

    def _cleanup_fixtures(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            env['ir.actions.server'].browse(self.confirm_tool_id).exists().unlink()
            env['ai.agent'].browse(
                [self.parent_agent_id, self.specialist_id]).exists().unlink()
            cr.commit()
        except Exception:
            cr.rollback()
        finally:
            cr.close()

    def _worker(self):
        cr = self.registry.cursor()
        self.addCleanup(cr.close)
        self.addCleanup(cr.rollback)
        return cr, Environment(cr, SUPERUSER_ID, {})

    def _running_root(self, env, query):
        agent = env['ai.agent'].browse(self.parent_agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _spawn_call(self, env, call_id, message):
        return [{'type': 'function_call', 'name': make_tool_name(self.spawn_tool),
                 'arguments': json.dumps({'agent_id': self.specialist_id,
                                          'starting_message': message, 'run_in_background': False}),
                 'call_id': call_id}]

    def _ask_call(self, env, call_id, child, question):
        return [{'type': 'function_call', 'name': make_tool_name(self.ask_tool),
                 'arguments': json.dumps({'session_id': child.id, 'question': question, 'run_in_background': False}),
                 'call_id': call_id}]

    def _confirm_call(self, env, call_id):
        tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        return [{'type': 'function_call', 'name': make_tool_name(tool),
                 'arguments': json.dumps({}), 'call_id': call_id}]

    def _children_of(self, env, parent):
        return env['ai.session'].search([('parent_session_id', '=', parent.id)])

    def _loops(self, session_id):
        """ai.debug.loop rows for *session_id*'s thread, read on a FRESH connection
        (the debug override commits on its own cursor)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            loops = env['ai.debug.loop'].search(
                [('thread_id.session_id', '=', str(session_id))], order='id')
            return [{'input_message': lp.input_message,
                     'is_running': lp.is_running,
                     'termination_reason': lp.termination_reason} for lp in loops]
        finally:
            cr.close()

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_approved_confirmation_continuation_renders_as_confirmed_not_duplicate(self):
        """Owner repro (deep agent): spawn → 1st confirmation → free-text SUPERSEDE →
        re-ask → 2nd confirmation → APPROVE → continue → success. The deep agent's
        post-approval continuation loop must render `(confirmed)`, NOT a second copy
        of the re-ask question."""
        cr, env = self._worker()
        original, redirect = 'rename user 2 to Mitchell', 'change user 2 to Na Na Na instead'
        root = self._running_root(env, 'rename my user')
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)

        # tick 1: root spawns the deep agent with the original instruction.
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn', original)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child = self._children_of(env, root)
        self.assertEqual(len(child), 1)

        # child 1st confirmation (loop L1, input=original).
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_1')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.paused_reason, 'awaiting_user_confirmation')

        # free-text SUPERSEDE: the child folds to idle, the root re-runs the new msg.
        root._add_user_message([{'type': 'text', 'content': {'data': redirect}}], False)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()                          # supersede fold -> idle
        self.assertEqual(child.queue_state, 'idle')
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()                           # drain child -> ready
            root._run_session_tick()                           # root folds -> ready (queued prompt)

        # root fresh turn on the redirect: re-asks the SAME (idle) child.
        with self.mock_openai_api_request([self._ask_call(env, 'call_ask', child, redirect)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()

        # child 2nd confirmation (loop L2, input=redirect).
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_2')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.paused_reason, 'awaiting_user_confirmation')

        # APPROVE the 2nd confirmation -> child runs the tool, then continues.
        env['ai.session']._route_confirmation(
            root.channel_id, child.pending_request_message_id.id, confirm=True)
        with self.mock_openai_api_request([self.mock_text_response("Renamed to Na Na Na.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()                          # resume: runs confirmed tool
            child._run_session_tick()                          # post-approval continuation -> terminal

        loops = self._loops(child.id)
        inputs = [lp['input_message'] for lp in loops]
        # The re-ask question must appear as an input bubble EXACTLY ONCE (L2);
        # the post-approval continuation must NOT re-paste it.
        self.assertEqual(inputs.count(redirect), 1,
            f"the redirect question must render as ONE input bubble, not duplicated; got {inputs!r}")
        self.assertIn('(confirmed)', inputs,
            f"the approved-confirmation continuation must render an approval marker; got {inputs!r}")
        # Specifically: the LAST (post-approval) loop is the approval marker.
        self.assertEqual(loops[-1]['input_message'], '(confirmed)',
            "the post-approval continuation loop is labelled `(confirmed)`")
        # And the confirmation loops keep their real input.
        self.assertEqual(inputs.count(original), 1, "the original instruction renders once")
