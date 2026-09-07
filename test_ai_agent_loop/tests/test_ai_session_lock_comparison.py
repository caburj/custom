# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Force stale first attempts and let native HTTP retry preserve committed work."""

import copy
import importlib
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

import requests

from odoo import api, http
from odoo.tests import HttpCase, tagged

from .test_ai_session_subagents_http import TestAISessionSubagentsHttp

_logger = logging.getLogger(__name__)


@tagged('post_install', '-at_install')
class TestAISessionLockComparison(HttpCase):
    _physical_tree = TestAISessionSubagentsHttp._physical_tree
    _snapshot = TestAISessionSubagentsHttp._snapshot
    _results = TestAISessionSubagentsHttp._results


    def _race(self, scenario):
        self.authenticate('admin', 'admin')
        duplicate_start = scenario == 'duplicate_start'
        confirmation = scenario not in ('siblings', 'duplicate_callback', 'duplicate_start')
        duplicate_resume = scenario == 'duplicate_resume'
        automatic = scenario.startswith('automatic_')
        child_count = 0 if duplicate_resume or duplicate_start else (2 if scenario == 'siblings' else 1)
        with self._physical_tree(
            child_count=child_count, confirmation=confirmation, prepare_root=not duplicate_start,
        ) as fixture:
            source_id = fixture['parent_id']
            target_id = fixture['children'][0][0] if scenario == 'duplicate_callback' else source_id
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                for child_id, child_uuid in fixture['children']:
                    env['ai.session'].sudo().browse(child_id).write({'request_phase': 'submitted'})
                if duplicate_start:
                    message_id = env['discuss.channel'].browse(fixture['channel_id']).message_post(
                        body='Start this exchange once', message_type='comment',
                    ).id
            waiting = self._snapshot(target_id)
            arrived = {name: Event() for name in ('first', 'second')}
            release = {name: Event() for name in arrived}
            snapshots = {}
            attempts = {'first': 0, 'second': 0}
            transitions = []
            invocations = []
            submissions = []
            session_model = self.registry['ai.session']
            original_merge = session_model._merge_child_result
            original_store = session_model._store_request_result
            original_prepare = session_model._prepare_agent_request
            original_post = self.registry['discuss.channel'].message_post
            original_tool = self.registry['ir.actions.server']._ai_tool_run
            router = importlib.import_module('odoo.http.router')
            original_serve = router.serve_ir_http

            def label():
                return http.request.httprequest.headers.get('X-AI-Lock-Comparison')

            def observe_http(request, *args, **kwargs):
                name = request.httprequest.headers.get('X-AI-Lock-Comparison')
                if name in attempts:
                    attempts[name] += 1
                return original_serve(request, *args, **kwargs)

            def enter_transition(session, kind):
                name = label()
                if session.id != target_id or name not in attempts or attempts[name] != 1:
                    return
                # Both first attempts must read the same state before either writes it.
                snapshots[name] = {
                    'pending': copy.deepcopy(session.pending_tool_call),
                    'request_uuid': session.request_uuid,
                    'resume_token': session.resume_token,
                    'loop_state': session.loop_state,
                    'request_result': copy.deepcopy(session.request_result),
                }
                session.env.cr.execute('SELECT pg_backend_pid(), txid_current(), current_setting(%s)', ['transaction_isolation'])
                pid, xid, isolation = session.env.cr.fetchone()
                self.assertEqual(isolation, 'repeatable read')
                transitions.append({'request': name, 'kind': kind, 'pid': pid, 'xid': xid})
                arrived[name].set()
                self.assertTrue(release[name].wait(timeout=45), 'Coordinator did not release the stale transition')

            def merge(session, child, result):
                if scenario != 'duplicate_callback':
                    enter_transition(session, 'merge')
                return original_merge(session, child, result)

            def store(session, *args, **kwargs):
                if scenario == 'duplicate_callback':
                    enter_transition(session, 'store')
                return original_store(session, *args, **kwargs)

            def prepare(session, *args, **kwargs):
                if duplicate_start:
                    enter_transition(session, 'start')
                return original_prepare(session, *args, **kwargs)

            def post(channel, *args, **kwargs):
                if confirmation and channel.id == fixture['channel_id'] and kwargs.get('body') == choice['label']:
                    # Both resumes have validated the token before posting a receipt.
                    # Test-mode channel bookkeeping can conflict here before the tool.
                    enter_transition(channel.env['ai.session'].sudo().browse(source_id), 'receipt')
                return original_post(channel, *args, **kwargs)

            def tool(tool_record, record, arguments, tools_context):
                if tools_context.get('session_id') == source_id and tools_context.get('tool_request_confirmed'):
                    invocations.append({'request': label(), 'arguments': copy.deepcopy(arguments)})
                return original_tool(tool_record, record, arguments, tools_context)

            def submit(_connection, _route, payload, **_kwargs):
                submissions.append(payload['request_uuid'])
                return

            def callback(name, child_index=0, *, parent=False):
                request_uuid = fixture['parent_uuid'] if parent else fixture['children'][child_index][1]
                return requests.post(
                    f'{self.base_url()}/ai/completion_result_ready',
                    headers={'X-AI-Lock-Comparison': name},
                    json={'request_uuid': request_uuid, 'llm_error': False,
                          'llm_result': {'status': 'success', 'result': {'role': 'assistant', 'content': [
                              {'type': 'text', 'text': f'Completed child {child_index}'},
                          ]}}}, timeout=90,
                )

            def confirm(name):
                return requests.post(
                    f'{self.base_url()}/ai/resume_pending_interaction',
                    headers={'X-AI-Lock-Comparison': name}, cookies=self.opener.cookies,
                    json=self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'session_id': source_id,
                        'resume_token': waiting['resume_token'],
                        'response': {'kind': 'confirmation', 'value': 'auto_confirm' if automatic else 'confirm_once'},
                    }), timeout=90,
                )

            def start(name):
                return requests.post(
                    f'{self.base_url()}/ai/start_session_advance',
                    headers={'X-AI-Lock-Comparison': name}, cookies=self.opener.cookies,
                    json=self.build_rpc_payload({
                        'channel_id': fixture['channel_id'], 'mail_message_id': message_id,
                    }), timeout=90,
                )

            if confirmation:
                value = 'auto_confirm' if automatic else 'confirm_once'
                choice = next(c for c in waiting['pending']['user_input_request']['choices'] if c['value'] == value)

            if scenario == 'siblings':
                first_call, second_call = lambda: callback('first'), lambda: callback('second', 1)
            elif scenario == 'duplicate_callback':
                first_call, second_call = lambda: callback('first'), lambda: callback('second')
            elif duplicate_resume:
                first_call, second_call = lambda: confirm('first'), lambda: confirm('second')
            elif duplicate_start:
                first_call, second_call = lambda: start('first'), lambda: start('second')
            elif scenario.endswith('merge_first'):
                first_call, second_call = lambda: callback('first'), lambda: confirm('second')
            else:
                first_call, second_call = lambda: confirm('first'), lambda: callback('second')

            try:
                with (
                    patch.object(router, 'serve_ir_http', observe_http),
                    patch.object(session_model, '_merge_child_result', merge),
                    patch.object(session_model, '_store_request_result', store),
                    patch.object(session_model, '_prepare_agent_request', prepare),
                    patch.object(self.registry['discuss.channel'], 'message_post', post),
                    patch.object(self.registry['ir.actions.server'], '_ai_tool_run', tool),
                    patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', side_effect=submit),
                    self.allow_requests(all_requests=True),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    first_future = pool.submit(first_call)
                    try:
                        self.assertTrue(arrived['first'].wait(timeout=15), 'First request never reached the stale read')
                        second_future = pool.submit(second_call)
                        self.assertTrue(arrived['second'].wait(timeout=15), 'Second request could not reach the stale read')
                        self.assertEqual(snapshots['first'], snapshots['second'])
                        self.assertEqual(snapshots['first']['pending'], waiting['pending'])
                        self.assertEqual(len({entry['pid'] for entry in transitions}), 2)
                        self.assertEqual(len({entry['xid'] for entry in transitions}), 2)
                        # Commit the first request while the second retains its old snapshot.
                        release['first'].set()
                        first_response = first_future.result(timeout=30)
                    finally:
                        for event in release.values():
                            event.set()
                    responses = [first_response, second_future.result(timeout=90)]
                    for index, response in enumerate(responses):
                        self.assertEqual(response.status_code, 200, response.text)
                        if duplicate_start and index == 1:
                            error = response.json()['error']['data']
                            self.assertEqual(error['name'], 'odoo.exceptions.UserError')
                            self.assertIn('already responding', error['message'])
                        elif isinstance(response.json(), dict):
                            self.assertNotIn('error', response.json())
                    self.assertEqual(attempts['first'], 1)
                    self.assertGreater(attempts['second'], 1, 'The stale transaction was not retried by HTTP')

                final = self._snapshot(source_id)
                results = self._results(final)
                expected_calls = [f'child-{index}' for index in range(child_count)] + (['confirm'] if confirmation else [])
                self.assertEqual([result['tool_call_id'] for result in results], expected_calls)
                self.assertTrue(all(result['success'] for result in results))
                for index in range(child_count):
                    child_result = json.loads(results[index]['result'][0]['text'])
                    self.assertEqual(child_result['session_id'], fixture['children'][index][0])
                    self.assertIn(f'Completed child {index}', child_result['message'])
                self.assertEqual(final['loop_state'], 'waiting_model')
                self.assertEqual(final['request_phase'], 'submitted')
                self.assertFalse(final['pending'])
                self.assertFalse(final['resume_token'])
                self.assertEqual(set(submissions), {final['request_uuid']})
                if duplicate_start:
                    self.assertEqual(len(final['events']), 1, 'A rolled-back start left duplicate history')
                    self.assertEqual(len(submissions), 1)
                    self.assertEqual(responses[0].json()['result']['request_uuid'], final['request_uuid'])
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    contacts = env['res.partner'].search_count([('name', '=', fixture['contact_name'])])
                self.assertEqual(contacts, int(confirmation))
                self.assertGreaterEqual(len(invocations), int(confirmation))
                # Count the exact selected-choice text, rather than assuming a label.
                if confirmation:
                    with self.registry._db.cursor() as cr:
                        env = api.Environment(cr, self.env.uid, {})
                        receipts = env['mail.message'].search_count([
                            ('model', '=', 'discuss.channel'), ('res_id', '=', fixture['channel_id']),
                            ('body', 'ilike', choice['label']),
                        ])
                    self.assertEqual(receipts, 1)
            finally:
                _logger.info('LOCK_COMPARISON %s', json.dumps({
                    'scenario': scenario, 'http_attempts': attempts,
                    'transition_entries': transitions,
                    'confirmed_tool_invocations': len(invocations),
                    'tool_invocation_requests': [i['request'] for i in invocations],
                    'transport_attempts': len(submissions), 'logical_submissions': len(set(submissions)),
                }, sort_keys=True))

    def test_simultaneous_sibling_callbacks(self):
        self._race('siblings')

    def test_duplicate_callback(self):
        self._race('duplicate_callback')

    def test_duplicate_start(self):
        self._race('duplicate_start')

    def test_merge_then_manual_resume(self):
        self._race('manual_merge_first')

    def test_manual_resume_then_merge(self):
        self._race('manual_resume_first')

    def test_duplicate_resume(self):
        self._race('duplicate_resume')

    def test_merge_then_automatic_resume(self):
        self._race('automatic_merge_first')

    def test_automatic_resume_then_merge(self):
        self._race('automatic_resume_first')
