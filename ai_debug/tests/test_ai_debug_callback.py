import json
from unittest.mock import MagicMock, patch

from odoo import api
from odoo.modules.registry import Registry
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.ai.models.ai_session import AiSession as EnterpriseAiSession
from odoo.addons.ai_debug.models.ai_session import AiSession as DebugAiSession


def assistant_text(text, provider_metadata=None):
    message = {
        'role': 'assistant',
        'content': [{'type': 'text', 'content': {'data': text}}],
    }
    if provider_metadata:
        message['provider_metadata'] = provider_metadata
    return message


@tagged('post_install', '-at_install')
class TestAiDebugCallback(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'AI Debug Callback Test Agent',
            'system_prompt': 'Answer plainly.',
        })
        cls.channel = cls.agent._create_ai_chat_channel('AI Debug Callback Test')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })

    def _prepare(self, body='Hi'):
        message = self.channel.message_post(body=body, message_type='comment')
        session = self.session.with_context(
            active_company_ids=self.env.companies.ids,
            allowed_company_ids=self.env.companies.ids,
            ai_context_snapshot={
                'active_company_ids': self.env.companies.ids,
                'allowed_company_ids': self.env.companies.ids,
            },
            ai_origin_message_id=message.id,
        )
        return session, session._prepare_initial_iap_request(message._convert_to_parts())

    @staticmethod
    def _capture(events):
        def capture(session, event_type, payload, **kwargs):
            events.append((event_type, payload, kwargs))
        return capture

    def test_callback_trace_is_correlated_terminal_and_replay_safe(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare()
            session._apply_iap_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            result = {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': assistant_text('Visible callback reply', {
                    'provider': 'callback_harness',
                    'model': 'deterministic-fixture',
                    'api': 'loopback',
                }),
            }
            message_count = len(session.channel_id.message_ids)
            applied = session._apply_iap_response(request, result)
            event_count = len(events)
            replay = session._apply_iap_response(request, result)

        self.assertTrue(applied['applied'])
        self.assertFalse(replay['applied'])
        self.assertEqual(len(events), event_count)
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertIn('Visible callback reply', session.channel_id.message_ids[0].body)
        self.assertEqual([event for event, _payload, _kwargs in events].count('new_trace'), 1)
        self.assertEqual([event for event, _payload, _kwargs in events].count('iteration'), 1)
        self.assertEqual([event for event, _payload, _kwargs in events].count('loop_end'), 1)
        trace = next(payload for event, payload, _kwargs in events if event == 'new_trace')
        self.assertEqual(trace['session_id'], session.id)
        self.assertEqual(trace['exchange_uuid'], request.exchange_uuid)
        self.assertEqual(trace['request_uuid'], request.request_uuid)
        self.assertEqual(trace['round_no'], 1)
        self.assertEqual(trace['request_state'], 'prepared')
        self.assertEqual(trace['user_query'], 'Hi')
        self.assertEqual(trace['instructions'], request.payload['instructions'])
        trace_target = next(kwargs for event, _payload, kwargs in events if event == 'new_trace')
        self.assertEqual(trace_target['target_user_id'], request.user_id.id)

        transitions = [
            (payload['previous_state'], payload['state'])
            for event, payload, _kwargs in events
            if event == 'request_state'
        ]
        self.assertEqual(transitions, [
            ('prepared', 'waiting_iap'),
            ('waiting_iap', 'done'),
        ])
        terminal = next(payload for event, payload, _kwargs in events if event == 'iteration')
        self.assertEqual(terminal['trace_id'], request.exchange_uuid)
        self.assertEqual(terminal['exchange_uuid'], request.exchange_uuid)
        self.assertEqual(terminal['iteration_id'], request.request_uuid)
        self.assertEqual(terminal['request_uuid'], request.request_uuid)
        self.assertEqual(terminal['iteration_index'], request.round_no)
        self.assertEqual(terminal['round_no'], request.round_no)
        self.assertEqual(terminal['request_body']['request_uuid'], request.request_uuid)
        self.assertEqual(terminal['request_body']['instructions'], request.payload['instructions'])
        self.assertEqual(terminal['request_body']['usage'], request.payload['usage'])
        self.assertNotIn('messages_sent', terminal)
        self.assertNotIn('tools', terminal)
        self.assertEqual(terminal['raw_response'], result)
        self.assertEqual(terminal['request_label'], 'Normalized IAP Submission')
        self.assertEqual(terminal['response_label'], 'Normalized IAP Result')
        self.assertEqual(terminal['provider'], 'callback_harness')
        self.assertEqual(terminal['model_name'], 'deterministic-fixture')
        self.assertEqual(terminal['provider_api'], 'loopback')
        self.assertGreaterEqual(terminal['duration_ms'], 0)
        self.assertEqual(terminal['duration_kind'], 'request_lifecycle')
        self.assertNotIn('tokens', terminal)
        terminal_target = next(kwargs for event, _payload, kwargs in events if event == 'iteration')
        self.assertEqual(terminal_target['target_user_id'], request.user_id.id)

        loop_end = next(payload for event, payload, _kwargs in events if event == 'loop_end')
        self.assertEqual(loop_end['termination_reason'], 'success')
        self.assertEqual(loop_end['iteration_count'], 1)
        self.assertEqual(loop_end['tool_call_count'], 0)
        self.assertEqual(loop_end['duration_ms'], terminal['duration_ms'])
        self.assertEqual(loop_end['duration_kind'], 'request_lifecycle')

        encoded = str(events).casefold()
        for forbidden in (
            'account_token', 'authorization', 'connection', 'cookie',
            'database_uuid', 'dbuuid', 'encrypted_content', 'thought_signature',
        ):
            self.assertNotIn(forbidden, encoded)

    def test_missing_provider_and_token_metadata_stays_unavailable(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('No metadata')
            session._apply_iap_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': assistant_text('No metadata result'),
            })

        iteration = next(payload for event, payload, _kwargs in events if event == 'iteration')
        self.assertIsNone(iteration['provider'])
        self.assertIsNone(iteration['model_name'])
        self.assertIsNone(iteration['provider_api'])
        self.assertNotIn('tokens', iteration)

    def test_debugger_failure_does_not_change_request_or_reply(self):
        session, request = self._prepare('Failure isolation')
        message_count = len(session.channel_id.message_ids)

        def fail_with_database_error(debug_session, *_args, **_kwargs):
            debug_session.env.cr.execute('SELECT 1 / 0')

        with patch.object(
            DebugAiSession,
            '_ai_debug_trace_request_result',
            new=fail_with_database_error,
        ):
            applied = session._apply_iap_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': assistant_text('Still visible'),
            })

        self.assertTrue(applied['applied'])
        self.assertEqual(request.state, 'done')
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertIn('Still visible', session.channel_id.message_ids[0].body)
        self.env.cr.execute('SELECT 1')
        self.assertEqual(self.env.cr.fetchone(), (1,))

    def test_prepare_debugger_failure_does_not_poison_request_creation(self):
        with patch.object(
            DebugAiSession,
            '_ai_debug_trace_request_prepared',
            side_effect=RuntimeError('debugger fixture failure'),
        ):
            _session, request = self._prepare('Prepare isolation')
        self.assertEqual(request.state, 'prepared')
        self.assertTrue(request.request_uuid)

    def test_direct_sync_tracing_and_no_ledger_row(self):
        events = []
        request_count = self.env['ai.session.request'].sudo().search_count([])
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={
                'status': 'success',
                'result': assistant_text('Direct result'),
            }),
        ):
            result = self.env['ai.session']._get_direct_response(
                instructions='Answer.',
                message=[{'type': 'text', 'content': {'data': 'Hi'}}],
            )

        self.assertEqual(result, assistant_text('Direct result')['content'])
        self.assertEqual(
            [event for event, _payload, _kwargs in events],
            ['new_trace', 'iteration', 'loop_end'],
        )
        self.assertEqual(
            self.env['ai.session.request'].sudo().search_count([]), request_count,
        )

    def test_direct_sync_forwards_loop_context_by_keyword(self):
        forwarded = {}
        expected_tools_context = {'state': {}}

        def enterprise_loop(
            enterprise_session, instructions, message, tools_context,
            record=None, **completion_options,
        ):
            forwarded.update({
                'session': enterprise_session,
                'instructions': instructions,
                'message': message,
                'tools_context': tools_context,
                'record': record,
                'completion_options': completion_options,
            })
            yield {'final_message': assistant_text('Extension result')['content']}

        def extension_loop(enterprise_session, *args, **kwargs):
            kwargs.setdefault('tools_context', {})['extension_marker'] = True
            yield from enterprise_loop(enterprise_session, *args, **kwargs)

        message = [{'type': 'text', 'content': {'data': 'Hi'}}]
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send'),
            patch.object(EnterpriseAiSession, '_run_agentic_loop', new=extension_loop),
        ):
            result = list(self.env['ai.session']._run_agentic_loop(
                instructions='Answer.',
                message=message,
                tools_context=expected_tools_context,
                record=self.agent,
                temperature=0,
            ))

        self.assertEqual(result, [{
            'final_message': assistant_text('Extension result')['content'],
        }])
        self.assertEqual(forwarded['instructions'], 'Answer.')
        self.assertEqual(forwarded['message'], message)
        self.assertIs(forwarded['tools_context'], expected_tools_context)
        self.assertTrue(forwarded['tools_context']['extension_marker'])
        self.assertEqual(forwarded['record'], self.agent)
        self.assertEqual(forwarded['completion_options'], {'temperature': 0})

    def test_payload_sanitizer_redacts_secrets_and_bounds_binary(self):
        original = {
            'connection': {'account_token': 'secret-token', 'endpoint': 'fixture'},
            'nested': {
                'headers': {'Authorization': 'Bearer secret'},
                'apiKey': 'camel-secret',
                'clientSecret': 'client-secret',
                'set-cookie': 'session-secret',
                'resume_token': 'resume-secret',
                'blob': b'binary fixture',
            },
        }
        sanitized = self.session._ai_debug_sanitize(original)

        self.assertEqual(sanitized['connection'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['headers'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['apiKey'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['clientSecret'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['set-cookie'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['resume_token'], '[REDACTED]')
        self.assertEqual(
            sanitized['nested']['blob'],
            {'_binary_excluded': True, 'size': len(b'binary fixture')},
        )
        self.assertIn('account_token', original['connection'])

    def test_normalized_messages_strip_continuity_and_bound_binary(self):
        messages = [{
            'role': 'assistant',
            'provider_metadata': {
                'provider': 'google',
                'model': 'fixture-model',
                'api': 'generateContent',
                'internal': 'excluded',
            },
            'content': [
                {
                    'type': 'text',
                    'content': {'data': 'Visible text'},
                    'provider_data': {'thought_signature': 'opaque-signature'},
                },
                {
                    'type': 'inline_data',
                    'content': {'mimetype': 'image/png', 'data': 'iVBORw0KGg'},
                },
                {
                    'type': 'inline_data',
                    'content': {'mimetype': 'application/pdf', 'data': 'pdf-bytes'},
                },
            ],
        }]

        normalized = self.session._ai_debug_normalized_messages(messages)
        self.assertEqual(normalized[0]['provider_metadata'], {
            'provider': 'google',
            'model': 'fixture-model',
            'api': 'generateContent',
        })
        self.assertTrue(normalized[0]['content'][0]['_provider_data_excluded'])
        self.assertNotIn('provider_data', normalized[0]['content'][0])
        self.assertEqual(
            normalized[0]['content'][1]['content']['data'],
            'data:image/png;base64,iVBORw0KGg',
        )
        self.assertTrue(normalized[0]['content'][2]['content']['_binary_excluded'])
        self.assertNotIn('data', normalized[0]['content'][2]['content'])

        preview_data = 'A' * 47_000
        preview = self.session._ai_debug_normalized_messages([{
            'role': 'assistant',
            'content': [{
                'type': 'inline_data',
                'content': {'mimetype': 'image/png', 'data': preview_data},
            }],
        }])
        sanitized_preview = self.session._ai_debug_sanitize(preview)
        self.assertEqual(
            sanitized_preview[0]['content'][0]['content']['data'],
            f'data:image/png;base64,{preview_data}',
        )
        oversized = self.session._ai_debug_normalized_messages([{
            'role': 'assistant',
            'content': [{
                'type': 'inline_data',
                'content': {'mimetype': 'image/png', 'data': 'A' * 48_001},
            }],
        }])
        self.assertTrue(oversized[0]['content'][0]['content']['_binary_excluded'])

    def test_bus_delivery_is_transactional_and_internal_user_scoped(self):
        bus = self.env['bus.bus'].sudo()
        self.session._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': 'transactional-fixture',
        })
        row = bus.search([('message', 'ilike', 'transactional-fixture')], limit=1)
        self.assertTrue(row)
        message = json.loads(row.message)
        self.assertEqual(message['type'], 'new_trace')
        self.assertEqual(message['payload']['trace_id'], 'transactional-fixture')
        queued = self.env.cr.precommit.data['ai_debug.bus_rows']
        self.assertIn((row.id, self.env.uid), queued)

        self.session._ai_debug_bus_send('iteration', {
            'type': 'iteration',
            'trace_id': 'oversized-fixture',
            'exchange_uuid': 'oversized-fixture',
            'request_uuid': 'oversized-request-fixture',
            'round_no': 1,
            'session_id': self.session.id,
            'messages_sent': ['X' * 64_000] * 10,
        })
        oversized_row = bus.search([
            ('message', 'ilike', 'oversized-fixture'),
        ], order='id desc', limit=1)
        oversized_payload = json.loads(oversized_row.message)['payload']
        self.assertTrue(oversized_payload['_payload_excluded'])
        self.assertEqual(oversized_payload['session_id'], self.session.id)
        self.assertEqual(oversized_payload['request_uuid'], 'oversized-request-fixture')
        self.assertNotIn('messages_sent', oversized_payload)

        portal = new_test_user(
            self.env,
            login='ai_debug_portal_bus',
            groups='base.group_portal',
        )
        before = bus.search_count([('message', 'ilike', 'denied-fixture')])
        self.session.with_user(portal)._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': 'denied-fixture',
        })
        self.assertEqual(
            bus.search_count([('message', 'ilike', 'denied-fixture')]), before,
        )

    def test_non_internal_user_cannot_subscribe_to_legacy_channel(self):
        portal = new_test_user(
            self.env,
            login='ai_debug_portal_subscription',
            groups='base.group_portal',
        )
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = portal.id
        with patch('odoo.addons.bus.models.ir_websocket.wsrequest', new=mock_wsrequest):
            channels = self.env['ir.websocket'].with_user(portal)._build_bus_channel_list([
                'ai_debug', 'other',
            ])
        string_channels = [channel for channel in channels if isinstance(channel, str)]
        self.assertNotIn('ai_debug', string_channels)
        self.assertIn('other', string_channels)

    def test_rolled_back_transaction_does_not_publish_bus_event(self):
        with self.assertRaises(RuntimeError):
            with Registry(self.env.cr.dbname).cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env['ai.session']._ai_debug_bus_send('new_trace', {
                    'type': 'new_trace',
                    'trace_id': 'rolled-back-fixture',
                })
                raise RuntimeError('rollback fixture')
        with Registry(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            self.assertFalse(env['bus.bus'].sudo().search([
                ('message', 'ilike', 'rolled-back-fixture'),
            ]))

    def test_savepoint_rollback_does_not_leave_bus_event(self):
        bus = self.env['bus.bus'].sudo()
        with self.assertRaises(RuntimeError):
            with self.env.cr.savepoint(flush=False):
                self.session._ai_debug_bus_send('new_trace', {
                    'type': 'new_trace',
                    'trace_id': 'savepoint-rollback-fixture',
                })
                self.assertTrue(bus.search([
                    ('message', 'ilike', 'savepoint-rollback-fixture'),
                ]))
                raise RuntimeError('savepoint rollback fixture')
        self.assertFalse(bus.search([
            ('message', 'ilike', 'savepoint-rollback-fixture'),
        ]))

    def test_postcommit_wakeup_failure_is_contained(self):
        with patch(
            'odoo.addons.ai_debug.models.ai_session.odoo.sql_db.db_connect',
            side_effect=RuntimeError('notify fixture failure'),
        ):
            with Registry(self.env.cr.dbname).cursor() as cr:
                env = api.Environment(cr, self.env.uid, {})
                env['ai.session']._ai_debug_bus_send('new_trace', {
                    'type': 'new_trace',
                    'trace_id': 'notify-failure-fixture',
                })
        with Registry(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            self.assertTrue(env['bus.bus'].sudo().search([
                ('message', 'ilike', 'notify-failure-fixture'),
            ]))


@tagged('post_install', '-at_install')
class TestAiDebugHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, cls.env.uid, {})
            new_test_user(
                env,
                login='ai_debug_portal_page',
                password='portal-page-fixture',
                groups='base.group_portal',
            )

    def test_page_is_internal_only(self):
        self.authenticate('admin', 'admin')
        internal = self.url_open('/ai-debug')
        self.assertEqual(internal.status_code, 200)

        self.authenticate('ai_debug_portal_page', 'portal-page-fixture')
        portal = self.url_open('/ai-debug', allow_redirects=False)
        self.assertEqual(portal.status_code, 303)
        self.assertIn('/web/login', portal.headers['Location'])
