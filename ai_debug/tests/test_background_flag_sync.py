# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""The debug thread's ``is_background`` flag tracks the session's CURRENT run
mode across turns -- not just the mode captured at thread creation.

``ai.session.is_background`` is PER-CALL: it is (re)written every time a turn is
dispatched (``_cron_dispatch_child``), so a session first run in background then
continued in foreground flips it to False. The ai_debug instrumentation caches a
copy on ``ai.debug.thread`` so the tree node can render a ``background`` flag --
this suite pins that the copy is reconciled on every later turn (both directions)
and that the per-turn ``AI_DEBUG_NEW_LOOP`` bus payload carries the new mode so a
live tree node re-syncs without a refetch."""

from unittest.mock import patch

from odoo import SUPERUSER_ID
from odoo.api import Environment
from odoo.tests import tagged

from odoo.addons.ai.tests.common import (
    TestAICommon, mock_post_ai_response__flush_bus,
)
from odoo.addons.bus.models.bus_listener_mixin import BusListenerMixin


@tagged('post_install', '-at_install', 'ai_cron_tick', 'ai_debug_bg_sync')
class TestBackgroundFlagSync(TestAICommon):

    def setUp(self):
        super().setUp()
        self.agent_id = self.env.ref('ai.ai_default_agent').id

    def _worker(self):
        cr = self.registry.cursor()
        self.addCleanup(cr.close)
        self.addCleanup(cr.rollback)
        return cr, Environment(cr, SUPERUSER_ID, {})

    def _make_session(self, env):
        agent = env['ai.agent'].browse(self.agent_id)
        return env['ai.session'].create({
            'agent_id': agent.id, 'provider': agent.provider,
            'channel_id': agent._create_ai_chat_channel().id})

    def _queue_prompt(self, env, session, query):
        """Queue a fresh-turn prompt signal so the next tick opens a new loop."""
        env['ai.session.signal'].create({
            'session_id': session.id, 'kind': 'prompt',
            'payload': {'message': [{'type': 'text', 'content': {'data': query}}],
                        'query': query}})

    def _thread_is_background(self, session_id):
        """Read the debug thread's flag on a FRESH connection -- the override
        commits its writes on its own cursor."""
        cr = self.registry.cursor()
        try:
            env = Environment(cr, SUPERUSER_ID, {})
            thread = env['ai.debug.thread'].search(
                [('session_id', '=', str(session_id))], limit=1)
            return thread.is_background
        finally:
            cr.close()

    def _run_turn(self, env, session, query, *, background, bus_capture=None):
        """Drive one complete terminal-text turn with the session's mode set to
        ``background``; optionally collect every ``_bus_send`` payload. Mocks the
        provider's ``get_completions`` (one terminal-text response per tick), like
        the behavioural cron suites."""
        session.is_background = background
        self._queue_prompt(env, session, query)

        provider = session.provider
        response = self.mock_text_response('Done.', provider=provider)
        if provider == 'google':
            api_mock = self.mock_google_api_request([response])
        else:
            api_mock = self.mock_openai_api_request([response])

        real_bus_send = BusListenerMixin._bus_send

        def _capture(self_users, notification_type, message, /, **kw):
            if bus_capture is not None:
                bus_capture.append((notification_type, message))
            return real_bus_send(self_users, notification_type, message, **kw)

        with api_mock, patch.object(BusListenerMixin, '_bus_send', _capture), \
                mock_post_ai_response__flush_bus():
            session._run_session_tick()

    def test_thread_background_flag_clears_after_foreground_continue(self):
        """bg-then-fg: a thread first run in background must DROP the flag once
        the session is continued in the foreground."""
        _cr, env = self._worker()
        session = self._make_session(env)

        self._run_turn(env, session, 'first run (background)', background=True)
        self.assertTrue(
            self._thread_is_background(session.id),
            "thread captures is_background=True from the background first run")

        bus = []
        self._run_turn(env, session, 'continued (foreground)',
                       background=False, bus_capture=bus)
        self.assertFalse(
            self._thread_is_background(session.id),
            "a foreground continue clears the thread's cached background flag")

        # The per-turn NEW_LOOP bus update must carry the new mode so the live
        # tree node re-syncs without a manual refetch.
        new_loop = [m for (t, m) in bus if t == 'AI_DEBUG_NEW_LOOP']
        self.assertTrue(new_loop, "a new loop is announced for the foreground turn")
        self.assertIn('is_background', new_loop[-1],
            "AI_DEBUG_NEW_LOOP payload carries the thread's current run mode")
        self.assertFalse(new_loop[-1]['is_background'],
            "the foreground turn's NEW_LOOP reports is_background=False")

    def test_thread_background_flag_sets_after_background_continue(self):
        """fg-then-bg: the reverse direction -- a foreground thread continued in
        the background must START showing the flag."""
        _cr, env = self._worker()
        session = self._make_session(env)

        self._run_turn(env, session, 'first run (foreground)', background=False)
        self.assertFalse(
            self._thread_is_background(session.id),
            "thread captures is_background=False from the foreground first run")

        bus = []
        self._run_turn(env, session, 'continued (background)',
                       background=True, bus_capture=bus)
        self.assertTrue(
            self._thread_is_background(session.id),
            "a background continue sets the thread's cached background flag")
        new_loop = [m for (t, m) in bus if t == 'AI_DEBUG_NEW_LOOP']
        self.assertTrue(new_loop, "a new loop is announced for the background turn")
        self.assertTrue(new_loop[-1].get('is_background'),
            "the background turn's NEW_LOOP reports is_background=True")
