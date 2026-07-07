# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Independent reviewer edge-case coverage for the post-fold loop-boundary
heuristic (commit 5d660f832ae).

The fix splits the root debug loop on a post-fold fresh turn by comparing the
live loop's ``input_message`` against this tick's ``user_query``
(``user_query_for_loop``). These tests probe the two failure modes a string
heuristic is most exposed to:

  (a) OVER-SPLIT — a genuinely-continuing ``awaiting_subagents`` turn (a normal
      subagent delivery, NOT a fold) that spans several cron ticks must stay ONE
      loop. If the comparison ever spuriously differed on a continuation tick it
      would shatter one turn into many loops. This is the MUST-NOT-REGRESS guard.

  (b) UNDER-SPLIT — when the free-text refusal happens to be byte-identical to
      the original prompt, the equality holds and the refusal is folded back into
      the original loop instead of opening its own. This is a documented, accepted
      limitation of the text-equality heuristic (rendering-only; production is
      unaffected). Pinned here as a characterization test so the boundary is
      visible and any future change to it is deliberate.

Reuses the dual-cursor harness of ``test_cron_debug_fold.TestCronDebugFold``."""

from odoo.tests import tagged
from odoo.tools import mute_logger

from .test_cron_debug_fold import TestCronDebugFold
from odoo.addons.ai.tests.common import mock_post_ai_response__flush_bus


@tagged('post_install', '-at_install', 'ai_cron_fold')
class TestCronDebugFoldEdges(TestCronDebugFold):

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_genuinely_continuing_subagent_turn_stays_one_loop(self):
        """A normal subagent round-trip (spawn → child terminal → root drains →
        root continues to its own terminal answer) is ONE user turn spanning
        several cron ticks. The deferred-finalize keeps ``current_debug_loop_id``
        live across those ticks; because ``user_query_for_loop`` is unchanged the
        reuse comparison holds and the whole turn stays a SINGLE root loop.

        This is the regression the fix must not introduce: the refusal split must
        never fire on a genuinely-continuing turn."""
        cr, env = self._worker()
        original = 'summarise the report'
        root = self._running_root(env, original)

        # tick 1 (fresh): root spawns the subagent → parks awaiting_subagents.
        # L1 opens (input=original), left running (deferred finalize), handle live.
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_cont')]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual((root.queue_state, root.paused_reason),
                         ('paused', 'awaiting_subagents'))
        self.assertTrue(root.current_debug_loop_id, "L1's cross-tick handle is live")
        child = self._children_of(env, root)
        self.assertEqual(len(child), 1)

        # child runs to a normal terminal answer → delivers its (non-fold) edge.
        with self.mock_openai_api_request([self.mock_text_response("Child report.")]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.queue_state, 'idle', "child finished its turn")

        # root drains the delivered edge (no LLM) → lands ready to continue.
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual(root.queue_state, 'ready', "same turn continues (not folded)")

        # root CONTINUATION tick: feeds the tool outputs back, produces its own
        # terminal answer. Same turn → must REUSE L1 (input still == original).
        with self.mock_openai_api_request([self.mock_text_response("Final answer.")]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual(root.queue_state, 'idle')

        loops = self._root_loops(root.id)
        self.assertEqual(len(loops), 1,
            "a genuinely-continuing subagent turn stays ONE root loop — the "
            "refusal split must NOT fire on a continuation tick")
        self.assertEqual(loops[0]['input_message'], original,
            "the single loop keeps the original prompt as its input bubble")
        self.assertFalse(loops[0]['is_running'], "the turn finalized")
        self.assertEqual(loops[0]['termination_reason'], 'success',
            "the continuing turn ended on a terminal answer, not superseded")

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_same_text_refusal_does_not_split_known_heuristic_limitation(self):
        """KNOWN LIMITATION (characterization, not a defect to fix here): when the
        free-text refusal is byte-identical to the original prompt, the
        ``input_message == user_query`` equality holds, so the post-fold fresh
        turn REUSES the original loop instead of opening its own. The two turns
        render as ONE loop.

        This is the accepted boundary of the text-equality heuristic:
        rendering-only, production fold/refuse is unaffected,
        and a user refusing with the exact original text is implausible. Pinned so
        the behaviour is explicit; if a future change makes this split into two
        loops, that is an improvement and this test should be updated."""
        cr, env = self._worker()
        same = 'update my user name'        # refusal text == original prompt text
        root = self._running_root(env, same)
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)

        # tick 1 (fresh): root spawns the subagent → parks. L1 opens (input=same).
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_same')]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual(root.paused_reason, 'awaiting_subagents')
        child = self._children_of(env, root)

        # child confirmation pause on the root channel.
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_same')]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()

        # user refuses with free text byte-identical to the original prompt →
        # supersede on root + child, prompt on root.
        root._add_user_message(
            [{'type': 'text', 'content': {'data': same}}], False)

        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()                          # supersede → fold → idle
        self.assertEqual(child.queue_state, 'idle')

        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()                           # drain child → ready
            root._run_session_tick()                           # root folds → ready (queued prompt)
        self.assertEqual(root.queue_state, 'ready')

        # root fresh post-fold turn: same text as the live loop → equality holds →
        # reuse (no split).
        with self.mock_openai_api_request([self.mock_text_response("Reworded attempt.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual(root.queue_state, 'idle')

        loops = self._root_loops(root.id)
        self.assertEqual(len(loops), 1,
            "KNOWN LIMITATION: an identical-text refusal is folded into the "
            "original loop (text-equality heuristic cannot distinguish them)")
        self.assertEqual(loops[0]['input_message'], same)
        self.assertEqual(loops[0]['termination_reason'], 'success',
            "the reused loop is finalized normally, not superseded")
