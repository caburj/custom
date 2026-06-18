# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""One ai.debug.loop spans the many cron ticks of a turn: continued iteration
numbering, per-tick message deltas, finalize deferred until the turn ends.
Drives ``_run_session_tick`` on a real worker cursor whose snapshot postdates
setUp's committed fixtures (see ``_worker`` / setUp comments for the
cursor-visibility constraints)."""

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.ai.tests.common import (
    TestAICommon, create_committed_ai_tool, mock_post_ai_response__flush_bus,
)


@tagged('post_install', '-at_install', 'ai_cron_tick')
class TestCronDebugLoopSpansTicks(TestAICommon):

    def setUp(self):
        super().setUp()
        # Committed tool — visible to the worker cursor opened below AND to
        # ai_debug's separate debug cursor (its ai.debug.tool.call.tool_id FK).
        self.tool_id = create_committed_ai_tool(self.registry)
        # Committed OpenAI agent: the ai.debug.thread.agent_id FK resolves on the
        # debug cursor, and it predates every snapshot. A test-created
        # (uncommitted) agent would FK-violate there. The ai.ai_default_agent
        # module record is the Google provider, so this suite commits its OWN
        # OpenAI agent to match the OpenAI mocks below.
        self.agent_id = self._create_committed_agent('Cron Debug Loop')
        self.addCleanup(self._cleanup_fixtures)

    def _create_committed_agent(self, name):
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
            env['ai.agent'].browse(self.agent_id).exists().unlink()
            cr.commit()
        except Exception:
            cr.rollback()
        finally:
            cr.close()

    def _worker(self):
        """A real connection whose snapshot postdates setUp's commits (so it sees
        the committed tool). Rolled back + closed at test end (its session /
        signal / channel writes are throwaway)."""
        cr = self.registry.cursor()
        self.addCleanup(cr.close)
        self.addCleanup(cr.rollback)
        return cr, Environment(cr, SUPERUSER_ID, {})

    def _make_running_session(self, env, query):
        """A session with a queued fresh-turn prompt signal, ready to tick."""
        agent = env['ai.agent'].browse(self.agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _loops_for(self, session_id):
        """ai.debug.loop rows for the session, read on a FRESH connection (the
        debug override commits them on its own cursor; neither the test cursor
        nor the worker cursor would otherwise see them under REPEATABLE READ)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            loops = env['ai.debug.loop'].search(
                [('thread_id.session_id', '=', str(session_id))], order='id')
            return [{
                'is_running': loop.is_running,
                'termination_reason': loop.termination_reason,
                'n_iterations': len(loop.iteration_ids),
                'sequences': loop.iteration_ids.sorted('sequence').mapped('sequence'),
                'deltas': loop.iteration_ids.sorted('sequence').mapped(
                    lambda it: len(it.messages_delta or [])),
            } for loop in loops]
        finally:
            cr.close()

    def test_one_loop_spans_ticks_with_continuing_sequence(self):
        """Across a 2-tick turn (tool call, then terminal text) there is exactly
        ONE ai.debug.loop, its iteration sequences continue 1,2 (not 1,1), and
        it is finalized only when the turn terminates."""
        cr, env = self._worker()
        session = self._make_running_session(env, 'span me')
        tool = env['ir.actions.server'].browse(self.tool_id)
        with self.mock_openai_api_request([
            self.mock_tool_response(tool),
            self.mock_text_response("Final."),
        ]), self.mock_default_tools(tool), mock_post_ai_response__flush_bus():
            # tick 1: tool call -> ready; the debug loop is created + persisted.
            session._run_session_tick()
            loops_after_t1 = self._loops_for(session.id)
            self.assertEqual(len(loops_after_t1), 1, "tick 1 creates exactly one loop")
            self.assertTrue(session.current_debug_loop_id, "the loop id is persisted on the session")
            self.assertTrue(loops_after_t1[0]['is_running'],
                "the loop is NOT finalized on a continuation tick (deferred finalize)")
            self.assertEqual(loops_after_t1[0]['n_iterations'], 1)

            # tick 2: continuation -> terminal text -> idle; reuses the SAME loop.
            # Both ticks share one worker transaction (events + current_debug_loop_id
            # are visible within it); commit-boundary survival is covered by
            # TestAiCronTickDriven, which drives real _agent_loop_tick commits.
            session._run_session_tick()

        loops_after_t2 = self._loops_for(session.id)
        self.assertEqual(len(loops_after_t2), 1,
            "the turn produced ONE debug loop spanning both ticks, not two")
        loop = loops_after_t2[0]
        self.assertEqual(loop['n_iterations'], 2, "both ticks' iterations are on the one loop")
        self.assertEqual(loop['sequences'], [1, 2],
            "iteration numbering continues across ticks, not restart at 1")
        self.assertFalse(loop['is_running'], "the loop is finalized once the turn terminated")
        self.assertEqual(loop['termination_reason'], 'success')
        self.assertFalse(session.current_debug_loop_id,
            "the cross-tick handle is cleared at turn end")

    def test_per_iteration_delta_not_full_history_each_tick(self):
        """The continuation tick's iteration delta is only what THIS tick
        appended, not the whole rebuilt history (prev_messages_len is seeded to
        the entry length when reusing a loop)."""
        cr, env = self._worker()
        session = self._make_running_session(env, 'delta check')
        tool = env['ir.actions.server'].browse(self.tool_id)
        with self.mock_openai_api_request([
            self.mock_tool_response(tool),
            self.mock_text_response("Done."),
        ]), self.mock_default_tools(tool), mock_post_ai_response__flush_bus():
            session._run_session_tick()             # tick 1 (iteration 1)
            session._run_session_tick()             # tick 2 (iteration 2)
        loops = self._loops_for(session.id)
        self.assertEqual(len(loops), 1)
        deltas = loops[0]['deltas']
        self.assertEqual(len(deltas), 2, "two iterations recorded")
        # With a re-seeded prev_messages_len the continuation iteration's
        # entry-length snapshot already covers the whole rebuilt history, so its
        # delta logs ZERO new messages; without the reseed (prev_messages_len=0)
        # the 2nd delta would re-log the entire rebuilt history (>=3 entries),
        # so this exact-0 assertion discriminates the regression precisely.
        self.assertEqual(deltas[1], 0,
            "the continuation iteration re-logged no history (prev_messages_len reseeded)")
