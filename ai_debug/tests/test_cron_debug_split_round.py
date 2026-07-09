# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The two-cron tick split keeps capturing every model call.

The agent tick is split into two independently scheduled seams: CRON1
(``_persist_llm_reply``) obtains + persists the model reply, CRON2
(``_run_tools_and_route``) runs that reply's tools. A tool-calling round is
therefore advanced across TWO commits. This suite proves the developer trace
survives the split: the model-call capture (raw_request / raw_response / tokens)
written by CRON1 and the tool.call rows attached by CRON2 land on ONE
ai.debug.iteration — bridged by the durable ``current_debug_iteration_id`` — with
no lost capture and no orphan second iteration.

Drives the two seams as SEPARATE calls (``_llm_advance`` then ``_tool_advance``,
the halves the two production crons run), not the single-frame
``_run_session_tick``, so the durable cross-seam handoff is what is exercised.
Mocks ``requests.request`` BELOW the pipeline so the real provider stack runs and
the re-pointed ``_execute_prepared_request`` capture patch fires (the behavioural
suites that mock ``get_completions`` bypass it and assert structure, not capture).
"""

from unittest.mock import MagicMock, patch

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.ai.tests.common import (
    TestAICommon,
    create_committed_ai_tool,
    mock_post_ai_response__flush_bus,
)


def _fake_http_response(payload):
    """Stand-in for ``requests.request``'s return: ``.json()`` yields the raw
    provider response dict, ``.raise_for_status()`` is a no-op."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@tagged('post_install', '-at_install', 'ai_cron_tick', 'ai_debug_split_round')
class TestCronDebugSplitRound(TestAICommon):

    def setUp(self):
        super().setUp()
        # Committed tool + committed OpenAI agent: both visible on ai_debug's
        # separate debug cursor (its FKs resolve there) and predating every
        # snapshot, matching the OpenAI request/response capture asserted here.
        self.tool_id = create_committed_ai_tool(self.registry)
        self.agent_id = self._create_committed_agent('Cron Debug Split Round')
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
        cr = self.registry.cursor()
        self.addCleanup(cr.close)
        self.addCleanup(cr.rollback)
        return cr, Environment(cr, SUPERUSER_ID, {})

    def _make_running_session(self, env, query):
        agent = env['ai.agent'].browse(self.agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _iterations_for(self, session_id):
        """Iteration + attached-tool rows, read on a FRESH connection (the debug
        override commits them on its own cursor)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            iters = env['ai.debug.iteration'].search(
                [('loop_id.thread_id.session_id', '=', str(session_id))], order='sequence')
            return [{
                'id': it.id,
                'is_running': it.is_running,
                'raw_request': it.raw_request,
                'raw_response': it.raw_response,
                'tokens_in': it.tokens_in,
                'tokens_out': it.tokens_out,
                'n_tool_calls': len(it.tool_call_ids),
                'tool_names': it.tool_call_ids.mapped('name'),
            } for it in iters]
        finally:
            cr.close()

    def test_one_round_one_iteration_across_two_seams(self):
        """A tool-calling round advanced as CRON1 then CRON2 produces ONE
        iteration carrying BOTH the model-call capture (from CRON1) and the
        tool.call rows (from CRON2) — no blind spot, no orphan iteration."""
        _cr, env = self._worker()
        session = self._make_running_session(env, 'split round please')
        tool = env['ir.actions.server'].browse(self.tool_id)

        usage = {'input_tokens': 7, 'output_tokens': 2, 'total_tokens': 9}
        tool_call_payload = {'output': self.mock_tool_response(tool), 'usage': usage}

        with patch(
            'odoo.addons.ai.services.ai_api_service.requests.request',
            return_value=_fake_http_response(tool_call_payload),
        ), self.mock_default_tools(tool), mock_post_ai_response__flush_bus():
            # CRON1 — obtain + persist the model reply (a tool call). No tools run.
            session._llm_advance()

            self.assertEqual(
                session.queue_state, 'tools_pending',
                "CRON1 persisted a tool-calling reply and handed off to the tool cron")
            self.assertTrue(
                session.current_debug_iteration_id,
                "CRON1 stashed the round's iteration id for CRON2 to re-attach to")
            iter_id = session.current_debug_iteration_id

            iters_after_cron1 = self._iterations_for(session.id)
            self.assertEqual(len(iters_after_cron1), 1, "CRON1 opened exactly one iteration")
            it1 = iters_after_cron1[0]
            self.assertEqual(it1['id'], iter_id)
            # The model call is captured on the iteration NOW — before any tool runs.
            self.assertIsInstance(it1['raw_request'], dict, "raw_request captured by CRON1")
            self.assertIsInstance(it1['raw_response'], dict, "raw_response captured by CRON1")
            self.assertIn('usage', it1['raw_response'],
                "raw_response is the full provider payload, carrying usage")
            self.assertEqual(it1['tokens_in'], 7)
            self.assertEqual(it1['tokens_out'], 2)
            self.assertTrue(it1['is_running'],
                "the iteration stays in-flight until CRON2 runs its tools")
            self.assertEqual(it1['n_tool_calls'], 0, "no tool rows yet — CRON2 has not run")

            # CRON2 — run the reply's tools and route.
            session._tool_advance()

        self.assertFalse(
            session.current_debug_iteration_id,
            "CRON2 released the per-round iteration handle")

        iters_after_cron2 = self._iterations_for(session.id)
        self.assertEqual(len(iters_after_cron2), 1,
            "still ONE iteration — CRON2 attached to CRON1's, no orphan second row")
        it2 = iters_after_cron2[0]
        self.assertEqual(it2['id'], iter_id,
            "CRON2 filled the SAME iteration CRON1 opened (durable current_debug_iteration_id)")
        self.assertFalse(it2['is_running'], "CRON2 closed the iteration")
        self.assertGreaterEqual(it2['n_tool_calls'], 1,
            "the round's tool.call rows are attached to CRON1's iteration")
        self.assertIn(tool.sudo().ai_tool_name, it2['tool_names'],
            "the executed tool's call row hangs off the model round's iteration")
        # The model-call capture survived the SECOND commit — no lost record.
        self.assertIsInstance(it2['raw_response'], dict,
            "raw_response still present after CRON2 (capture not blanked by the tool commit)")
        self.assertEqual(it2['tokens_in'], 7, "token capture intact after the tool commit")

    def test_threaded_capture_bridges_call_bundle_to_finalize(self):
        """Production's LLM batch runs the HTTP in a bare worker thread, so CRON1's
        capture travels on the ``call`` bundle (``prepared``/``result``), not the
        thread-local. ``_ai_debug_stash_completion`` bridges it onto the tracker the
        finalize reads, and ``pop_last_completion_data`` extracts tokens from it —
        the same path the same-thread capture patch feeds. This unit-covers that
        bridge, which the in-process pump (inline path, no worker thread) can't
        reach because only the threaded persist surfaces the two keys on ``call``."""
        from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker
        from odoo.addons.ai_debug.models.ai_provider_patch import (
            pop_last_completion_data,
        )
        ai_debug_tracker.__init__()  # pristine slots
        call = {
            'prepared': {'body': {
                'model': 'gpt-x', 'input': [{'role': 'user', 'content': 'hi'}]}},
            'result': {'ok': True, 'duration_ms': 42, 'raw_response': {
                'output': [],
                'usage': {'input_tokens': 5, 'output_tokens': 3, 'total_tokens': 8}}},
        }
        self.env['ai.session']._ai_debug_stash_completion(call)
        data = pop_last_completion_data()
        self.assertEqual(data['request_body'], call['prepared']['body'],
            "the request body is bridged from call['prepared'] to the finalize")
        self.assertEqual(data['raw_response'], call['result']['raw_response'],
            "the raw response is bridged from call['result']")
        self.assertEqual(data['llm_duration_ms'], 42, "duration comes from the executor result")
        self.assertEqual(data['tokens'], {'input': 5, 'output': 3, 'total': 8},
            "tokens are extracted from the bridged raw response (OpenAI usage)")

    def test_execute_prepared_request_patch_captures_on_the_running_thread(self):
        """The capture patch is re-pointed from ``_request`` to
        ``_execute_prepared_request`` (where the split moved the socket call). A
        completion prepared-request stashes the request body and, on success, the
        raw response + duration onto the tracker for the same-thread finalize; a
        non-completion prepared-request is passed through untouched."""
        from unittest.mock import patch

        from odoo.addons.ai.services.ai_api_service import AIApiService
        from odoo.addons.ai_debug.models.agent_runtime_tracker import ai_debug_tracker
        from odoo.addons.ai_debug.models.ai_provider_patch import (
            pop_last_completion_data,
        )
        ai_debug_tracker.__init__()
        prepared = {
            'method': 'POST',
            'url': 'https://api.openai.test/v1/responses',
            'body': {'model': 'gpt-x', 'input': []},
        }
        raw = {'output': [], 'usage': {'input_tokens': 2, 'output_tokens': 1, 'total_tokens': 3}}
        with patch(
            'odoo.addons.ai.services.ai_api_service.requests.request',
            return_value=_fake_http_response(raw),
        ):
            result = AIApiService._execute_prepared_request(prepared)
        self.assertTrue(result.get('ok'), "the underlying executor still runs and returns its result")
        data = pop_last_completion_data()
        self.assertEqual(data['request_body'], prepared['body'],
            "the completion request body was captured on the running thread")
        self.assertEqual(data['raw_response'], raw, "the raw response was captured on success")
        self.assertEqual(data['tokens'], {'input': 2, 'output': 1, 'total': 3})
