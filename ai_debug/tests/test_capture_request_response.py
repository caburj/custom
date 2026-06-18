# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Per-iteration ``messages_sent`` / ``raw_request`` / ``raw_response`` are
captured from the genuine HTTP layer and are DISTINCT.

The behavioural cron suites mock ``AIApiServiceOpenAI.get_completions`` directly,
which bypasses ``ai_provider_patch._patched_request`` -- so they never exercise
the request/response capture (the tracker stays empty and the three fields are
None). This suite instead mocks ``requests.request`` BELOW ``_request`` so the
full provider stack runs and the patched ``_request`` stashes the request body
and raw HTTP response on the tracker for the loop override to read back."""

from unittest.mock import MagicMock, patch

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.ai.tests.common import (
    TestAICommon, create_committed_ai_tool, mock_post_ai_response__flush_bus,
)


def _fake_http_response(payload):
    """A stand-in for ``requests.request``'s return: ``.json()`` yields the raw
    provider response dict, ``.raise_for_status()`` is a no-op."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


@tagged('post_install', '-at_install', 'ai_cron_tick', 'ai_debug_capture')
class TestCaptureRequestResponse(TestAICommon):

    def setUp(self):
        super().setUp()
        self.tool_id = create_committed_ai_tool(self.registry)
        # Committed OpenAI agent (NOT ai.ai_default_agent, which is the Google
        # provider): the ai.debug.thread.agent_id FK resolves on the debug cursor,
        # it predates every snapshot, and its provider matches the OpenAI request/
        # response capture this suite asserts on.
        self.agent_id = self._create_committed_agent('Capture Request Response')
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
        """A session with a queued fresh-turn prompt signal, ready to tick."""
        agent = env['ai.agent'].browse(self.agent_id)
        session = env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}], 'query': query}})
        return session

    def _iterations_for(self, session_id):
        """Iteration rows read on a FRESH connection (the override commits them
        on its own cursor)."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            iters = env['ai.debug.iteration'].search(
                [('loop_id.thread_id.session_id', '=', str(session_id))],
                order='sequence')
            return [{
                'sequence': it.sequence,
                'messages_sent': it.messages_sent,
                'raw_request': it.raw_request,
                'raw_response': it.raw_response,
                'messages_delta': it.messages_delta,
            } for it in iters]
        finally:
            cr.close()

    def test_messages_sent_and_raw_request_and_response_captured_distinctly(self):
        """A single terminal-text turn captures all three fields from the real
        HTTP layer, and Messages Sent != Raw Response."""
        _cr, env = self._worker()
        session = self._make_running_session(env, 'capture me please')

        raw_response_payload = {
            'output': [{
                'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': 'Captured.'}],
            }],
            'usage': {
                'input_tokens': 11, 'output_tokens': 3, 'total_tokens': 14,
            },
        }

        with patch(
            'odoo.addons.ai.services.ai_api_service.requests.request',
            return_value=_fake_http_response(raw_response_payload),
        ), mock_post_ai_response__flush_bus():
            session._run_session_tick()

        iters = self._iterations_for(session.id)
        self.assertEqual(len(iters), 1, "one iteration captured for the single LLM call")
        it = iters[0]

        # raw_response: the genuine HTTP payload, including usage (NOT the
        # post-processed output list the base loop puts in item['metadata']).
        self.assertIsInstance(it['raw_response'], dict)
        self.assertIn('usage', it['raw_response'],
            "raw_response is the full provider response, carrying usage")
        self.assertIn('output', it['raw_response'])

        # raw_request: the full request envelope sent to the provider.
        self.assertIsInstance(it['raw_request'], dict)
        # Read the agent on the worker cursor: it was committed in setUp after
        # self.env's snapshot began, so only the worker cursor (opened in this
        # test) sees it; self.env would raise MissingError.
        expected_model = env['ai.agent'].browse(self.agent_id)._get_llm_model()
        self.assertEqual(it['raw_request'].get('model'), expected_model)
        self.assertIn('input', it['raw_request'])
        self.assertIn('instructions', it['raw_request'])

        # messages_sent: the COMPLETE provider-format messages list actually
        # sent (request body 'input'); contains the user message, is a list,
        # and is NOT a 1-item delta-only payload.
        self.assertIsInstance(it['messages_sent'], list)
        self.assertTrue(it['messages_sent'], "messages_sent is non-empty (the real history)")
        self.assertEqual(it['messages_sent'], it['raw_request']['input'],
            "messages_sent mirrors the request body's messages list")

        # The two tabs must show DISTINCT data.
        self.assertNotEqual(it['messages_sent'], it['raw_response'],
            "Messages Sent and Raw Response are distinct (bug 1 fixed)")

    def test_messages_sent_grows_across_iterations(self):
        """messages_sent must GROW per iteration, not stay a 1-item delta:
        across a 2-tick turn (tool call, then terminal text) the 2nd iteration's
        captured messages_sent is strictly longer than the 1st (the request
        body's full cumulative history at each LLM call)."""
        _cr, env = self._worker()
        session = self._make_running_session(env, 'grow across iterations')
        tool = env['ir.actions.server'].browse(self.tool_id)

        usage = {'input_tokens': 9, 'output_tokens': 2, 'total_tokens': 11}
        tool_call_payload = {'output': self.mock_tool_response(tool), 'usage': usage}
        terminal_payload = {'output': self.mock_text_response('Done.'), 'usage': usage}

        with patch(
            'odoo.addons.ai.services.ai_api_service.requests.request',
            side_effect=[
                _fake_http_response(tool_call_payload),
                _fake_http_response(terminal_payload),
            ],
        ), self.mock_default_tools(tool), mock_post_ai_response__flush_bus():
            session._run_session_tick()             # tick 1 -> tool call (iteration 1)
            session._run_session_tick()             # tick 2 -> terminal text (iteration 2)

        iters = self._iterations_for(session.id)
        self.assertEqual(len(iters), 2, "one debug loop with two iterations across the ticks")
        m1 = iters[0]['messages_sent']
        m2 = iters[1]['messages_sent']
        self.assertIsInstance(m1, list)
        self.assertIsInstance(m2, list)
        self.assertTrue(m1, "iteration 1 messages_sent is non-empty")
        self.assertGreater(
            len(m2), len(m1),
            "messages_sent GROWS across iterations (iter 2 carries the assistant "
            "tool-call + tool output appended after iter 1) -- not stuck at 1 item")
        # Per-tick history rebuild re-injects a dynamic <odoo_current_context>
        # block, so the messages are not byte-identical across ticks -- assert on
        # structural growth, not equality: iter 2 carries the appended function
        # call + its output that iter 1 produced.
        self.assertTrue(
            any((msg.get('type') or '').startswith('function_call') for msg in m2),
            "iteration-2 messages_sent includes the tool-call round-trip appended after iteration 1")


@tagged('post_install', '-at_install', 'ai_debug_capture')
class TestMessagesSentNullFallback(TransactionCase):
    """A NULL ``messages_sent`` jsonb column reads back as ``False`` (Odoo Json
    field semantics), never ``None`` -- so rows without a capture must fall back
    to delta reconstruction; an ``is None`` guard would never fire for them."""

    def test_debug_expand_falls_back_to_delta_when_messages_sent_unset(self):
        agent = self.env['ai.agent'].create({
            'name': 'Fallback Agent', 'system_prompt': 'x'})
        thread = self.env['ai.debug.thread'].create({
            'session_id': 'fallback-session', 'agent_id': agent.id,
            'user_id': self.env.user.id})
        loop = self.env['ai.debug.loop'].create({
            'thread_id': thread.id, 'model_name': 'test-model',
            'termination_reason': 'success'})
        # Two iterations carrying deltas but NO messages_sent (NULL column).
        it1 = self.env['ai.debug.iteration'].create({
            'loop_id': loop.id, 'sequence': 1,
            'messages_delta': [{'role': 'user', 'content': 'U'}]})
        it2 = self.env['ai.debug.iteration'].create({
            'loop_id': loop.id, 'sequence': 2,
            'messages_delta': [{'role': 'assistant', 'content': 'A'}]})

        # Document the trap: a NULL Json column reads as False, not None.
        self.assertIs(it2.messages_sent, False,
            "NULL jsonb reads back as False -- the reason `is None` fails")

        # debug_expand must reconstruct from the concatenated deltas, NOT return False.
        result = self.env['ai.debug.thread'].debug_expand(
            'iteration', it2.id, 'messages_sent')
        self.assertEqual(result['value'], [
            {'role': 'user', 'content': 'U'},
            {'role': 'assistant', 'content': 'A'},
        ], "falls back to delta reconstruction for a NULL messages_sent row")

    def test_debug_expand_returns_stored_messages_sent_when_present(self):
        agent = self.env['ai.agent'].create({
            'name': 'Stored Agent', 'system_prompt': 'x'})
        thread = self.env['ai.debug.thread'].create({
            'session_id': 'stored-session', 'agent_id': agent.id,
            'user_id': self.env.user.id})
        loop = self.env['ai.debug.loop'].create({
            'thread_id': thread.id, 'model_name': 'test-model',
            'termination_reason': 'success'})
        full = [{'role': 'user', 'content': 'U'}, {'role': 'assistant', 'content': 'A'}]
        it = self.env['ai.debug.iteration'].create({
            'loop_id': loop.id, 'sequence': 1,
            'messages_delta': [{'role': 'assistant', 'content': 'A'}],
            'messages_sent': full})
        result = self.env['ai.debug.thread'].debug_expand(
            'iteration', it.id, 'messages_sent')
        self.assertEqual(result['value'], full,
            "the stored full messages_sent is returned verbatim, not reconstructed from delta")
