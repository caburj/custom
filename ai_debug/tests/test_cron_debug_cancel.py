# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Loop-boundary rendering when a (background) session is CANCELLED.

A cancel/Stop is consumed at the TOP of the tick (`_consume_cancel_signal`),
BEFORE `_run_agentic_loop` ever runs — so the loop's own `finally` (the only path
that clears `is_running` / writes a `termination_reason`) never fires. A turn that
had parked across ticks left its debug loop running (deferred finalize), so without
the fix the cancelled session's `ai.debug.loop` stays `is_running=True` /
`termination_reason=NULL` forever and the viewer shows a perpetual spinner.

The fix: ai_debug overrides `_consume_cancel_signal` and, on an ACTUAL termination
(`queue_state='terminated'`), closes the open loop as `cancelled`
(`_ai_debug_close_cancelled_loop`). A FOREGROUND subagent cancel parks
resumable-idle (NOT terminated) and must keep its loop live (it resumes later) —
guarded by the second test.

Mirrors `test_cron_debug_subagent` / `test_cron_debug_fold`'s dual-cursor harness
(committed fixtures, real worker cursor, ai.debug.* rows read back on a fresh
connection) and the production recipe in
`ai.tests.test_background_cancel`."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import (
    TestAICommon, create_committed_ai_tool, mock_post_ai_response__flush_bus,
)


@tagged('post_install', '-at_install', 'ai_cron_cancel')
class TestCronDebugCancel(TestAICommon):

    def setUp(self):
        super().setUp()
        self.parent_agent_id = self._create_committed_agent('Cron Debug Cancel Parent')
        self.specialist_id = self._create_committed_agent('Cron Debug Cancel Specialist')
        # Committed tool — visible to the worker cursor AND to ai_debug's separate
        # debug cursor (its ai.debug.tool.call.tool_id FK).
        self.tool_id = create_committed_ai_tool(self.registry)
        self.spawn_tool = self.env.ref('ai.ir_actions_server_start_session')
        self.addCleanup(self._cleanup_fixtures)

    def _create_committed_agent(self, name):
        """A COMMITTED OpenAI agent: visible to the worker cursor opened later AND
        to ai_debug's separate debug cursor (its ai.debug.thread.agent_id FK)."""
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

    def _cleanup_fixtures(self):
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            env['ir.actions.server'].browse(self.tool_id).exists().unlink()
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
        """A front root session with a queued fresh-turn prompt signal, ready to
        tick. `originating_uid` is set so the background start / cancelled chat
        notifications have an author (D6)."""
        agent = env['ai.agent'].browse(self.parent_agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'originating_uid': env.uid,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _spawn_call(self, call_id, run_in_background=False):
        return [{'type': 'function_call', 'name': make_tool_name(self.spawn_tool),
                 'arguments': json.dumps({'agent_id': self.specialist_id,
                                          'starting_message': 'go',
                                          'run_in_background': run_in_background}),
                 'call_id': call_id}]

    def _children_of(self, env, parent):
        return env['ai.session'].search([('parent_session_id', '=', parent.id)])

    def _child_loop(self, session_id):
        """The child session's latest ai.debug.loop, read on a FRESH connection (the
        debug override commits it on its own cursor, invisible to the test/worker
        cursors under REPEATABLE READ)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            loop = env['ai.debug.loop'].search(
                [('thread_id.session_id', '=', str(session_id))], order='id desc', limit=1)
            if not loop:
                return None
            return {'is_running': loop.is_running,
                    'termination_reason': loop.termination_reason}
        finally:
            cr.close()

    def _open_running_child_loop(self, env, parent, child):
        """Tick the child once on a tool call so its debug loop opens and is left
        running across ticks (one iteration per tick → deferred finalize). Returns
        with the child `ready` and `current_debug_loop_id` live."""
        tool = env['ir.actions.server'].browse(self.tool_id)
        with self.mock_openai_api_request([self.mock_tool_response(tool)]), \
                self.mock_default_tools(tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertTrue(child.current_debug_loop_id,
                        "the child's tool-call tick opened a debug loop (cross-tick handle live)")
        loop = self._child_loop(child.id)
        self.assertTrue(loop and loop['is_running'],
                        "the child's debug loop is left running across ticks (deferred finalize)")

    # ----- cancelled BACKGROUND task: loop closes as 'cancelled', spinner stops -----
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_cancelled_background_loop_is_finalized_cancelled(self):
        """A background subagent with an OPEN running debug loop is cancelled; its
        tick consumes the cancel and TERMINATES (FR-17). The debug loop must be
        finalized `is_running=False`, `termination_reason='cancelled'` — NOT left
        spinning forever (the bug this guards: the cancel never re-enters
        `_run_agentic_loop`, so the loop's own finally never runs)."""
        cr, env = self._worker()
        parent = self._running_parent(env)

        # parent tick: spawn a BACKGROUND child (parent does not park; child gets a
        # kickoff prompt + a background incoming edge, is_background=True).
        with self.mock_openai_api_request([self._spawn_call('call_bg_spawn', run_in_background=True)]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            parent._run_session_tick()
        child = self._children_of(env, parent)
        self.assertEqual(len(child), 1)
        self.assertTrue(child.is_background, "the spawned child is a background task")

        # child opens a running, deferred debug loop.
        self._open_running_child_loop(env, parent, child)

        # Production cancel entry: an off-row cancel signal on the subtree.
        child._queue_cancel(reason='user_stop')
        with mock_post_ai_response__flush_bus():
            child._run_session_tick()           # cancel consumed first, no LLM call

        self.assertEqual(child.queue_state, 'terminated',
                         "an explicitly cancelled background task terminates (FR-17)")
        loop = self._child_loop(child.id)
        self.assertIsNotNone(loop)
        self.assertFalse(loop['is_running'],
                         "the cancelled loop's spinner stops (is_running cleared)")
        self.assertEqual(loop['termination_reason'], 'cancelled',
                         "the cancelled loop reads 'cancelled' in the viewer")
        self.assertFalse(child.current_debug_loop_id,
                         "the cross-tick handle is released on the cancelled loop close")

    # ----- FOREGROUND subagent cancel parks resumable: loop stays live (guard) -----
    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_cancelled_foreground_subagent_loop_is_not_closed(self):
        """A FOREGROUND subagent cancel parks the session resumable-idle (NOT
        terminated): its loop must stay live (it resumes on a later turn), so the
        close-as-cancelled path must NOT fire. Guards the `queue_state=='terminated'`
        precondition of the fix."""
        cr, env = self._worker()
        parent = self._running_parent(env)

        # parent tick: spawn a FOREGROUND child (parent parks awaiting it).
        with self.mock_openai_api_request([self._spawn_call('call_fg_spawn', run_in_background=False)]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            parent._run_session_tick()
        child = self._children_of(env, parent)
        self.assertEqual(len(child), 1)
        self.assertFalse(child.is_background, "the spawned child is a foreground subagent")

        self._open_running_child_loop(env, parent, child)

        child._queue_cancel(reason='user_stop')
        with mock_post_ai_response__flush_bus():
            child._run_session_tick()

        self.assertEqual(child.queue_state, 'idle',
                         "a foreground subagent cancel parks resumable-idle (not terminated)")
        loop = self._child_loop(child.id)
        self.assertIsNotNone(loop)
        self.assertTrue(loop['is_running'],
                        "the parked-resumable loop stays live (it resumes later), not cancelled")
        self.assertNotEqual(loop['termination_reason'], 'cancelled',
                            "a parked foreground subagent loop is not finalized cancelled")
