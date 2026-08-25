from unittest.mock import MagicMock, patch

from odoo import api
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.ai.models.ai_session import AiSession as EnterpriseAiSession
from odoo.addons.ai_debug.models.ai_session import AiSession as DebugAiSession


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'content': {'data': text}}],
    }


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
                'result': assistant_text('Visible callback reply'),
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
        terminal = next(payload for event, payload, _kwargs in events if event == 'iteration')
        self.assertEqual(terminal['trace_id'], request.exchange_uuid)
        self.assertEqual(terminal['exchange_uuid'], request.exchange_uuid)
        self.assertEqual(terminal['iteration_id'], request.request_uuid)
        self.assertEqual(terminal['request_uuid'], request.request_uuid)
        self.assertEqual(terminal['iteration_index'], request.round_no)
        self.assertEqual(terminal['round_no'], request.round_no)
        self.assertNotIn('provider', terminal)
        self.assertNotIn('tokens', terminal)
        self.assertNotIn('request_body', terminal)

    def test_debugger_failure_does_not_change_request_or_reply(self):
        session, request = self._prepare('Failure isolation')
        message_count = len(session.channel_id.message_ids)
        with patch.object(
            DebugAiSession,
            '_ai_debug_trace_request_result',
            side_effect=RuntimeError('debugger fixture failure'),
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

    def test_payload_sanitizer_redacts_secrets_and_bounds_binary(self):
        original = {
            'connection': {'account_token': 'secret-token', 'endpoint': 'fixture'},
            'nested': {
                'headers': {'Authorization': 'Bearer secret'},
                'resume_token': 'resume-secret',
                'blob': b'binary fixture',
            },
        }
        sanitized = self.session._ai_debug_sanitize(original)

        self.assertEqual(sanitized['connection'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['headers'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['resume_token'], '[REDACTED]')
        self.assertEqual(
            sanitized['nested']['blob'],
            {'_binary_excluded': True, 'size': len(b'binary fixture')},
        )
        self.assertIn('account_token', original['connection'])

    def test_bus_delivery_is_postcommit_and_internal_user_scoped(self):
        self.env.cr.postcommit.data.pop('ai_debug.events', None)
        with patch('odoo.addons.bus.models.bus.BusBus._sendone') as send:
            self.session._ai_debug_bus_send('new_trace', {
                'type': 'new_trace',
                'trace_id': 'postcommit-fixture',
            })
        send.assert_not_called()
        queued = self.env.cr.postcommit.data['ai_debug.events']
        self.assertEqual(queued[0][0], self.env.uid)
        self.assertEqual(queued[0][1], 'new_trace')

        portal = new_test_user(
            self.env,
            login='ai_debug_portal_bus',
            groups='base.group_portal',
        )
        self.env.cr.postcommit.data.pop('ai_debug.events', None)
        self.session.with_user(portal)._ai_debug_bus_send('new_trace', {
            'type': 'new_trace',
            'trace_id': 'denied-fixture',
        })
        self.assertNotIn('ai_debug.events', self.env.cr.postcommit.data)

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
