# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Atomic production endpoints through real HTTP requests and database cursors."""

import importlib
import json
import logging
from contextlib import contextmanager
from unittest.mock import patch

from odoo import api, http
from odoo.exceptions import ConcurrencyError
from odoo.sql_db import Cursor
from odoo.tests import HttpCase, tagged

from .common import apply_iap_result
from .test_ai_session_subagents import tool_call
from .test_ai_session_subagents_http import TestAISessionSubagentsHttp
from odoo.addons.ai.controllers.thread import AIThreadController

_logger = logging.getLogger(__name__)


@contextmanager
def observe_transactions(*, before_commit=None, on_attempt=None):
    """Observe production transactions and inject failures without replacing work."""
    router = importlib.import_module('odoo.http.router')
    original_serve = router.serve_ir_http
    original_transaction = AIThreadController._lock_and_commit
    original_commit = Cursor.commit
    observations = []

    def serve(request, *args, **kwargs):
        if on_attempt and request.httprequest.path in (
            '/ai/completion_result_ready', '/ai/resume_pending_interaction',
        ):
            on_attempt(request)
        return original_serve(request, *args, **kwargs)

    def commit(cr):
        observation = getattr(http.request, '_ai_test_transaction', None) if http.request else None
        if observation is not None and cr is http.request.env.cr:
            observation['commits'] += 1
        result = original_commit(cr)
        if observation is not None and cr is http.request.env.cr:
            observation['committed'] = True
        return result

    @contextmanager
    def transaction(controller, session, **actor_params):
        request = http.request
        cr = controller.env.cr
        cr.execute('SELECT txid_current()')
        observation = {'xid': cr.fetchone()[0], 'committed': False, 'commits': 0}
        observations.append(observation)
        request._ai_test_transaction = observation
        try:
            with original_transaction(controller, session, **actor_params) as session:
                yield session
                if before_commit:
                    before_commit(request, observation)
        finally:
            request._ai_test_transaction = None
            assert observation['commits'] <= 1, 'Intermediate business commit'

    with (
        patch.object(router, 'serve_ir_http', serve),
        patch.object(AIThreadController, '_lock_and_commit', transaction),
        patch.object(Cursor, 'commit', commit),
    ):
        yield observations


@tagged('post_install', '-at_install')
class TestAISessionAtomicEndpoint(HttpCase):
    _physical_tree = TestAISessionSubagentsHttp._physical_tree
    _results = TestAISessionSubagentsHttp._results
    _callback = TestAISessionSubagentsHttp._callback
    _contact_call = TestAISessionSubagentsHttp._contact_call

    def _snapshot(self, session_id):
        snapshot = TestAISessionSubagentsHttp._snapshot(self, session_id)
        with self.registry._db.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            snapshot['request_result'] = env['ai.session'].sudo().browse(session_id).request_result
        return snapshot


    def test_nested_callback_rolls_back_every_parent_edge(self):
        with self._physical_tree() as fixture:
            parent_id, parent_uuid = fixture['children'][0]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                parent = env['ai.session'].sudo().browse(parent_id)
                parent.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                apply_iap_result(parent, parent_uuid, {
                    'kind': 'success', 'message': {'role': 'assistant', 'content': [
                        tool_call('start_session', 'grandchild', agent_id=fixture['agent_id'], message='Nested work'),
                        self._contact_call(env, 'decline-parent', fixture['contact_name']),
                    ]},
                })
                child = env['ai.session'].sudo().search([('parent_session_id', '=', parent_id)])
                child_id, child_uuid = child.id, child.request_uuid
                parent._resume_pending_interaction(parent.resume_token, {'kind': 'confirmation', 'value': 'decline'})
            ids = [fixture['parent_id'], parent_id, child_id]
            before = {sid: self._snapshot(sid) for sid in ids}
            merges = []
            merge = self.registry['ai.session']._merge_child_result

            def observe_merge(parent, child):
                parent.env.cr.execute('SELECT txid_current()')
                merges.append((parent.id, parent.env.cr.fetchone()[0]))
                return merge(parent, child)

            attempts = []

            def fail_before_commit(request, observation):
                # Even the deepest callback and both parent merges are invisible.
                self.assertEqual({sid: self._snapshot(sid) for sid in ids}, before)
                self.assertEqual(transport.call_count, 0)
                attempts.append(observation['xid'])
                if len(attempts) == 1:
                    message = 'Injected failure: retry the entire nested delivery'
                    raise ConcurrencyError(message)

            with (
                observe_transactions(before_commit=fail_before_commit) as observations,
                patch.object(self.registry['ai.session'], '_merge_child_result', observe_merge),
                patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
            ):
                response = self._callback(child_uuid, 'Nested answer')
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(attempts), 2)
            self.assertNotEqual(*attempts)
            self.assertEqual(merges, [(parent_id, attempts[0]), (fixture['parent_id'], attempts[0]),
                                      (parent_id, attempts[1]), (fixture['parent_id'], attempts[1])])
            self.assertEqual([o['committed'] for o in observations], [False, True])
            self.assertEqual(self._snapshot(child_id)['loop_state'], 'ready')
            self.assertEqual(self._snapshot(parent_id)['loop_state'], 'ready')
            self.assertEqual(self._snapshot(fixture['parent_id'])['request_phase'], 'submitted')
            transport.assert_called_once()
            _logger.info('ATOMIC_ENDPOINT nested %s', json.dumps(observations))

    def test_resume_rollback_preserves_work_before_confirmation(self):
        self.authenticate('admin', 'admin')
        with self._physical_tree(child_count=0, prepare_root=False) as fixture:
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                root = env['ai.session'].sudo().browse(fixture['parent_id'])
                root.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                root._prepare_model_request([{'type': 'text', 'text': 'Create A then B'}])
                apply_iap_result(root, root.request_uuid, {
                    'kind': 'success', 'message': {'role': 'assistant', 'content': [
                        self._contact_call(env, 'prior', fixture['contact_name'] + ' A'),
                        self._contact_call(env, 'confirm', fixture['contact_name']),
                    ]},
                })
                root._resume_pending_interaction(root.resume_token,
                                                 {'kind': 'confirmation', 'value': 'confirm_once'})
                self.assertEqual(root.loop_state, 'waiting_confirmation')
                prior = env['res.partner'].search([('name', '=', fixture['contact_name'] + ' A')])
                self.assertEqual(len(prior), 1)
                prior_id = prior.id
            before = self._snapshot(fixture['parent_id'])
            attempts = []
            invocations = []
            original_tool = self.registry['ir.actions.server']._ai_tool_run

            def tool(action, record, arguments, tools_context):
                invocations.append(arguments)
                return original_tool(action, record, arguments, tools_context)

            def fail_before_commit(request, observation):
                self.assertEqual(self._snapshot(fixture['parent_id']), before)
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    self.assertTrue(env['res.partner'].browse(prior_id).exists())
                    self.assertFalse(env['res.partner'].search_count([('name', '=', fixture['contact_name'])]))
                transport.assert_not_called()
                attempts.append(observation)
                if len(attempts) == 1:
                    message = 'Injected failure: rollback after confirmed tool'
                    raise ConcurrencyError(message)

            with (
                observe_transactions(before_commit=fail_before_commit) as observations,
                patch.object(self.registry['ir.actions.server'], '_ai_tool_run', tool),
                patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
            ):
                response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                    'channel_id': fixture['channel_id'], 'session_id': fixture['parent_id'],
                    'resume_token': before['resume_token'],
                    'response': {'kind': 'confirmation', 'value': 'confirm_once'},
                }))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn('error', response.json())
            self.assertEqual(len(invocations), 2)
            self.assertEqual([o['committed'] for o in observations], [False, True])
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertEqual(env['res.partner'].search_count([('name', '=', fixture['contact_name'])]), 1)
                self.assertTrue(env['res.partner'].browse(prior_id).exists())
            transport.assert_called_once()
            _logger.info('ATOMIC_ENDPOINT resume_rollback %s', json.dumps(observations))
