# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

import requests

from odoo import api, Command
from odoo.exceptions import LockError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.ai.controllers.thread import IAP_TRANSPORT_TIMEOUT
from odoo.addons.ai.utils.ai_utils import UserInputResponse


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'content': {'data': text}}],
    }


@tagged('post_install', '-at_install')
class TestAISessionRequestHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, cls.env.uid, {})
            agent = env['ai.agent'].create({
                'name': 'Callback HTTP Test Agent',
                'system_prompt': 'Answer plainly.',
            })
            channel = agent._create_ai_chat_channel('Callback HTTP Test')
            session = env['ai.session'].sudo().create({
                'agent_id': agent.id,
                'channel_id': channel.id,
            })
            other_user = new_test_user(
                env,
                login='callback_confirmation_other',
                groups='base.group_user',
            )
            cls.agent_id = agent.id
            cls.channel_id = channel.id
            cls.session_id = session.id
            cls.other_user_id = other_user.id
        cls.agent = cls.env['ai.agent'].browse(cls.agent_id)
        cls.channel = cls.env['discuss.channel'].browse(cls.channel_id)
        cls.ai_session = cls.env['ai.session'].sudo().browse(cls.session_id)

    def _post_committed_prompt(self, body):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            return env['discuss.channel'].browse(self.channel_id).message_post(
                body=body, message_type='comment',
            ).id

    def _start_session_advance(self, message, **params):
        return self.url_open(
            '/ai/start_session_advance',
            json=self.build_rpc_payload({
                'channel_id': self.channel.id,
                'mail_message_id': message.id,
                **params,
            }),
        )

    def _post_completion_callback(self, payload):
        with self.allow_requests(all_requests=True):
            response = requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json=self.build_rpc_payload(payload),
                timeout=12,
            )
        self.assertNotIn('Cookie', response.request.headers)
        return response

    def _get_request(self, request_id):
        self.env.invalidate_all()
        return self.env['ai.session.request'].sudo().browse(request_id)

    def _create_committed_confirmation(self, label='HTTP Confirmed Contact'):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            channel = env['ai.agent'].browse(self.agent_id)._create_ai_chat_channel(label)
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
            })
            tool = env.ref('ai.ir_actions_server_create_records')
            session.state = {'available_tools': [tool.id]}
            message = channel.message_post(body=label, message_type='comment')
            company_ids = env.companies.ids
            request = session.with_context(
                active_company_ids=company_ids,
                allowed_company_ids=company_ids,
            )._prepare_session_request(
                message._convert_to_parts(),
                context_snapshot={
                    'active_company_ids': company_ids,
                    'allowed_company_ids': company_ids,
                },
            )
            session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'http-create-contact',
                        'name': tool.ai_tool_name,
                        'args': {
                            'explanation': f'Create {label}?',
                            'model_name': 'res.partner',
                            'preview_menu_id': False,
                            'values': [{
                                'field_values': [{
                                    'field': 'name',
                                    'value': label,
                                }],
                            }],
                        },
                    }],
                },
            })
            return {
                'channel_id': channel.id,
                'session_id': session.id,
                'request_id': request.id,
                'request_uuid': request.request_uuid,
                'resume_token': request.resume_token,
                'label': label,
            }

    def _resume_pending_confirmation(self, confirmation, **overrides):
        values = {
            'channel_id': confirmation['channel_id'],
            'request_uuid': confirmation['request_uuid'],
            'resume_token': confirmation['resume_token'],
            'response': {'value': UserInputResponse.CONFIRM_ONCE},
        }
        values.update(overrides)
        return self.url_open(
            '/ai/resume_pending_interaction',
            json=self.build_rpc_payload(values),
        )

    def test_callback_ignores_non_string_request_uuid(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value={'status': 'queued'},
        ):
            request_uuid = self._start_session_advance(message).json()['result']['request_uuid']

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
        ) as transport:
            response = self._post_completion_callback({'request_uuid': [request_uuid]})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['result'])
        self.assertNotIn('Set-Cookie', response.headers)
        transport.assert_not_called()

    def test_callback_fetch_failure_is_a_jsonrpc_error(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value={'status': 'queued'},
        ):
            acknowledgement = self._start_session_advance(message).json()['result']

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            side_effect=RuntimeError('IAP result fetch failed'),
        ):
            response = self._post_completion_callback({
                'request_uuid': acknowledgement['request_uuid'],
            })

        self.assertEqual(response.status_code, 200)
        self.assertIn('error', response.json())
        self.env.invalidate_all()
        session_request = self.env['ai.session.request'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(session_request.state, 'waiting_iap')

    def test_session_advance_accepts_numeric_prompt_button_id(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Do I have any customer in New Jersey?',
        ))
        prompt_button = self.env.ref('ai.ai_prompt_customer_new_jersey')

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value={'status': 'queued'},
        ) as submit:
            response = self._start_session_advance(
                message,
                ai_prompt_button_ref=prompt_button.id,
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.json())
        submitted_messages = submit.call_args.args[2]['messages']
        self.assertEqual(submit.call_args.kwargs['timeout'], IAP_TRANSPORT_TIMEOUT)
        submitted_text = ' '.join(
            part['content']['data']
            for submitted_message in submitted_messages
            for part in submitted_message['content']
            if part['type'] == 'text'
        )
        self.assertIn('Get a list of contacts in New Jersey', submitted_text)

    def test_real_session_advance_and_callback_use_the_iap_result(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value={'status': 'queued'},
        ) as submit:
            advance_response = self._start_session_advance(message)

        self.assertEqual(advance_response.status_code, 200)
        self.assertTrue(advance_response.headers['Content-Type'].startswith('application/json'))
        acknowledgement = advance_response.json()['result']
        self.assertTrue(acknowledgement['request_uuid'])
        self.assertEqual(acknowledgement['responseState'], 'running')
        submit.assert_called_once()
        self.assertIsInstance(submit.call_args.args[2], dict)
        self.assertEqual(submit.call_args.args[1], '1/submit_completions')

        self.env.invalidate_all()
        request = self.env['ai.session.request'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(len(request), 1)
        self.assertEqual(request.request_uuid, acknowledgement['request_uuid'])
        self.assertEqual(request.state, 'waiting_iap')

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
        ) as transport:
            unknown = self._post_completion_callback({
                'request_uuid': '00000000-0000-4000-8000-ffffffffffff',
            })
        self.assertEqual(unknown.status_code, 200)
        self.assertIsNone(unknown.json()['result'])
        self.assertNotIn('Set-Cookie', unknown.headers)
        transport.assert_not_called()

        event_count = len(self.ai_session.event_ids)
        message_count = len(self.channel.message_ids)
        iap_result = {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': assistant_text('Result fetched from IAP'),
        }
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value=iap_result,
        ) as transport:
            callback = self._post_completion_callback({
                'request_uuid': request.request_uuid,
            })
        self.assertEqual(callback.status_code, 200)
        self.assertIsNone(callback.json()['result'])
        self.assertNotIn('Set-Cookie', callback.headers)
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[1], '1/get_completion_result')
        self.assertEqual(transport.call_args.kwargs['timeout'], IAP_TRANSPORT_TIMEOUT)
        self.env.invalidate_all()
        self.assertEqual(request.state, 'done')
        self.assertEqual(len(self.ai_session.event_ids), event_count + 1)
        self.assertEqual(len(self.channel.message_ids), message_count + 1)
        self.assertIn('Result fetched from IAP', self.channel.message_ids[0].body)

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
        ) as transport:
            replay = self._post_completion_callback({'request_uuid': request.request_uuid})
        self.assertEqual(replay.status_code, 200)
        self.assertIsNone(replay.json()['result'])
        self.assertNotIn('Set-Cookie', replay.headers)
        transport.assert_not_called()
        self.env.invalidate_all()
        self.assertEqual(len(self.ai_session.event_ids), event_count + 1)
        self.assertEqual(len(self.channel.message_ids), message_count + 1)

    def test_callback_fetch_uses_originating_company_iap_account(self):
        self.authenticate('admin', 'admin')
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            origin_company = env['res.company'].create({
                'name': 'Callback Origin Company',
            })
            env.user.write({
                'company_ids': [Command.link(origin_company.id)],
            })
            service = env['iap.service'].search([
                ('technical_name', '=', 'odoo_ai'),
            ], limit=1)
            default_token = 'callback-default-company-token'
            origin_token = 'callback-origin-company-token'
            env['iap.account'].sudo().create({
                'service_id': service.id,
                'account_token': default_token,
                'company_ids': [Command.set(env.company.ids)],
            })
            env['iap.account'].sudo().create({
                'service_id': service.id,
                'account_token': origin_token,
                'company_ids': [Command.set(origin_company.ids)],
            })

            context = {
                'allowed_company_ids': origin_company.ids,
                'active_company_ids': origin_company.ids,
            }
            env = api.Environment(cr, env.uid, context)
            channel = env['ai.agent'].browse(self.agent_id)._create_ai_chat_channel(
                'Callback Origin Company Test',
            )
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
            })
            message = channel.message_post(body='Hi', message_type='comment')
            request = session._prepare_session_request(
                message._convert_to_parts(),
                context_snapshot=context,
            )
            request._transition('waiting_iap')
            request_uuid = request.request_uuid

        result = {
            'request_uuid': request_uuid,
            'status': 'success',
            'result': assistant_text('Origin company callback result'),
        }
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value=result,
        ) as transport:
            response = self._post_completion_callback({'request_uuid': request_uuid})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()['result'])
        transport.assert_called_once()
        connection = transport.call_args.args[0]
        self.assertEqual(connection['account_token'], origin_token)
        self.assertNotEqual(connection['account_token'], default_token)

    def test_confirmation_resume_executes_once_then_submits_followup(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation()
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value={'status': 'queued'},
        ) as submit:
            response = self._resume_pending_confirmation(confirmation)

        self.assertEqual(response.status_code, 200)
        acknowledgement = response.json()['result']
        self.assertEqual(acknowledgement['responseState'], 'running')
        self.assertNotEqual(
            acknowledgement['request_uuid'], confirmation['request_uuid'],
        )
        submit.assert_called_once()
        self.env.invalidate_all()
        request = self._get_request(confirmation['request_id'])
        self.assertEqual(request.state, 'done')
        self.assertFalse(request.resume_token)
        next_request = self.env['ai.session.request'].sudo().search([
            ('session_id', '=', request.session_id.id),
        ], order='id desc', limit=1)
        self.assertEqual(next_request.state, 'waiting_iap')
        self.assertEqual(next_request.request_uuid, acknowledgement['request_uuid'])
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', confirmation['label']),
        ]), 1)

    def test_confirmation_resume_captures_fresh_browser_context(self):
        self.authenticate('admin', 'admin')
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            resumed_company = env['res.company'].create({
                'name': 'Callback Resume Company',
            })
            env.user.company_ids = [Command.link(resumed_company.id)]
            resumed_company_id = resumed_company.id

        confirmation = self._create_committed_confirmation(
            'HTTP Fresh Context Contact',
        )
        original_request = self._get_request(confirmation['request_id'])
        original_snapshot = dict(original_request.context_snapshot)
        current_view_info = {'marker': 'fresh-browser-view'}
        original_cids = self.opener.cookies.get('cids')
        self.opener.cookies['cids'] = str(resumed_company_id)
        try:
            with patch(
                'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
                return_value={'status': 'queued'},
            ):
                response = self._resume_pending_confirmation(
                    confirmation,
                    current_view_info=current_view_info,
                )
        finally:
            if original_cids is None:
                self.opener.cookies.pop('cids', None)
            else:
                self.opener.cookies['cids'] = original_cids

        self.assertEqual(response.status_code, 200)
        acknowledgement = response.json()['result']
        self.env.invalidate_all()
        original_request = self._get_request(confirmation['request_id'])
        next_request = self.env['ai.session.request'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(original_request.context_snapshot, original_snapshot)
        self.assertEqual(
            next_request.context_snapshot['current_view_info'],
            current_view_info,
        )
        self.assertEqual(
            next_request.context_snapshot['active_company_ids'],
            [resumed_company_id],
        )
        self.assertIn('fresh-browser-view', str(next_request.payload['messages']))

        duplicate = self._resume_pending_confirmation(confirmation)

        self.assertIn('error', duplicate.json())
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', confirmation['label']),
        ]), 1)

    def test_confirmation_lock_contention_fails_before_tool_execution(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation(
            'HTTP Locked Confirmation Contact',
        )

        with patch.object(
            self.registry['ai.session'],
            'lock_for_update',
            side_effect=LockError('fixture lock contention'),
        ):
            response = self._resume_pending_confirmation(confirmation)

        self.assertIn('error', response.json())
        self.env.invalidate_all()
        request = self._get_request(confirmation['request_id'])
        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(request.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_confirmation_resume_rejects_wrong_token_choice_and_channel(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP Rejected Contact')
        another = self._create_committed_confirmation('HTTP Other Contact')

        wrong_token = self._resume_pending_confirmation(
            confirmation, resume_token='not-the-resume-token',
        )
        wrong_choice = self._resume_pending_confirmation(
            confirmation, response={'value': 'invented-confirmation-choice'},
        )
        wrong_channel = self._resume_pending_confirmation(
            confirmation, channel_id=another['channel_id'],
        )

        self.assertIn('error', wrong_token.json())
        self.assertIn('error', wrong_choice.json())
        self.assertIn('error', wrong_channel.json())
        self.env.invalidate_all()
        request = self._get_request(confirmation['request_id'])
        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(request.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_confirmation_resume_rejects_another_channel_member(self):
        confirmation = self._create_committed_confirmation(
            'HTTP Foreign Actor Contact',
        )
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.uid, {})
            env['discuss.channel'].browse(
                confirmation['channel_id'],
            )._add_members(users=env['res.users'].browse(self.other_user_id))

        self.authenticate(
            'callback_confirmation_other',
            'callback_confirmation_other',
        )
        response = self._resume_pending_confirmation(confirmation)

        self.assertIn('error', response.json())
        self.env.invalidate_all()
        request = self._get_request(confirmation['request_id'])
        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(request.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_confirmation_decline_settles_without_submission_or_mutation(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP Declined Contact')
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
        ) as transport:
            response = self._resume_pending_confirmation(
                confirmation,
                response={'value': UserInputResponse.DECLINE},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['responseState'], 'idle')
        transport.assert_not_called()
        self.env.invalidate_all()
        request = self._get_request(confirmation['request_id'])
        self.assertEqual(request.state, 'done')
        self.assertFalse(request.session_id.pending_tool_call)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_submission_locks_request_before_iap_call(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(
            self._post_committed_prompt('Observe submission locks')
        )
        events = []
        request_model = self.env.registry['ai.session.request']
        lock_request = request_model.lock_for_update

        def observe_request_lock(request, *args, **kwargs):
            events.append(('request_lock', request.env.uid, request.env.su))
            return lock_request(request, *args, **kwargs)

        def observe_submit(*_args, **_kwargs):
            events.append(('submit',))
            return {'status': 'queued'}

        with (
            patch.object(
                request_model, 'lock_for_update', autospec=True,
                side_effect=observe_request_lock,
            ),
            patch(
                'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
                side_effect=observe_submit,
            ),
        ):
            advance_response = self._start_session_advance(message)

        self.assertEqual(advance_response.status_code, 200)
        submit_index = [event[0] for event in events].index('submit')
        self.assertEqual(
            [event[0] for event in events[submit_index - 1:submit_index + 1]],
            ['request_lock', 'submit'],
        )
        self.assertEqual(
            events[submit_index - 1][1:],
            (self.env.ref('base.user_admin').id, True),
        )
