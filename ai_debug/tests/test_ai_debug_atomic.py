"""Debugger facts share the production callback's atomic business transaction."""

from contextlib import contextmanager
from unittest.mock import patch

import requests

from odoo import api, Command
from odoo.exceptions import ConcurrencyError
from odoo.tests import HttpCase, tagged
from odoo.addons.ai.controllers.thread import AIThreadController
from odoo.addons.base.tests.files import PNG_B64


def assistant(content):
    return {'role': 'assistant', 'content': content}


@tagged('post_install', '-at_install')
class TestAiDebugAtomicCallback(HttpCase):
    @contextmanager
    def _fixture(self, *, image):
        raw_cursor = self.registry._db.cursor
        with raw_cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            agent = env['ai.agent'].create({
                'name': 'Atomic debugger fixture', 'system_prompt': 'Answer briefly.',
                'skill_ids': [Command.clear()],
            })
            agent.allowed_agent_ids = agent
            channel = agent._create_ai_chat_channel('Atomic debugger fixture')
            root = env['ai.session'].sudo().create({'agent_id': agent.id, 'channel_id': channel.id})
            image_tool = env.ref('ai.ir_actions_server_ai_generate_image')
            if image:
                root.state = {'available_tools': image_tool.ids}
            root = root.with_context(allowed_company_ids=env.companies.ids, active_company_ids=env.companies.ids)
            root._prepare_agent_request([{'type': 'text', 'text': 'Fixture'}])

            def delegate(parent):
                parent._store_request_result(parent.request_uuid, {'kind': 'success', 'message': assistant([{
                    'type': 'tool_call', 'name': 'start_session', 'call_id': 'child',
                    'args': {'agent_id': agent.id, 'message': 'Fixture child'},
                }])})
                outcome = parent._continue(parent.request_uuid, parent.request_result)
                return env['ai.session'].sudo().browse(outcome['prepared_requests'][0]['session_id'])

            if image:
                title = f'atomic-debug-{root.id}'
                root._store_request_result(root.request_uuid, {'kind': 'success', 'message': assistant([{
                    'type': 'tool_call', 'name': image_tool.ai_tool_name, 'call_id': 'image',
                    'args': {'prompt': 'Green mug', 'images_paths': [], 'image_title': title,
                             'feedback': 'Here is the image', 'aspect_ratio': '1:1'},
                }])})
                outcome = root._continue(root.request_uuid, root.request_result)
                leaf = env['ai.session'].sudo().browse(outcome['prepared_requests'][0]['session_id'])
                sessions = root | leaf
            else:
                middle = delegate(root)
                leaf = delegate(middle)
                # A declined ancestor waits for its outstanding descendant before
                # its result can be delivered to the root.
                middle._finish_exchange('declined')
                sessions = root | middle | leaf
            fixture = {
                'ids': sessions.ids, 'root': root.id, 'leaf': leaf.id, 'uuid': leaf.request_uuid,
                'traces': [session.request_context['ai_debug_exchange_uuid'] for session in sessions],
                'channel': channel.id, 'agent': agent.id,
                'attachment_name': f'AI Generated {title}' if image else 'No atomic image',
            }
        try:
            # HTTP must use independent real cursors, not HttpCase's shared test cursor.
            with patch.object(self.registry, 'cursor', lambda readonly=False: raw_cursor()):
                yield fixture
        finally:
            with raw_cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env['ai.session'].sudo().browse(fixture['root']).exists().unlink()
                env['discuss.channel'].sudo().browse(fixture['channel']).exists().unlink()
                env['ai.agent'].sudo().browse(fixture['agent']).exists().unlink()
                env['ir.attachment'].sudo().search([('name', '=', fixture['attachment_name'])]).unlink()
                cr.execute("DELETE FROM bus_bus WHERE message::jsonb->'payload'->>'trace_id' = ANY(%s)",
                           [fixture['traces']])

    def _snapshot(self, fixture):
        with self.registry._db.cursor() as cr:
            cr.execute('''SELECT id, loop_state, request_uuid, request_phase, request_result,
                                 pending_tool_call
                            FROM ai_session WHERE id = ANY(%s) ORDER BY id''', [fixture['ids']])
            sessions = cr.fetchall()
            cr.execute("SELECT id FROM ir_attachment WHERE name = %s ORDER BY id", [fixture['attachment_name']])
            attachments = cr.fetchall()
            cr.execute("""SELECT id, message::jsonb FROM bus_bus
                            WHERE message::jsonb->'payload'->>'trace_id' = ANY(%s) ORDER BY id""",
                       [fixture['traces']])
            return {'sessions': sessions, 'attachments': attachments, 'events': cr.fetchall()}

    def _exercise_atomic_callback(self, *, image):
        with self._fixture(image=image) as fixture:
            before = self._snapshot(fixture)
            attempts = []
            original = AIThreadController._session_transaction

            @contextmanager
            def retry_before_commit(controller, session, **actor_params):
                with original(controller, session, **actor_params) as bound:
                    yield bound
                    bound.env.flush_all()
                    # Independent readers cannot see receipt, settlement, parent
                    # application, the generated attachment, or any debugger fact.
                    self.assertEqual(self._snapshot(fixture), before)
                    transport.assert_not_called()
                    bound.env.cr.execute('SELECT txid_current()')
                    attempts.append(bound.env.cr.fetchone()[0])
                    if len(attempts) == 1:
                        raise ConcurrencyError('Retry the entire callback including debugger facts')

            content = ([{'type': 'inline_data', 'mimetype': 'image/png',
                         'data': PNG_B64.decode() if isinstance(PNG_B64, bytes) else PNG_B64}]
                       if image else [{'type': 'text', 'text': 'Child result'}])
            payload = {'request_uuid': fixture['uuid'], 'llm_error': False,
                       'llm_result': {'status': 'success', 'result': assistant(content)}}
            with (
                patch.object(AIThreadController, '_session_transaction', retry_before_commit),
                patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
                self.allow_requests(all_requests=True),
            ):
                response = requests.post(self.base_url() + '/ai/completion_result_ready', json=payload, timeout=30)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(len(attempts), 2)
            self.assertNotEqual(*attempts)
            self.assertEqual(transport.call_count, 0 if image else 1)
            after = self._snapshot(fixture)
            prior_ids = {row_id for row_id, _event in before['events']}
            events = [event for row_id, event in after['events'] if row_id not in prior_ids]
            received = [event for event in events if event['type'] == 'iteration'
                        and event['payload'].get('phase') == 'result_received']
            self.assertEqual(len(received), 1, 'Rolled-back receipt must not survive retry')
            self.assertEqual(received[0]['payload']['request_uuid'], fixture['uuid'])
            terminals = [event['payload'] for event in events if event['type'] == 'loop_end']
            self.assertEqual(len(terminals), 2)
            if image:
                self.assertTrue(all(terminal['exchange_result'] is None for terminal in terminals))
            else:
                by_trace = {terminal['trace_id']: terminal for terminal in terminals}
                leaf_result = by_trace[fixture['traces'][-1]]['exchange_result']
                middle_result = by_trace[fixture['traces'][1]]['exchange_result']
                self.assertEqual(leaf_result['status'], 'completed')
                self.assertIn('Child result', leaf_result['message'])
                self.assertEqual(middle_result['status'], 'declined')
                self.assertIn('Skipped', middle_result['message'])
            self.assertEqual(sum(event['type'] == 'tool_call_completed' for event in events), 1 if image else 2)
            self.assertEqual(sum(event['payload'].get('phase') == 'child_applied' for event in events), 1 if image else 2)
            self.assertEqual(len(after['attachments']), 1 if image else 0)
            self.assertEqual(next(row for row in after['sessions'] if row[0] == fixture['leaf'])[1], 'ready')
            with self.allow_requests(all_requests=True), patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None,
            ) as replay_transport:
                replay = requests.post(self.base_url() + '/ai/completion_result_ready', json=payload, timeout=30)
            self.assertEqual(replay.status_code, 200, replay.text)
            replay_transport.assert_not_called()
            self.assertEqual(self._snapshot(fixture), after, 'Replay must not duplicate facts or image effects')

    def test_nested_delivery_and_debugger_facts_retry_atomically(self):
        self._exercise_atomic_callback(image=False)

    def test_image_application_and_debugger_facts_retry_atomically(self):
        self._exercise_atomic_callback(image=True)
