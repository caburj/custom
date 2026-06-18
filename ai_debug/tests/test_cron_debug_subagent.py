# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Cron subagent debug linkage: the CHILD persists the parent spawn/ask
tool-call's debug-row id on ITS OWN session row (``parent_tool_call_db_id``) at
its first tick — resolved from its own waiting wait edge call_id, NOT written by
the parent (a parent-side write to the not-held child row raced the cron claim's
40001). The parent's drain of the wait edge finalizes the spawn/ask debug
tool.call row, overwriting the placeholder result the spawn iteration wrote.
Mirrors ``test_cron_debug_loop``'s dual-cursor pattern (committed fixtures, real
worker cursor, ai.debug.* rows read back on a fresh connection)."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import TestAICommon, mock_post_ai_response__flush_bus


@tagged('post_install', '-at_install', 'ai_cron_subagent')
class TestCronDebugSubagent(TestAICommon):

    def setUp(self):
        super().setUp()
        self.parent_agent_id = self._create_committed_agent('Cron Debug Parent')
        self.specialist_id = self._create_committed_agent('Cron Debug Specialist')
        self.addCleanup(self._cleanup_agents)

    def _create_committed_agent(self, name):
        """A COMMITTED OpenAI agent: visible to the worker cursor opened later
        AND to ai_debug's separate debug cursor (its ai.debug.thread.agent_id FK)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            agent = env['ai.agent'].create({
                'name': name, 'provider': 'openai', 'system_prompt': 'x'})
            agent_id = agent.id
            cr.commit()
            return agent_id
        finally:
            cr.close()

    def _cleanup_agents(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
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

    def _running_parent(self, env, query='delegate'):
        """A parent session with a queued fresh-turn prompt signal, ready to tick."""
        agent = env['ai.agent'].browse(self.parent_agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _spawn_call(self, env, call_id):
        spawn_tool = env.ref('ai.ir_actions_server_start_session')
        return [{'type': 'function_call', 'name': make_tool_name(spawn_tool),
                 'arguments': json.dumps({'agent_id': self.specialist_id,
                                          'starting_message': 'go', 'run_in_background': False}),
                 'call_id': call_id}]

    def _children_of(self, env, parent):
        return env['ai.session'].search([('parent_session_id', '=', parent.id)])

    def _tool_call_row(self, call_id):
        """Read the spawn debug tool.call row on a FRESH connection (the override
        commits it on its own cursor; neither the test nor the worker cursor sees
        it under REPEATABLE READ)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            rec = env['ai.debug.tool.call'].search([('call_id', '=', str(call_id))], limit=1)
            return {'id': rec.id, 'result': rec.result} if rec else None
        finally:
            cr.close()

    def _loop_with_parent_call(self, parent_call_id):
        """The ai.debug.loop back-linked to a given parent tool-call, read on a
        FRESH connection (committed on the child's own debug cursor)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            rec = env['ai.debug.loop'].search(
                [('parent_tool_call_id', '=', parent_call_id)], limit=1)
            return rec.id or None
        finally:
            cr.close()

    # ----- the parent's spawn tick does NOT write the child's session row -----

    def test_ai_debug_spawn_does_not_write_child_session_row(self):
        """The fix for the routine cron-claim 40001: the parent's spawn tick must
        NOT persist parent_tool_call_db_id on the child's ai.session row from the
        parent's (main) cursor — that committed write to a row the parent does not
        hold the tick lock on raced a sibling worker's claim. After the spawn tick
        the child's parent_tool_call_db_id is still EMPTY; the linkage is deferred
        to the child's own first tick (asserted by the next test). If this write
        comes back, the 40001 canary on the claim returns."""
        cr, env = self._worker()
        parent = self._running_parent(env)
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_norace')]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            parent._run_session_tick()
        child = self._children_of(env, parent)
        self.assertEqual(len(child), 1)
        self.assertFalse(child.parent_tool_call_db_id,
                         "the parent's spawn tick did NOT write the child's "
                         "ai.session row (no concurrent-write race source)")

    # ----- linkage persisted at the child's first tick (deferred, on own row) -----

    def test_ai_debug_parent_tool_call_db_id_persisted_at_child_first_tick(self):
        cr, env = self._worker()
        parent = self._running_parent(env)
        with self.mock_openai_api_request([
            self._spawn_call(env, 'call_spawn_dbg'),
            self.mock_text_response("Child work."),
        ]), self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            parent._run_session_tick()                 # spawn: NO child-row write
            child = self._children_of(env, parent)
            self.assertEqual(len(child), 1)
            self.assertFalse(child.parent_tool_call_db_id,
                             "not linked yet at the parent's spawn tick")
            child._run_session_tick()                  # child's first tick links on its OWN row
        row = self._tool_call_row('call_spawn_dbg')
        self.assertIsNotNone(row, "the spawn debug tool.call row exists")
        self.assertTrue(child.parent_tool_call_db_id,
                        "the child's first tick persisted the parent debug tool-call id "
                        "on its OWN held row")
        self.assertEqual(child.parent_tool_call_db_id, row['id'],
                         "child.parent_tool_call_db_id == the spawn tool-call's debug row id")
        # Viewer linkage intact: the child's debug loop back-links the parent call.
        self.assertEqual(self._loop_with_parent_call(row['id']),
                         self._child_loop_id(child),
                         "the child's debug loop is back-linked to the parent spawn call "
                         "(the debug viewer still shows the parent->child linkage)")

    def _child_loop_id(self, child):
        """The child's debug loop id, read on a FRESH connection."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            thread = env['ai.debug.thread'].search(
                [('session_id', '=', str(child.id))], limit=1)
            loop = env['ai.debug.loop'].search(
                [('thread_id', '=', thread.id)], order='id desc', limit=1)
            return loop.id or None
        finally:
            cr.close()

    # ----- finalize overwrites the placeholder on drain -----------------

    def test_ai_debug_finalize_overwrites_placeholder_on_drain(self):
        cr, env = self._worker()
        parent = self._running_parent(env)
        with self.mock_openai_api_request([
            self._spawn_call(env, 'call_spawn_fin'),
            self.mock_text_response("Child debug report."),
        ]), self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            parent._run_session_tick()                 # spawn -> placeholder result on debug row
            placeholder = self._tool_call_row('call_spawn_fin')
            self.assertIn('dispatched', (placeholder or {}).get('result') or '',
                          "the spawn iteration wrote a placeholder result on the debug row")
            child = self._children_of(env, parent)
            child._run_session_tick()                  # child terminal -> delivers its edge
            parent._run_session_tick()                 # drain -> finalize OVERWRITES
        row = self._tool_call_row('call_spawn_fin')
        self.assertIsNotNone(row)
        self.assertIn("Child debug report.", row['result'] or '',
                      "finalize overwrote the placeholder with the child report")
        self.assertNotIn('dispatched', row['result'] or '',
                         "the placeholder result is gone after the overwrite")
