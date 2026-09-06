# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

import requests
from psycopg2.errorcodes import SERIALIZATION_FAILURE
from psycopg2.errors import SerializationFailure

from odoo import api, http, SUPERUSER_ID
from odoo.tests import HttpCase, tagged, TransactionCase

from odoo.addons.ai.controllers.thread import CHANNEL_NAME_INSTRUCTIONS
from odoo.addons.ai.models.ai_session import AiSession

from .common import apply_iap_result


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
    }


def accept_submitted_request(_connection, _route, _payload, **_kwargs):
    return None


@tagged('post_install', '-at_install')
class TestAIChannelNameContinuation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Channel Name Continuation Agent',
            'system_prompt': 'Answer plainly.',
        })

    def _prepare_title(self, body='Name this conversation'):
        channel = self.agent._create_ai_chat_channel()
        conversation = self.env['ai.session'].sudo().create({
            'agent_id': self.agent.id,
            'channel_id': channel.id,
        })
        message = channel.message_post(body=body, message_type='comment')
        context_snapshot = {
            'allowed_company_ids': self.env.companies.ids,
            'active_company_ids': self.env.companies.ids,
        }
        title_session = self.env['ai.session'].sudo().create({})
        title_session._prepare_request(
            {
                'messages': [{
                    'role': 'user',
                    'content': message._convert_to_parts(),
                }],
                'instructions': CHANNEL_NAME_INSTRUCTIONS,
                'tools': [],
                'usage': 'channel_name',
            },
            continuation_data={
                'continuation_type': 'channel_name',
                'channel_id': channel.id,
            },
            context_snapshot=context_snapshot,
            request_round=1,
            request_round_limit=1,
        )
        return channel, conversation, message, title_session, context_snapshot

    def test_title_request_uses_one_headless_session(self):
        channel, conversation, message, title_session, context = self._prepare_title()

        self.assertFalse(title_session.agent_id)
        self.assertFalse(title_session.channel_id)
        self.assertFalse(title_session.res_model)
        self.assertFalse(title_session.res_id)
        self.assertEqual(channel.ai_session_ids, conversation)
        self.assertEqual(title_session.loop_state, 'waiting_model')
        self.assertEqual(title_session.request_phase, 'prepared')
        self.assertFalse(title_session.request_result)
        self.assertEqual(title_session.request_context, context)
        self.assertEqual(title_session.continuation_data, {
            'continuation_type': 'channel_name',
            'channel_id': channel.id,
        })
        self.assertEqual(title_session.request_payload, {
            'messages': [{
                'role': 'user',
                'content': message._convert_to_parts(),
            }],
            'instructions': CHANNEL_NAME_INSTRUCTIONS,
            'tools': [],
            'usage': 'channel_name',
        })

    def test_title_result_is_normalized_retained_and_applied_once(self):
        channel, _conversation, _message, title_session, _context = self._prepare_title()
        request_uuid = title_session.request_uuid
        result = {
            'kind': 'success',
            'message': assistant_text('\n  Quarterly\nReport  \n'),
        }

        outcome = apply_iap_result(title_session, request_uuid, result)
        replay = apply_iap_result(title_session, request_uuid, result)

        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertEqual(replay['response']['responseState'], 'idle')
        self.assertEqual(channel.name, 'Quarterly Report')
        self.assertEqual(title_session.loop_state, 'ready')
        self.assertFalse(title_session.request_phase)
        self.assertEqual(title_session.request_uuid, request_uuid)
        self.assertEqual(title_session.request_result, result)

    def test_title_error_and_changed_target_settle_without_overwriting(self):
        error_channel, _conversation, _message, error_session, _context = (
            self._prepare_title('This title request fails')
        )
        apply_iap_result(error_session, error_session.request_uuid, {
            'kind': 'failure',
            'code': 'request_failed',
        })
        self.assertFalse(error_channel.name)
        self.assertEqual(error_session.loop_state, 'ready')
        self.assertTrue(error_session.request_result)

        channel, _conversation, _message, title_session, _context = self._prepare_title()
        channel.name = 'Manual title'
        apply_iap_result(title_session, title_session.request_uuid, {
            'kind': 'success',
            'message': assistant_text('Generated title'),
        })
        self.assertEqual(channel.name, 'Manual title')
        self.assertEqual(title_session.loop_state, 'ready')


@tagged('post_install', '-at_install')
class TestAIChannelNameContinuationHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, cls.env.ref('base.user_admin').id, {})
            cls.agent_id = env['ai.agent'].create({
                'name': 'Channel Name HTTP Agent',
                'system_prompt': 'Answer plainly.',
            }).id

    def _create_committed_chat(
        self, body='Name this committed chat', *, website_builder=False,
    ):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            if website_builder:
                session_data = env['ai.agent'].action_launch_ai_chat(
                    interface_key='website_builder_ai',
                )
                channel = env['discuss.channel'].browse(session_data['ai_channel_id'])
                conversation = env['ai.session'].sudo().search([
                    ('channel_id', '=', channel.id),
                ])
            else:
                channel = env['ai.agent'].browse(self.agent_id)._create_ai_chat_channel()
                conversation = env['ai.session'].sudo().create({
                    'agent_id': self.agent_id,
                    'channel_id': channel.id,
                })
            message = channel.message_post(body=body, message_type='comment')
            return {
                'channel_id': channel.id,
                'conversation_id': conversation.id,
                'message_id': message.id,
            }

    def _start_session_advance(self, chat):
        return self.url_open(
            '/ai/start_session_advance',
            json=self.build_rpc_payload({
                'channel_id': chat['channel_id'],
                'mail_message_id': chat['message_id'],
            }),
        )

    def _post_completion_callback(self, request_uuid, result):
        with self.allow_requests(all_requests=True):
            return requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json={
                    'request_uuid': request_uuid,
                    'llm_result': {'status': 'success', 'result': result},
                    'llm_error': False,
                },
                timeout=12,
            )

    def _get_title_session(self, channel_id):
        self.env.invalidate_all()
        sessions = self.env['ai.session'].sudo().search([
            ('agent_id', '=', False),
            ('channel_id', '=', False),
        ])
        return sessions.filtered(
            lambda session: (
                session.continuation_data.get('continuation_type') == 'channel_name'
                and session.continuation_data.get('channel_id') == channel_id
            )
        )

    def test_start_commits_both_sessions_before_submission(self):
        self.authenticate('admin', 'admin')
        chat = self._create_committed_chat()
        submissions = []
        visible_sessions = []

        def observe_submission(_connection, route, payload, **_kwargs):
            submissions.append((route, payload.copy()))
            with self.registry.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                visible_sessions.append(env['ai.session'].search_count([
                    ('request_phase', '=', 'prepared'),
                    ('request_uuid', '!=', False),
                ]))
            return accept_submitted_request(_connection, route, payload)

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=observe_submission,
        ):
            response = self._start_session_advance(chat)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(submissions), 2)
        self.assertGreaterEqual(visible_sessions[0], 2)
        self.assertNotEqual(submissions[0][1]['request_uuid'], submissions[1][1]['request_uuid'])
        self.assertEqual([submission[0] for submission in submissions], ['1/get_completions'] * 2)
        self.assertTrue(all(submission[1]['webhook_url'].endswith(
            '/ai/completion_result_ready'
        ) for submission in submissions))
        self.assertTrue(all(submission[1]['llm_retry'] is False for submission in submissions))
        self.assertTrue(all('callback_url' not in submission[1] for submission in submissions))
        self.assertEqual(
            [submission[1].get('usage') for submission in submissions],
            ['channel_name', 'agent:custom'],
        )
        title_session = self._get_title_session(chat['channel_id'])
        self.assertEqual(len(title_session), 1)
        self.assertFalse(title_session.agent_id)
        self.assertFalse(title_session.channel_id)
        conversation = self.env['ai.session'].sudo().browse(chat['conversation_id'])
        self.assertEqual(conversation.channel_id.ai_session_ids, conversation)

    def test_title_submission_failure_does_not_fail_main(self):
        self.authenticate('admin', 'admin')
        chat = self._create_committed_chat('Keep the main request alive')

        def submit(_connection, _route, payload, **_kwargs):
            if payload.get('usage') == 'channel_name':
                raise RuntimeError('title transport unavailable')
            return None

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=submit,
        ):
            response = self._start_session_advance(chat)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['responseState'], 'running')
        conversation = self.env['ai.session'].sudo().browse(chat['conversation_id'])
        title_session = self._get_title_session(chat['channel_id'])
        self.assertEqual(conversation.request_phase, 'submitted')
        self.assertEqual(title_session.request_phase, 'prepared')

    def test_rejected_main_start_does_not_prepare_a_title(self):
        self.authenticate('admin', 'admin')
        chat = self._create_committed_chat(
            'Do not orphan a title request',
            website_builder=True,
        )

        with (
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            ) as transport,
        ):
            response = self._start_session_advance(chat)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['responseState'], 'idle')
        transport.assert_not_called()
        self.assertFalse(self._get_title_session(chat['channel_id']))

    def test_callback_retries_title_from_the_persisted_result(self):
        self.authenticate('admin', 'admin')
        chat = self._create_committed_chat('Retry this title')
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=accept_submitted_request,
        ):
            self._start_session_advance(chat)
        title_session = self._get_title_session(chat['channel_id'])
        request_uuid = title_session.request_uuid
        original_continue = AiSession._continue_channel_name
        attempts = []

        def fail_once(session):
            self.assertIs(session.env.cr, http.request.env.cr)
            channel = session.env['discuss.channel'].browse(chat['channel_id'])
            attempts.append({
                'request_result': session.request_result,
                'channel_name': channel.name,
                'loop_state': session.loop_state,
            })
            if len(attempts) == 1:
                original_continue(session)
                error = SerializationFailure('retry title continuation')
                error.__setstate__({'pgcode': SERIALIZATION_FAILURE})
                raise error
            return original_continue(session)

        with patch.object(
            AiSession, '_continue_channel_name', autospec=True, side_effect=fail_once,
        ):
            response = self._post_completion_callback(
                request_uuid,
                assistant_text('Durable channel title'),
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]['request_result'], attempts[1]['request_result'])
        self.assertFalse(attempts[0]['channel_name'])
        self.assertFalse(attempts[1]['channel_name'])
        self.assertEqual(attempts[0]['loop_state'], 'waiting_model')
        self.assertEqual(attempts[1]['loop_state'], 'waiting_model')
        self.env.invalidate_all()
        self.assertEqual(
            self.env['discuss.channel'].browse(chat['channel_id']).name,
            'Durable channel title',
        )
        title_session = self.env['ai.session'].sudo().browse(title_session.id)
        self.assertEqual(title_session.loop_state, 'ready')
        self.assertTrue(title_session.request_result)
