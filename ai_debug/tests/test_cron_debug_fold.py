# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Loop-boundary rendering after a free-text refusal fold.

A subagent spawn parks the ROOT `awaiting_subagents`, so its debug loop is left
running with its cross-tick handle (`current_debug_loop_id`) still live (deferred
finalize). When the user then refuses the subagent's confirmation with FREE TEXT,
production folds the refusal up to the root and runs that text as a brand-new
root turn. The debug layer must render that fresh turn as its OWN root loop
(input_message = the refusal), NOT fold it into the still-open original loop.

Mirrors ``test_cron_debug_subagent`` / ``test_cron_debug_confirm`` dual-cursor
harness (committed fixtures, real worker cursor, ai.debug.* rows read back on a
fresh connection) and the production recipe
``ai.tests.test_ai_cron_confirm.test_refusal_folds_chain_to_root_then_runs_queued_prompt``."""

import json

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import make_tool_name
from odoo.addons.ai.tests.common import TestAICommon, mock_post_ai_response__flush_bus


@tagged('post_install', '-at_install', 'ai_cron_fold')
class TestCronDebugFold(TestAICommon):

    def setUp(self):
        super().setUp()
        self.parent_agent_id, self.specialist_id, self.confirm_tool_id = self._commit_fixtures()
        self.spawn_tool = self.env.ref('ai.ir_actions_server_start_session')
        self.addCleanup(self._cleanup_fixtures)

    def _commit_fixtures(self):
        """A COMMITTED parent + specialist agent and a confirm-requiring code tool:
        visible to the worker cursor opened later AND to ai_debug's own debug
        cursor (its ai.debug.thread.agent_id / ai.debug.tool.call.tool_id FKs)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            parent = env['ai.agent'].create({
                'name': 'Cron Debug Fold Parent', 'provider': 'openai', 'system_prompt': 'x'})
            specialist = env['ai.agent'].create({
                'name': 'Cron Debug Fold Specialist', 'provider': 'openai', 'system_prompt': 'x'})
            tool = env['ir.actions.server'].create({
                'model_id': env['ir.model']._get_id('ai.agent'),
                'state': 'code', 'name': 'tool_w_confirm_fold', 'use_in_ai': True,
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
        """A root session with a queued fresh-turn prompt signal, ready to tick."""
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
        return env['ai.session'].search([('parent_session_id', '=', parent.id)])

    def _root_loops(self, session_id):
        """ai.debug.loop rows for the ROOT session, read on a FRESH connection (the
        debug override commits them on its own cursor, invisible to the test/worker
        cursors under REPEATABLE READ). Subagent loops live on a different thread
        (different session_id) and are excluded."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            loops = env['ai.debug.loop'].search(
                [('thread_id.session_id', '=', str(session_id))], order='id')
            return [{
                'input_message': loop.input_message,
                'is_running': loop.is_running,
                'termination_reason': loop.termination_reason,
            } for loop in loops]
        finally:
            cr.close()

    @mute_logger('odoo.addons.ai.models.ai_session')
    def test_post_fold_fresh_turn_is_its_own_root_loop(self):
        """ROOT spawns a subagent (loop L1 opens, input=original prompt, parks
        awaiting_subagents → deferred finalize, handle still live). The user
        refuses the subagent's confirmation with free text; the refusal folds to
        the root and runs as a FRESH turn. The debug layer must open a SECOND root
        loop whose input_message is the refusal — not fold it into L1."""
        cr, env = self._worker()
        original, refusal = 'update my user name', 'do it differently'
        root = self._running_root(env, original)
        confirm_tool = env['ir.actions.server'].browse(self.confirm_tool_id)

        # tick 1 (fresh): root spawns the subagent → parks awaiting_subagents.
        # L1 opens with input_message=original and is left running (deferred).
        with self.mock_openai_api_request([self._spawn_call(env, 'call_spawn_fold')]), \
                self.mock_default_tools(env['ir.actions.server']), \
                mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual((root.queue_state, root.paused_reason),
                         ('paused', 'awaiting_subagents'), "root parked awaiting the subagent")
        self.assertTrue(root.current_debug_loop_id, "L1's cross-tick handle is live")
        child = self._children_of(env, root)
        self.assertEqual(len(child), 1)

        # child confirmation pause (surfaces its request on the root channel).
        with self.mock_openai_api_request([self._confirm_call(env, 'call_conf_fold')]), \
                self.mock_default_tools(confirm_tool), \
                mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual((child.queue_state, child.paused_reason),
                         ('paused', 'awaiting_user_confirmation'))

        # user refuses with free text → supersede on root + child, prompt on root.
        root._add_user_message(
            [{'type': 'text', 'content': {'data': refusal}}], False)

        # child supersede → FOLD (no LLM): delivers a NORMAL final_message edge,
        # ends idle (re-askable, NOT terminated).
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            child._run_session_tick()
        self.assertEqual(child.queue_state, 'idle', "the child folded to idle (re-askable)")

        # root drains the child report then folds itself (no LLM) → ready to run
        # the queued refusal prompt.
        with self.mock_openai_api_request([]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()                          # drain child → ready
            root._run_session_tick()                          # root folds → ready (queued prompt)
        self.assertEqual(root.queue_state, 'ready', "root re-enqueues to run the queued prompt")

        # root fresh post-fold turn: terminal text. The fix opens L2 here.
        with self.mock_openai_api_request([self.mock_text_response("Trying a different approach.")]), \
                self.mock_default_tools(confirm_tool), mock_post_ai_response__flush_bus():
            root._run_session_tick()
        self.assertEqual(root.queue_state, 'idle')

        loops = self._root_loops(root.id)
        self.assertEqual(len(loops), 2,
            "the post-fold refusal renders as its OWN root loop, not folded into "
            "the original prompt's loop")
        self.assertEqual(loops[0]['input_message'], original,
            "L1 keeps the original prompt as its input bubble")
        self.assertFalse(loops[0]['is_running'], "the stale L1 is finalized, not left running")
        self.assertEqual(loops[0]['termination_reason'], 'superseded',
            "L1 is closed as superseded by the fresh post-fold turn")
        self.assertEqual(loops[1]['input_message'], refusal,
            "L2's input bubble is the free-text refusal")
        self.assertFalse(loops[1]['is_running'])
        self.assertEqual(loops[1]['termination_reason'], 'success',
            "L2 ran the queued prompt to a terminal answer")
