# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Data-driven `refused` marking on ai.debug.tool.call rows.

A tool call is marked refused ONLY from actual records, never from row position:
  (a) a confirmation call the user declined (the holder's pending call), AND
  (b) the parent's spawn/ask call resolved by the child's superseded fold.
A second-round re-delegation that DELIVERS NORMALLY must stay refused=False.

Both marks are driven from the (session_id, call_id) pairs the fold closes
(`ai.session._fold_superseded` → `_ai_debug_mark_refused_calls`), so they persist
even though the wait edge is unlinked at drain. Drives the real production
supersede-fold-then-redelegate path (mocked LLM tokens) on the dual-cursor
harness, then reads the committed ai.debug.tool.call rows back on a fresh
connection."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import TestAICommon, mock_post_ai_response__flush_bus


@tagged('post_install', '-at_install', 'ai_cron_refused')
class TestCronDebugRefused(TestAICommon):

    def setUp(self):
        super().setUp()
        self.parent_agent_id, self.specialist_id, self.confirm_tool_id = self._commit_fixtures()
        self.spawn_tool = self.env.ref('ai.ir_actions_server_start_session')
        self.addCleanup(self._cleanup_fixtures)

    def _commit_fixtures(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            parent = env['ai.agent'].create({
                'name': 'Cron Debug Refused Parent', 'provider': 'openai', 'system_prompt': 'x'})
            specialist = env['ai.agent'].create({
                'name': 'Cron Debug Refused Specialist', 'provider': 'openai', 'system_prompt': 'x'})
            tool = env['ir.actions.server'].create({
                'model_id': env['ir.model']._get_id('ai.agent'),
                'state': 'code', 'name': 'tool_w_confirm_refused', 'ai_tool_name': 'tool_w_confirm_refused', 'use_in_ai': True,
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

    def _spawn_call(self, env, call_id):
        return [{'type': 'function_call', 'name': make_tool_name(self.spawn_tool),
                 'arguments': json.dumps({'agent_id': self.specialist_id,
                                          'starting_message': 'go', 'run_in_background': False}),
                 'call_id': call_id}]

    def _confirm_call(self, env, call_id):
        tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        return [{'type': 'function_call', 'name': make_tool_name(tool),
                 'arguments': json.dumps({}), 'call_id': call_id}]

    def _children_of(self, env, parent):
        return env['ai.session'].search(
            [('parent_session_id', '=', parent.id)], order='id')

    def _refused(self, call_id):
        """Read the refused flag on the ai.debug.tool.call row (fresh connection:
        the debug override commits on its own cursor). Order by id desc so we
        read THIS run's row even if a prior run on the same DB committed a row
        with the same (hard-coded) call_id."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            rec = env['ai.debug.tool.call'].search(
                [('call_id', '=', str(call_id))], order='id desc', limit=1)
            return rec.refused if rec else None
        finally:
            cr.close()

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_refused_marks_only_folded_and_refused_calls_not_successful_redelegation(self):
        cr, env = self._worker()
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        root = self._running_root(env, 'update my user name')

        # --- round 1: spawn → child confirmation → free-text refusal → fold ---
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_1')]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child1 = self._children_of(env, root)
        self.assertEqual(len(child1), 1)
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_1')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child1._run_session_tick()
        self.assertEqual(child1.paused_reason, 'awaiting_user_confirmation')
        root._add_user_message(
            [{'type': 'text', 'content': {'data': 'do it differently'}}], False)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child1._run_session_tick()                         # supersede → fold → idle
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()                           # drain child → ready
            root._run_session_tick()                           # root folds → ready (queued prompt)
        self.assertEqual(root.queue_state, 'ready')

        # --- round 2: post-fold fresh turn re-delegates; the child SUCCEEDS ---
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_2')]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        child2 = self._children_of(env, root)[-1]
        self.assertNotEqual(child2.id, child1.id, "round 2 spawned a fresh child")
        with self.mock_openai_api_request([self.mock_text_response("Renamed successfully.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child2._run_session_tick()                         # child terminal success → delivers
        with self.mock_openai_api_request([self.mock_text_response("All set.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()                           # drain normal delivery → continue
            root._run_session_tick()                           # terminal text

        # (a) the deep confirmation call refused by the user
        self.assertTrue(self._refused('call_conf_1'),
            "the deep confirmation call resolved by a refusal is marked refused")
        # (b) the spawn whose child folded via supersede
        self.assertTrue(self._refused('call_spawn_1'),
            "the spawn resolved by the superseded fold is marked refused")
        # NOT the successful re-delegation
        self.assertFalse(self._refused('call_spawn_2'),
            "a normally-delivered re-delegation spawn is NOT marked refused")

    def _refused_for(self, call_id, session):
        """Read the refused flag on the ai.debug.tool.call row for *call_id*
        scoped to *session*'s debug thread (fresh connection)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            rec = env['ai.debug.tool.call'].search([
                ('call_id', '=', str(call_id)),
                ('iteration_id.loop_id.thread_id.session_id', '=', str(session.id)),
            ], limit=1)
            return rec.refused if rec else None
        finally:
            cr.close()

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_refused_does_not_bleed_across_sessions_sharing_a_call_id(self):
        """Two independent root sessions spawn with the SAME call_id. Refusing +
        folding session A must mark ONLY A's spawn row; B's never-refused spawn
        must stay refused=False. (call_id is unique only within a session;
        provider-global uniqueness is an unstated invariant imports/replays/custom
        providers can break.)"""
        cr, env = self._worker()
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)
        shared = 'shared_dup_call'
        sess_a = self._running_root(env, 'rename me A')
        sess_b = self._running_root(env, 'rename me B')

        # Both A and B spawn a subagent under the SAME call_id (their spawn rows
        # collide on call_id but live under different debug threads).
        with self.mock_openai_api_request([self._spawn_call(env, shared)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            sess_a._run_session_tick()
        with self.mock_openai_api_request([self._spawn_call(env, shared)]), \
                self.mock_default_tools(env['ir.actions.server']), mock_post_ai_response__flush_bus():
            sess_b._run_session_tick()
        child_a = self._children_of(env, sess_a)
        self.assertEqual(len(child_a), 1)

        # Drive ONLY A to a free-text refusal + fold.
        with self.mock_openai_api_request([self._confirm_call(env, 'conf_a')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child_a._run_session_tick()
        sess_a._add_user_message(
            [{'type': 'text', 'content': {'data': 'no thanks'}}], False)
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child_a._run_session_tick()                        # supersede → fold → idle
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            sess_a._run_session_tick()                         # A drains the child report
            sess_a._run_session_tick()                         # A folds itself

        # A's spawn folded → refused; B's identical-call_id spawn must NOT bleed.
        self.assertTrue(self._refused_for(shared, sess_a),
            "A's folded spawn is marked refused")
        self.assertFalse(self._refused_for(shared, sess_b),
            "B's never-refused spawn (same call_id) must stay refused=False")
