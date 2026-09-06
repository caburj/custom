# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Narrow row ownership and approval-policy races through physical HTTP calls."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import requests

from odoo import api, http
from odoo.tests import HttpCase, tagged

from .common import apply_iap_result
from .test_ai_session_atomic_endpoint import (
    TestAISessionAtomicEndpoint,
    observe_transactions,
)
from .test_ai_session_subagents import tool_call
from .test_ai_session_subagents_http import TestAISessionSubagentsHttp

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestAISessionAtomicScope(HttpCase):
    _physical_tree = TestAISessionSubagentsHttp._physical_tree
    _snapshot = TestAISessionAtomicEndpoint._snapshot
    _contact_call = TestAISessionSubagentsHttp._contact_call
    _results = TestAISessionSubagentsHttp._results

    def _post(self, label, path, data):
        return requests.post(f'{self.base_url()}{path}', json=data,
                             headers={'X-AI-Atomic-Scope': label}, cookies=self.opener.cookies, timeout=90)

    def _callback(self, label, request_uuid, content):
        return self._post(label, '/ai/completion_result_ready', {
            'request_uuid': request_uuid, 'llm_error': False,
            'llm_result': {'status': 'success', 'result': {'role': 'assistant', 'content': content}},
        })

    def _concurrent(self, first, second, *, must_block):
        paused, release = Event(), Event()
        pids, attempts, waits = {}, {}, []
        submissions = []
        invocations = []
        original_tool = self.registry['ir.actions.server']._ai_tool_run

        def on_attempt(request):
            label = request.httprequest.headers.get('X-AI-Atomic-Scope')
            attempts[label] = attempts.get(label, 0) + 1
            request.env.cr.execute('SELECT pg_backend_pid()')
            pids[label] = request.env.cr.fetchone()[0]

        def before_commit(request, observation):
            if request.httprequest.headers.get('X-AI-Atomic-Scope') == 'first' and not paused.is_set():
                paused.set()
                self.assertTrue(release.wait(45), 'Coordinator did not release the first transaction')

        def transport(_connection, _route, payload, **kwargs):
            with self.registry._db.cursor() as cr:
                cr.execute('SELECT request_phase FROM ai_session WHERE request_uuid = %s', [payload['request_uuid']])
                self.assertIn(cr.fetchone()[0], ('prepared', 'submitted'), 'Transport preceded durable preparation')
            submissions.append(payload['request_uuid'])

        def tool(action, record, arguments, tools_context):
            if tools_context.get('tool_request_confirmed'):
                invocations.append({'session_id': tools_context.get('session_id'),
                                    'request': http.request.httprequest.headers.get('X-AI-Atomic-Scope')})
            return original_tool(action, record, arguments, tools_context)

        with (
            observe_transactions(on_attempt=on_attempt, before_commit=before_commit) as observations,
            patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', side_effect=transport),
            patch.object(self.registry['ir.actions.server'], '_ai_tool_run', tool),
            self.allow_requests(all_requests=True),
            ThreadPoolExecutor(max_workers=2) as pool,
        ):
            first_future = pool.submit(first)
            try:
                self.assertTrue(paused.wait(15), 'First endpoint never reached its final business commit')
                second_future = pool.submit(second)
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if 'second' in pids:
                        with self.registry._db.cursor() as cr:
                            cr.execute('SELECT pg_blocking_pids(%s)', [pids['second']])
                            waits = cr.fetchone()[0]
                    if pids.get('first') in waits or second_future.done():
                        break
                    time.sleep(0.01)
                if must_block:
                    self.assertIn(pids['first'], waits, 'Expected a physical row-lock wait')
                else:
                    self.assertTrue(second_future.done(), 'An unrelated branch should finish before release')
            finally:
                release.set()
            for future in (first_future, second_future):
                response = future.result(90)
                self.assertEqual(response.status_code, 200, response.text)
                if isinstance(response.json(), dict):
                    self.assertNotIn('error', response.json())
        result = {'attempts': attempts, 'blocked': bool(waits),
                  'transactions': observations, 'submissions': submissions, 'tools': invocations}
        _logger.info('ATOMIC_SCOPE %s', json.dumps(result, sort_keys=True))
        return result

    def test_allow_all_accepts_late_confirmation_and_fresh_work_obeys_policy(self):
        self.authenticate('admin', 'admin')
        for first_kind in ('waiting', 'enabling'):
            with self.subTest(first=first_kind), self._physical_tree(confirmation=True) as fixture:
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                    branch_id, branch_uuid = fixture['children'][0]
                    branch = env['ai.session'].sudo().browse(branch_id)
                    apply_iap_result(branch, branch_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            tool_call('start_session', 'deep', agent_id=fixture['agent_id'], message='Deep task'),
                        ]},
                    })
                    child = env['ai.session'].sudo().search([('parent_session_id', '=', branch_id)])
                    child_id, child_uuid = child.id, child.request_uuid
                    child.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                    child._apply_submission_acknowledgement(child_uuid)
                    contact_call = self._contact_call(env, 'deep-confirm', fixture['contact_name'] + ' B')
                    later_call = self._contact_call(env, 'fresh-policy', fixture['contact_name'] + ' C')
                waiting = self._snapshot(fixture['parent_id'])

                def enable(label):
                    return self._post(label, '/ai/resume_pending_interaction', self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'session_id': fixture['parent_id'],
                        'resume_token': waiting['resume_token'],
                        'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                    }))

                def child_ready(label):
                    return self._callback(label, child_uuid, [contact_call])

                first, second = (child_ready, enable) if first_kind == 'waiting' else (enable, child_ready)
                self._concurrent(lambda: first('first'), lambda: second('second'), must_block=False)
                late = self._snapshot(child_id)
                self.assertEqual(late['loop_state'], 'waiting_confirmation')
                self.assertTrue(late['resume_token'])
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    self.assertTrue(env['ai.session'].sudo().browse(fixture['parent_id']).auto_confirm)
                    self.assertEqual(env['res.partner'].search_count([('name', '=', fixture['contact_name'])]), 1)
                    self.assertFalse(env['res.partner'].search_count([('name', '=', fixture['contact_name'] + ' B')]))
                with (
                    patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None),
                    self.allow_requests(all_requests=True),
                ):
                    answer = self._post('answer', '/ai/resume_pending_interaction', self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'session_id': child_id,
                        'resume_token': late['resume_token'],
                        'response': {'kind': 'confirmation', 'value': 'confirm_once'},
                    }))
                    self.assertEqual(answer.status_code, 200, answer.text)
                    self.assertNotIn('error', answer.json())
                    current = self._snapshot(child_id)
                    response = self._callback('fresh', current['request_uuid'], [later_call])
                    self.assertEqual(response.status_code, 200, response.text)
                current = self._snapshot(child_id)
                self.assertEqual(current['loop_state'], 'waiting_model')
                self.assertEqual(current['request_phase'], 'submitted')
                self.assertFalse(current['resume_token'])
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    for suffix in (' B', ' C'):
                        self.assertEqual(env['res.partner'].search_count([
                            ('name', '=', fixture['contact_name'] + suffix),
                        ]), 1)

    def test_declined_parents_propagate_concurrently_without_family_lock(self):
        with self._physical_tree(child_count=2) as fixture:
            leaves = []
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                for index, (parent_id, parent_uuid) in enumerate(fixture['children']):
                    parent = env['ai.session'].sudo().browse(parent_id)
                    parent.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                    apply_iap_result(parent, parent_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            tool_call('start_session', 'leaf', agent_id=fixture['agent_id'], message='Leaf task'),
                            self._contact_call(env, 'decline', fixture['contact_name'] + (' A' if index == 0 else ' B')),
                        ]},
                    })
                    leaf = env['ai.session'].sudo().search([('parent_session_id', '=', parent_id)])
                    leaves.append((leaf.id, leaf.request_uuid))
                    leaf._apply_submission_acknowledgement(leaf.request_uuid)
                    parent._resume_pending_interaction(parent.resume_token, {'kind': 'confirmation', 'value': 'decline'})
                    self.assertEqual(parent.loop_state, 'waiting_child')
            result = self._concurrent(
                lambda: self._callback('first', leaves[0][1], [{'type': 'text', 'text': 'Leaf A done'}]),
                lambda: self._callback('second', leaves[1][1], [{'type': 'text', 'text': 'Leaf B done'}]),
                must_block=True,
            )
            root = self._snapshot(fixture['parent_id'])
            self.assertEqual(root['request_phase'], 'submitted')
            self.assertEqual([json.loads(r['result'][0]['text'])['status'] for r in self._results(root)], ['declined', 'declined'])
            self.assertEqual(result['submissions'], [root['request_uuid']])
            self.assertEqual(result['tools'], [])
            for index, (parent_id, _) in enumerate(fixture['children']):
                parent = self._snapshot(parent_id)
                self.assertEqual(parent['loop_state'], 'ready')
                self.assertEqual(parent['exchange_result']['status'], 'declined')
                self.assertEqual(self._snapshot(leaves[index][0])['loop_state'], 'ready')
            self.assertGreater(result['attempts']['second'], 1)

    def _prepare_deep_branches(self, fixture, *, waiting=False):
        leaves = []
        with self.registry._db.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            for index, (branch_id, branch_uuid) in enumerate(fixture['children']):
                branch = env['ai.session'].sudo().browse(branch_id)
                apply_iap_result(branch, branch_uuid, {
                    'kind': 'success', 'message': {'role': 'assistant', 'content': [
                        tool_call('start_session', 'leaf', agent_id=fixture['agent_id'], message='Independent leaf'),
                    ]},
                })
                leaf = env['ai.session'].sudo().search([('parent_session_id', '=', branch_id)])
                leaf.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                leaf._apply_submission_acknowledgement(leaf.request_uuid)
                call = self._contact_call(env, 'confirm', fixture['contact_name'] + (' A' if index == 0 else ' B'))
                if waiting:
                    apply_iap_result(leaf, leaf.request_uuid, {'kind': 'success', 'message': {'role': 'assistant', 'content': [call]}})
                    self.assertEqual(leaf.loop_state, 'waiting_confirmation')
                leaves.append({'id': leaf.id, 'uuid': leaf.request_uuid, 'token': leaf.resume_token,
                               'call': call, 'parent_id': branch_id})
        return leaves

    def test_independent_branches_progress_without_serializing_business(self):
        with self._physical_tree(child_count=2) as fixture:
            leaves = self._prepare_deep_branches(fixture)
            result = self._concurrent(
                lambda: self._callback('first', leaves[0]['uuid'], [leaves[0]['call']]),
                lambda: self._callback('second', leaves[1]['uuid'], [leaves[1]['call']]),
                must_block=False,
            )
            self.assertEqual(result['attempts'], {'first': 1, 'second': 1})
            self.assertEqual(result['tools'], [])
            self.assertEqual(result['submissions'], [])
            for leaf in leaves:
                self.assertEqual(self._snapshot(leaf['id'])['loop_state'], 'waiting_confirmation')

    def test_two_descendants_enable_allow_all_together(self):
        self.authenticate('admin', 'admin')
        with self._physical_tree(child_count=2) as fixture:
            leaves = self._prepare_deep_branches(fixture, waiting=True)

            def enable(label, leaf):
                return self._post(label, '/ai/resume_pending_interaction', self.build_rpc_payload({
                    'channel_id': fixture['channel_id'], 'session_id': leaf['id'],
                    'resume_token': leaf['token'],
                    'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                }))

            result = self._concurrent(lambda: enable('first', leaves[0]), lambda: enable('second', leaves[1]),
                                      must_block=True)
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertTrue(env['ai.session'].sudo().browse(fixture['parent_id']).auto_confirm)
                for suffix in (' A', ' B'):
                    self.assertEqual(env['res.partner'].search_count([('name', '=', fixture['contact_name'] + suffix)]), 1)
            for leaf in leaves:
                snapshot = self._snapshot(leaf['id'])
                self.assertEqual(snapshot['request_phase'], 'submitted')
                self.assertFalse(snapshot['resume_token'])
                self.assertEqual(sum(t['session_id'] == leaf['id'] for t in result['tools']), 1)
            self.assertEqual(len(set(result['submissions'])), 2)
