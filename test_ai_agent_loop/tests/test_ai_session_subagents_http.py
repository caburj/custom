# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, nullcontext
from threading import Barrier, Event
from unittest.mock import patch

import requests

from odoo import Command, api
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

from .common import apply_iap_result
from .test_ai_session_subagents import tool_call
from odoo.addons.ai.controllers.thread import AIThreadController


@tagged('post_install', '-at_install')
class TestAISessionSubagentsHttp(HttpCase):
    @contextmanager
    def _physical_tree(self, child_count=1, *, confirmation=False):
        """Use committed fixtures and real HTTP cursors, not TestCursor wrappers."""
        raw_cursor = self.registry._db.cursor
        with raw_cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            agent = env['ai.agent'].create({
                'name': 'Physical foreground agent',
                'system_prompt': 'Complete focused work.',
                'skill_ids': [Command.clear()],
            })
            agent.allowed_agent_ids = agent
            channel = agent._create_ai_chat_channel('Physical foreground callbacks')
            parent = env['ai.session'].sudo().create({
                'agent_id': agent.id, 'channel_id': channel.id,
            })
            create_tool = env.ref('ai.ir_actions_server_create_records')
            if confirmation:
                parent.state = {'available_tools': create_tool.ids}
            contact_name = f'Physical foreground confirmed {parent.id}'
            parent._prepare_model_request(
                [{'type': 'text', 'text': 'Run independent children'}],
                context_snapshot={'allowed_company_ids': env.companies.ids,
                                  'active_company_ids': env.companies.ids},
            )
            parent_uuid = parent.request_uuid
            apply_iap_result(parent, parent_uuid, {
                'kind': 'success', 'message': {'role': 'assistant', 'content': [
                    tool_call('start_session', f'child-{index}',
                              agent_id=agent.id, message=f'Child {index}')
                    for index in range(child_count)
                ] + ([tool_call(create_tool.ai_tool_name, 'confirm',
                    explanation='Create the confirmed contact?', model_name='res.partner',
                    preview_menu_id=False, values=[{'field_values': [
                        {'field': 'name', 'value': contact_name},
                    ]}],
                )] if confirmation else [])},
            })
            children = env['ai.session'].sudo().search([
                ('parent_session_id', '=', parent.id),
            ], order='id')
            fixture = {
                'parent_id': parent.id, 'parent_uuid': parent_uuid,
                'channel_id': channel.id, 'agent_id': agent.id, 'contact_name': contact_name,
                'children': [(child.id, child.request_uuid) for child in children],
            }
        try:
            with patch.object(self.registry, 'cursor', lambda readonly=False: raw_cursor()):
                yield fixture
        finally:
            with raw_cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env['ai.session'].sudo().browse(fixture['parent_id']).exists().unlink()
                env['discuss.channel'].sudo().browse(fixture['channel_id']).exists().unlink()
                env['ai.agent'].sudo().browse(fixture['agent_id']).exists().unlink()
                env['res.partner'].search([('name', 'in', [
                    fixture['contact_name'], fixture['contact_name'] + ' A',
                    fixture['contact_name'] + ' B', fixture['contact_name'] + ' C',
                ])]).unlink()

    def _callback(self, request_uuid, text, *, concurrent=False):
        with nullcontext() if concurrent else self.allow_requests(all_requests=True):
            return requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json={
                    'request_uuid': request_uuid, 'llm_error': False,
                    'llm_result': {'status': 'success', 'result': {
                        'role': 'assistant', 'content': ([{'type': 'text', 'text': text}]
                                                       if isinstance(text, str) else text),
                    }},
                }, timeout=25,
            )

    def _snapshot(self, session_id):
        with self.registry._db.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            session = env['ai.session'].sudo().browse(session_id)
            return {
                'loop_state': session.loop_state,
                'request_uuid': session.request_uuid,
                'previous_request_uuid': session.previous_request_uuid,
                'request_phase': session.request_phase,
                'resume_token': session.resume_token,
                'pending': session.pending_tool_call,
                'exchange_result': session.exchange_result,
                'payload': session.request_payload,
                'events': session.event_ids.ids,
            }

    def _results(self, snapshot):
        return [part for message in snapshot['payload']['messages']
                for part in message['content'] if part.get('type') == 'tool_result']

    def test_callback_replay_delivers_a_committed_child_after_interrupted_merge(self):
        with self._physical_tree() as fixture:
            child_id, child_uuid = fixture['children'][0]
            deliver = AIThreadController._deliver_subagent_result
            attempts = []

            def stop_before_first_merge(controller, session_id, request_uuid):
                if session_id == child_id:
                    attempts.append(request_uuid)
                    if len(attempts) == 1:
                        raise RuntimeError('worker stopped after child settlement commit')
                return deliver(controller, session_id, request_uuid)

            with (
                mute_logger('odoo.http'),
                patch.object(AIThreadController, '_deliver_subagent_result',
                             autospec=True, side_effect=stop_before_first_merge),
                patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport',
                      return_value=None) as transport,
            ):
                self.assertEqual(self._callback(child_uuid, 'Durable answer').status_code, 500)
                child = self._snapshot(child_id)
                self.assertEqual(child['loop_state'], 'ready')
                self.assertIn('Durable answer', child['exchange_result']['message'])
                parent = self._snapshot(fixture['parent_id'])
                self.assertEqual(parent['pending']['pending_results'][0]['child_session_id'], child_id)
                transport.assert_not_called()
                self.assertEqual(self._callback(child_uuid, 'Durable answer').status_code, 200)
                settled = self._snapshot(fixture['parent_id'])
                self.assertEqual(settled['loop_state'], 'waiting_model')
                self.assertEqual(settled['request_phase'], 'submitted')
                self.assertEqual(self._callback(child_uuid, 'Durable answer').status_code, 200)
                self.assertEqual(self._snapshot(fixture['parent_id']), settled)
                self.assertEqual(self._snapshot(child_id), child)
                transport.assert_called_once()
                self.assertEqual(transport.call_args.args[2]['request_uuid'], settled['request_uuid'])

    def test_simultaneous_child_callbacks_settle_independently_and_serialize_parent(self):
        with self._physical_tree(child_count=2) as fixture:
            child_ids = {child_id for child_id, _uuid in fixture['children']}
            locally_settled = Barrier(2)
            ready_to_merge = Barrier(2)
            observed = {'pids': {}, 'settlement_transactions': {}, 'contention': False}
            deliver = AIThreadController._deliver_subagent_result
            merge = self.registry['ai.session']._merge_child_result
            advance = self.registry['ai.session']._continue
            merge_order = []

            def observe_settlement(session, request_uuid):
                result = advance(session, request_uuid)
                if session.id in child_ids:
                    session.env.cr.execute('SELECT txid_current()')
                    observed['settlement_transactions'][session.id] = session.env.cr.fetchone()[0]
                    session.env.cr.execute(
                        "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'advisory' AND granted",
                    )
                    self.assertEqual(session.env.cr.fetchone()[0], 0)
                    locally_settled.wait(timeout=15)
                return result

            def synchronize_committed_children(controller, session_id, request_uuid):
                if session_id in child_ids:
                    controller.env.cr.execute('SELECT pg_backend_pid()')
                    observed['pids'][session_id] = controller.env.cr.fetchone()[0]
                    ready_to_merge.wait(timeout=15)
                    self.assertTrue(all(
                        self._snapshot(child_id)['exchange_result'] for child_id in child_ids
                    ))
                return deliver(controller, session_id, request_uuid)

            def observe_parent_contention(parent, child):
                merge_order.append(child.id)
                if len(merge_order) == 1:
                    other_id = next(iter(child_ids - {child.id}))
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline:
                        with self.registry._db.cursor() as cr:
                            cr.execute("""
                                SELECT EXISTS (
                                    SELECT FROM pg_locks
                                    WHERE pid = %s AND locktype = 'advisory' AND NOT granted
                                )
                            """, [observed['pids'][other_id]])
                            if cr.fetchone()[0]:
                                observed['contention'] = True
                                break
                        time.sleep(0.01)
                    self.assertTrue(observed['contention'], 'Second merge did not wait for parent ownership')
                return merge(parent, child)

            def submit_after_release(_connection, _route, payload, **_kwargs):
                with self.registry._db.cursor() as cr:
                    cr.execute("""
                        SELECT count(*) FROM pg_locks
                        WHERE pid = ANY(%s) AND locktype = 'advisory' AND granted
                    """, [list(observed['pids'].values())])
                    self.assertEqual(cr.fetchone()[0], 0)
                    cr.execute('SELECT id FROM ai_session WHERE id = %s FOR UPDATE NOWAIT',
                               [fixture['parent_id']])
                    self.assertEqual(cr.fetchone()[0], fixture['parent_id'])
                self.assertNotEqual(payload['request_uuid'], fixture['parent_uuid'])
                return None

            with (
                patch.object(AIThreadController, '_deliver_subagent_result',
                             autospec=True, side_effect=synchronize_committed_children),
                patch.object(self.registry['ai.session'], '_continue', observe_settlement),
                patch.object(self.registry['ai.session'], '_merge_child_result', observe_parent_contention),
                patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport',
                      side_effect=submit_after_release) as transport,
                self.allow_requests(all_requests=True),
                ThreadPoolExecutor(max_workers=2) as pool,
            ):
                futures = [pool.submit(self._callback, request_uuid, f'Answer {index}', concurrent=True)
                           for index, (_child_id, request_uuid) in enumerate(fixture['children'])]
                self.assertEqual([future.result(timeout=25).status_code for future in futures], [200, 200])
            self.assertEqual(len(set(observed['pids'].values())), 2)
            self.assertEqual(len(set(observed['settlement_transactions'].values())), 2)
            self.assertTrue(observed['contention'])
            parent = self._snapshot(fixture['parent_id'])
            results = self._results(parent)
            self.assertEqual([result['tool_call_id'] for result in results], ['child-0', 'child-1'])
            self.assertEqual([json.loads(result['result'][0]['text'])['session_id'] for result in results],
                             [child_id for child_id, _uuid in fixture['children']])
            self.assertEqual(parent['loop_state'], 'waiting_model')
            transport.assert_called_once()

    def test_child_callback_during_confirmation_and_resume_replay_execute_once(self):
        with self._physical_tree(confirmation=True) as fixture:
            self.authenticate('admin', 'admin')
            child_id, child_uuid = fixture['children'][0]
            waiting = self._snapshot(fixture['parent_id'])
            self.assertEqual(waiting['loop_state'], 'waiting_confirmation')
            with patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport',
                       return_value=None) as transport:
                self.assertEqual(self._callback(child_uuid, 'Done while awaiting approval').status_code, 200)
                filled = self._snapshot(fixture['parent_id'])
                self.assertEqual(filled['loop_state'], 'waiting_confirmation')
                self.assertEqual(filled['resume_token'], waiting['resume_token'])
                self.assertEqual(filled['pending']['user_input_request'], waiting['pending']['user_input_request'])
                self.assertEqual(filled['pending']['call_id'], waiting['pending']['call_id'])
                transport.assert_not_called()
                submit = AIThreadController._submit_request_successor
                attempts = []

                def stop_after_resume_commit(controller, request_uuid, **kwargs):
                    attempts.append(request_uuid)
                    if len(attempts) == 1:
                        raise RuntimeError('worker stopped after confirmation commit')
                    return submit(controller, request_uuid, **kwargs)

                payload = self.build_rpc_payload({
                    'channel_id': fixture['channel_id'],
                    'request_uuid': waiting['request_uuid'],
                    'resume_token': waiting['resume_token'],
                    'response': {'kind': 'confirmation', 'value': 'confirm_once'},
                })
                with (
                    mute_logger('odoo.http'),
                    patch.object(AIThreadController, '_submit_request_successor',
                                 autospec=True, side_effect=stop_after_resume_commit),
                ):
                    failed = self.url_open('/ai/resume_pending_interaction', json=payload)
                    self.assertIn('error', failed.json())
                    prepared = self._snapshot(fixture['parent_id'])
                    self.assertEqual(prepared['loop_state'], 'waiting_model')
                    self.assertEqual(prepared['request_phase'], 'prepared')
                    replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                    self.assertNotIn('error', replay.json())
                    self.assertEqual(replay.json()['result']['request_uuid'], prepared['request_uuid'])
                transport.assert_called_once()
                self.assertEqual(transport.call_args.args[2]['request_uuid'], prepared['request_uuid'])
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertEqual(env['res.partner'].search_count([
                    ('name', '=', fixture['contact_name']),
                ]), 1)
                children = env['ai.session'].sudo().search([
                    ('parent_session_id', '=', fixture['parent_id']),
                ])
                self.assertEqual(children.ids, [child_id])
            self.assertEqual(self._snapshot(fixture['parent_id'])['events'], prepared['events'])

    def _contact_call(self, env, call_id, name):
        return tool_call(env.ref('ai.ir_actions_server_create_records').ai_tool_name, call_id,
            explanation=f'Create {name}?', model_name='res.partner', preview_menu_id=False,
            values=[{'field_values': [{'field': 'name', 'value': name}]}],
        )

    def test_nested_delivery_replays_after_intermediate_parent_commits_terminal(self):
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
                grandchild = env['ai.session'].sudo().search([('parent_session_id', '=', parent_id)])
                grandchild_id, grandchild_uuid = grandchild.id, grandchild.request_uuid
                parent._resume_pending_interaction(
                    parent_uuid, parent.resume_token,
                    {'kind': 'confirmation', 'value': 'decline'},
                )
            merge = self.registry['ai.session']._merge_child_result
            owners = []
            stopped = False

            def stop_between_parent_edges(parent, child):
                nonlocal stopped
                parent.env.cr.execute("""
                    SELECT objid FROM pg_locks
                    WHERE pid = pg_backend_pid() AND locktype = 'advisory' AND granted
                """)
                self.assertEqual(parent.env.cr.fetchall(), [(parent.id,)])
                owners.append(parent.id)
                if parent.id == fixture['parent_id'] and not stopped:
                    stopped = True
                    raise RuntimeError('worker stopped between committed parent edges')
                return merge(parent, child)

            with (
                mute_logger('odoo.http'),
                patch.object(self.registry['ai.session'], '_merge_child_result', stop_between_parent_edges),
                patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport', return_value=None) as transport,
            ):
                self.assertEqual(self._callback(grandchild_uuid, 'Nested answer').status_code, 500)
                parent = self._snapshot(parent_id)
                self.assertEqual(parent['loop_state'], 'ready')
                self.assertEqual(parent['exchange_result']['status'], 'declined')
                self.assertEqual(self._snapshot(grandchild_id)['loop_state'], 'ready')
                self.assertEqual(self._snapshot(fixture['parent_id'])['pending']['pending_results'][0]['child_session_id'], parent_id)
                transport.assert_not_called()
                self.assertEqual(self._callback(grandchild_uuid, 'Nested answer').status_code, 200)
                self.assertEqual(self._snapshot(parent_id), parent)
                root = self._snapshot(fixture['parent_id'])
                self.assertEqual(root['loop_state'], 'waiting_model')
                self.assertEqual(root['previous_request_uuid'], parent_uuid)
                self.assertEqual(owners, [parent_id, fixture['parent_id']] * 2)
                transport.assert_called_once()
                self.assertEqual(transport.call_args.args[2]['request_uuid'], root['request_uuid'])
                self.assertEqual([json.loads(result['result'][0]['text'])['status'] for result in self._results(root)],
                                 ['declined'])

    def test_autoapproval_reaches_child_that_commits_confirmation_after_initial_sweep(self):
        with self._physical_tree(child_count=2) as fixture:
            self.authenticate('admin', 'admin')
            first_id, first_uuid = fixture['children'][0]
            second_id, second_uuid = fixture['children'][1]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                first = env['ai.session'].sudo().browse(first_id)
                second = env['ai.session'].sudo().browse(second_id)
                (first | second).state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                apply_iap_result(first, first_uuid, {
                    'kind': 'success', 'message': {'role': 'assistant', 'content': [
                        self._contact_call(env, 'first-confirm', fixture['contact_name'] + ' A'),
                    ]},
                })
                first_token = first.resume_token
                second_call = self._contact_call(env, 'second-confirm', fixture['contact_name'] + ' B')
            read_old_approval = Event()
            root_approved = Event()
            build_context = self.registry['ai.session']._build_tools_context
            paused = False

            def hold_child_with_old_approval(session):
                nonlocal paused
                context = build_context(session)
                if session.id == second_id and not paused:
                    paused = True
                    self.assertFalse(context['auto_confirm'])
                    read_old_approval.set()
                    self.assertTrue(root_approved.wait(timeout=15))
                return context

            with (
                patch.object(self.registry['ai.session'], '_build_tools_context', hold_child_with_old_approval),
                patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport', return_value=None) as transport,
                self.allow_requests(all_requests=True),
                ThreadPoolExecutor(max_workers=1) as pool,
            ):
                callback = pool.submit(self._callback, second_uuid, [second_call], concurrent=True)
                try:
                    self.assertTrue(read_old_approval.wait(timeout=15))
                    response = requests.post(
                        f'{self.base_url()}/ai/resume_pending_interaction',
                        cookies=self.opener.cookies,
                        json=self.build_rpc_payload({
                            'channel_id': fixture['channel_id'], 'session_id': first_id,
                            'request_uuid': first_uuid, 'resume_token': first_token,
                            'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
                        }), timeout=15,
                    )
                    self.assertNotIn('error', response.json())
                    self.assertEqual(self._snapshot(first_id)['loop_state'], 'waiting_model')
                    self.assertEqual(self._snapshot(second_id)['loop_state'], 'waiting_model')
                finally:
                    root_approved.set()
                self.assertEqual(callback.result(timeout=20).status_code, 200)
            self.assertEqual(self._snapshot(second_id)['loop_state'], 'waiting_model')
            self.assertNotEqual(self._snapshot(second_id)['request_uuid'], second_uuid)
            self.assertEqual(transport.call_count, 2)
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                self.assertTrue(env['ai.session'].sudo().browse(fixture['parent_id']).auto_confirm)
                for suffix in (' A', ' B'):
                    self.assertEqual(env['res.partner'].search_count([
                        ('name', '=', fixture['contact_name'] + suffix),
                    ]), 1)

    def test_replayed_autoapproval_resumes_all_already_pending_descendants(self):
        with self._physical_tree(child_count=3) as fixture:
            self.authenticate('admin', 'admin')
            first_id, first_uuid = fixture['children'][0]
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
                children = env['ai.session'].sudo().browse([child_id for child_id, _uuid in fixture['children']])
                children.state = {'available_tools': env.ref('ai.ir_actions_server_create_records').ids}
                for child, suffix in zip(children, (' A', ' B', ' C')):
                    apply_iap_result(child, child.request_uuid, {
                        'kind': 'success', 'message': {'role': 'assistant', 'content': [
                            self._contact_call(env, f'confirm-{child.id}', fixture['contact_name'] + suffix),
                        ]},
                    })
                token = children[0].resume_token
            sweep = AIThreadController._resume_auto_confirmations
            attempts = []

            def interrupt_first_sweep(controller, root_id):
                attempts.append(root_id)
                if len(attempts) == 1:
                    raise RuntimeError('worker stopped before autoapproval sweep')
                return sweep(controller, root_id)

            payload = self.build_rpc_payload({
                'channel_id': fixture['channel_id'], 'session_id': first_id,
                'request_uuid': first_uuid, 'resume_token': token,
                'response': {'kind': 'confirmation', 'value': 'auto_confirm'},
            })
            with (
                mute_logger('odoo.http'),
                patch.object(AIThreadController, '_resume_auto_confirmations',
                             autospec=True, side_effect=interrupt_first_sweep),
                patch('odoo.addons.ai.utils.session_env.call_odoo_ai_transport', return_value=None) as transport,
            ):
                failed = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertIn('error', failed.json())
                self.assertEqual(self._snapshot(first_id)['loop_state'], 'waiting_model')
                self.assertTrue(all(self._snapshot(child_id)['loop_state'] == 'waiting_confirmation'
                                    for child_id, _uuid in fixture['children'][1:]))
                replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', replay.json())
                self.assertTrue(all(self._snapshot(child_id)['loop_state'] == 'waiting_model'
                                    for child_id, _uuid in fixture['children']))
                self.assertEqual(transport.call_count, 3)
                replay = self.url_open('/ai/resume_pending_interaction', json=payload)
                self.assertNotIn('error', replay.json())
                self.assertEqual(transport.call_count, 3)
            with self.registry._db.cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                for suffix in (' A', ' B', ' C'):
                    self.assertEqual(env['res.partner'].search_count([
                        ('name', '=', fixture['contact_name'] + suffix),
                    ]), 1)
