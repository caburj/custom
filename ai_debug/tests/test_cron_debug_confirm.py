# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The confirmation-resume path must trace on its OWN sibling cursor, never the
job cursor: while the confirmed tool executes on the resume tick,
``ai_debug_tracker.debug_env.cr`` must NOT be the tick's job cursor. Aliasing
``debug_env = self.env`` there would let ``_handle_tool_calls``' commits release
the held row lock mid-tick and double-run the confirmed tool (full rationale in
``_ai_debug_commit_tracked``); that revert turns this test red, and the
``_handle_tool_calls`` tripwire is the loud runtime backstop. Mirrors
``test_cron_debug_subagent``'s dual-cursor harness (committed fixtures, real
worker cursor)."""

import json
from textwrap import dedent
from unittest.mock import patch

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import TestAICommon, mock_post_ai_response__flush_bus
from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker


@tagged('post_install', '-at_install', 'ai_cron_confirm')
class TestCronDebugConfirm(TestAICommon):

    def setUp(self):
        super().setUp()
        self.agent_id, self.confirm_tool_id = self._commit_fixtures()
        self.addCleanup(self._cleanup_fixtures)

    def _commit_fixtures(self):
        """A COMMITTED OpenAI agent + confirm-requiring code tool: visible to the
        worker cursor opened later AND to ai_debug's own debug cursor (FK resolve)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            agent = env['ai.agent'].create({
                'name': 'Cron Debug Confirm', 'provider': 'openai', 'system_prompt': 'x'})
            tool = env['ir.actions.server'].create({
                'model_id': env['ir.model']._get_id('ai.agent'),
                'state': 'code', 'name': 'tool_w_confirm_dbg', 'use_in_ai': True,
                'code': dedent("""
                    if not ai['tool_request_confirmed']:
                        ai['tool_request_message'] = 'Do this?'
                    else:
                        ai['result'] = 'Confirmed!'
                """),
                'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            })
            ids = (agent.id, tool.id)
            cr.commit()
            return ids
        finally:
            cr.close()

    def _cleanup_fixtures(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            env['ir.actions.server'].browse(self.confirm_tool_id).exists().unlink()
            env['ai.agent'].browse(self.agent_id).exists().unlink()
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

    def _running_session(self, env, query='hello'):
        agent = env['ai.agent'].browse(self.agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _confirm_call(self, env, call_id):
        tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        return [{'type': 'function_call', 'name': make_tool_name(tool),
                 'arguments': json.dumps({}), 'call_id': call_id}]

    def test_confirmation_resume_traces_on_own_cursor_not_job_cursor(self):
        """While the confirmed tool runs on the resume tick, the ai_debug tracker
        env must be a SIBLING cursor, never the held job cursor (held-lock
        invariant). Reverting `debug_env = self.env` fails this assertion."""
        cr, env = self._worker()
        session = self._running_session(env)
        tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        IrActionsServer = type(env['ir.actions.server'])
        original_run = IrActionsServer._ai_tool_run
        captured = {}

        def _spy(self_action, record, arguments, tools_context):
            # Snapshot the live tracker cursor the instant the confirmed tool runs.
            dbg = ai_debug_tracker.debug_env
            if dbg is not None and tools_context.get('tool_request_confirmed'):
                captured['debug_cr'] = dbg.cr
                captured['is_job_cr'] = dbg.cr is cr
            return original_run(self_action, record, arguments, tools_context)

        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_dbg'),
                                           self.mock_text_response("Done")]), \
                self.mock_default_tools(tool), \
                mock_post_ai_response__flush_bus():
            session._run_session_tick()                       # pause for confirmation
            self.assertEqual((session.queue_state, session.paused_reason),
                             ('paused', 'awaiting_user_confirmation'), "parked awaiting confirmation")
            env['ai.session.signal'].create({'session_id': session.id, 'kind': 'confirm'})
            with patch.object(IrActionsServer, '_ai_tool_run', _spy):
                session._run_session_tick()                   # resume -> runs confirmed tool

        self.assertFalse(session.pending_tool_call_id, "pending cleared after confirm (resume tick ran)")
        self.assertIn('debug_cr', captured,
                      "the confirmed tool ran with the ai_debug tracker populated")
        self.assertFalse(captured['is_job_cr'],
                         "the confirmation-resume debug env MUST be a sibling cursor, "
                         "never the held job cursor self.env.cr (held-lock invariant)")
