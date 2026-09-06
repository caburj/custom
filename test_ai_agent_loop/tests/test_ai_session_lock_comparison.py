# Part of Odoo. See LICENSE file for full copyright and licensing details.

"""Force real HTTP contention without requiring a particular locking primitive."""

import copy
import importlib
import json
import logging
import time
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
        confirmation = scenario not in ('siblings', 'duplicate_callback')
        duplicate_resume = scenario == 'duplicate_resume'
        automatic = scenario.startswith('automatic_')
        child_count = 0 if duplicate_resume else (2 if scenario == 'siblings' else 1)
        with self._physical_tree(child_count=child_count, confirmation=confirmation) as fixture:
            source_id = fixture['parent_id']
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                for child_id, child_uuid in fixture['children']:
                    env['ai.session'].sudo().browse(child_id)._apply_submission_acknowledgement(child_uuid)
            waiting = self._snapshot(source_id)
            paused = Event()
            release = Event()
            request_pids = {}
            attempts = {'first': 0, 'second': 0}
            transitions = []
            invocations = []
            submissions = []
            blocking = []
            first_snapshot = {}
            session_model = self.registry['ai.session']
            original_merge = session_model._merge_child_result
            original_resume = session_model._resume_pending_interaction
            original_tool = self.registry['ir.actions.server']._ai_tool_run
            router = importlib.import_module('odoo.http.router')
            original_serve = router.serve_ir_http

            def label():
                return http.request.httprequest.headers.get('X-AI-Lock-Comparison')

            def observe_http(request, *args, **kwargs):
                name = request.httprequest.headers.get('X-AI-Lock-Comparison')
                if name in attempts:
                    attempts[name] += 1
                    request.env.cr.execute('SELECT pg_backend_pid()')
                    request_pids[name] = request.env.cr.fetchone()[0]
                return original_serve(request, *args, **kwargs)

            def enter_transition(session, kind):
                if session.id != source_id:
                    return
                # Materialize both the ORM values and the transaction snapshot.
                snapshot = {
                    'pending': copy.deepcopy(session.pending_tool_call),
                    'request_uuid': session.request_uuid,
                    'resume_token': session.resume_token,
                }
                session.env.cr.execute('SELECT pg_backend_pid(), txid_current(), current_setting(%s)', ['transaction_isolation'])
                pid, xid, isolation = session.env.cr.fetchone()
                self.assertEqual(isolation, 'repeatable read')
                name = label()
                transitions.append({'request': name, 'kind': kind, 'pid': pid, 'xid': xid})
                if name == 'first' and not paused.is_set():
                    first_snapshot.update(snapshot)
                    paused.set()
                    self.assertTrue(release.wait(timeout=45), 'Coordinator did not release the first transition')

            def merge(session, child):
                enter_transition(session, 'merge')
                return original_merge(session, child)

            def resume(session, *args, **kwargs):
                enter_transition(session, 'resume')
                return original_resume(session, *args, **kwargs)

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

            if scenario == 'siblings':
                first_call, second_call = lambda: callback('first'), lambda: callback('second', 1)
            elif scenario == 'duplicate_callback':
                first_call, second_call = lambda: callback('first'), lambda: callback('second')
            elif duplicate_resume:
                first_call, second_call = lambda: confirm('first'), lambda: confirm('second')
            elif scenario.endswith('merge_first'):
                first_call, second_call = lambda: callback('first'), lambda: confirm('second')
            else:
                first_call, second_call = lambda: confirm('first'), lambda: callback('second')

            try:
                with (
                    patch.object(router, 'serve_ir_http', observe_http),
                    patch.object(session_model, '_merge_child_result', merge),
                    patch.object(session_model, '_resume_pending_interaction', resume),
                    patch.object(self.registry['ir.actions.server'], '_ai_tool_run', tool),
                    patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', side_effect=submit),
                    self.allow_requests(all_requests=True),
                    ThreadPoolExecutor(max_workers=2) as pool,
                ):
                    first_future = pool.submit(first_call)
                    try:
                        self.assertTrue(paused.wait(timeout=15), 'First request never reached the shared transition')
                        second_future = pool.submit(second_call)
                        deadline = time.monotonic() + 20
                        while time.monotonic() < deadline:
                            second_pid = request_pids.get('second')
                            if second_pid:
                                with self.registry._db.cursor() as cr:
                                    cr.execute('''
                                        SELECT locktype, mode FROM pg_locks
                                        WHERE pid = %s AND NOT granted
                                          AND %s = ANY(pg_blocking_pids(%s))
                                    ''', [second_pid, request_pids['first'], second_pid])
                                    blocking = cr.fetchall()
                            if blocking or second_future.done():
                                break
                            time.sleep(0.01)
                        self.assertTrue(blocking, 'The overlapping session changes did not wait for their owner')
                        self.assertEqual(first_snapshot['pending'], waiting['pending'])
                    finally:
                        release.set()
                    responses = [first_future.result(timeout=90), second_future.result(timeout=90)]
                    for response in responses:
                        self.assertEqual(response.status_code, 200, response.text)
                        if isinstance(response.json(), dict):
                            self.assertNotIn('error', response.json())

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
                with self.registry._db.cursor() as cr:
                    env = api.Environment(cr, self.env.uid, {})
                    contacts = env['res.partner'].search_count([('name', '=', fixture['contact_name'])])
                self.assertEqual(contacts, int(confirmation))
                self.assertEqual(len(invocations), int(confirmation),
                                 'Confirmed tool execution repeated after waiting for the source row')
                # Count the exact selected-choice text, rather than assuming a label.
                if confirmation:
                    value = 'auto_confirm' if automatic else 'confirm_once'
                    choice = next(c for c in waiting['pending']['user_input_request']['choices'] if c['value'] == value)
                    with self.registry._db.cursor() as cr:
                        env = api.Environment(cr, self.env.uid, {})
                        receipts = env['mail.message'].search_count([
                            ('model', '=', 'discuss.channel'), ('res_id', '=', fixture['channel_id']),
                            ('body', 'ilike', choice['label']),
                        ])
                    self.assertEqual(receipts, 1)
                self.assertEqual(len({request_pids['first'], request_pids['second']}), 2)
            finally:
                _logger.info('LOCK_COMPARISON %s', json.dumps({
                    'scenario': scenario, 'http_attempts': attempts,
                    'transition_entries': transitions, 'second_wait': blocking,
                    'confirmed_tool_invocations': len(invocations),
                    'tool_invocation_requests': [i['request'] for i in invocations],
                    'transport_attempts': len(submissions), 'logical_submissions': len(set(submissions)),
                }, sort_keys=True))

    def test_simultaneous_sibling_callbacks(self):
        self._race('siblings')

    def test_duplicate_callback(self):
        self._race('duplicate_callback')

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
