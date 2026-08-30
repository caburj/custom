# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

import requests

from odoo import api, Command
from odoo.exceptions import LockError, MissingError
from odoo.tests import HttpCase, new_test_user, tagged

from odoo.addons.ai.controllers.thread import AIThreadController, IAP_TRANSPORT_TIMEOUT
from odoo.addons.ai.utils.ai_utils import UserInputResponse


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
    }


def queue_submitted_request(_connection, _route, payload, **_kwargs):
    return {
        'request_uuid': payload['request_uuid'],
        'status': 'queued',
    }


@tagged('post_install', '-at_install')
class TestAISessionLoopHttp(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with cls.registry.cursor() as cr:
            env = api.Environment(cr, cls.env.uid, {})
            agent = env['ai.agent'].create({
                'name': 'Callback HTTP Test Agent',
                'system_prompt': 'Answer plainly.',
            })
            agent.skill_ids = env['ai.skill'].create({
                'name': 'Callback HTTP Business Records',
                'instructions': 'Create and update test contacts when requested.',
                'tool_ids': [Command.set([
                    env.ref('ai.ir_actions_server_create_records').id,
                    env.ref('ai.ir_actions_server_update_records').id,
                ])],
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

    def _get_session(self, session_id):
        self.env.invalidate_all()
        return self.env['ai.session'].sudo().browse(session_id)

    def _create_committed_prepared_session(self, label):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.env.ref('base.user_admin').id, {})
            channel = env['ai.agent'].browse(
                self.agent_id,
            )._create_ai_chat_channel(label)
            session = env['ai.session'].sudo().create({
                'agent_id': self.agent_id,
                'channel_id': channel.id,
            })
            message = channel.message_post(body=label, message_type='comment')
            session._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot={
                    'allowed_company_ids': env.companies.ids,
                    'active_company_ids': env.companies.ids,
                },
            )
            return {
                'session_id': session.id,
                'request_uuid': session.request_uuid,
                'request_payload': session.request_payload,
                'event_count': len(session.event_ids),
            }

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
            session = session.with_context(
                active_company_ids=company_ids,
                allowed_company_ids=company_ids,
            )._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot={
                    'active_company_ids': company_ids,
                    'allowed_company_ids': company_ids,
                },
            )
            request_uuid = session.request_uuid
            session._apply_iap_result(request_uuid, {
                'request_uuid': request_uuid,
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
                'request_uuid': request_uuid,
                'resume_token': session.resume_token,
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

    def test_website_sale_context_reaches_callback_pricing_consumer(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Show me products',
        ))
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=queue_submitted_request,
        ):
            response = self._start_session_advance(message)

        self.assertEqual(response.status_code, 200)
        context = self._get_session(self.session_id).request_context
        self.assertTrue(context['website_id'])
        self.assertIn('pricelist_id', context)
        self.assertIn('fiscal_position_id', context)

        product_model = self.env['product.template'].with_context(**context)
        pricelist, fiscal_position = product_model._get_website_context()
        self.assertEqual(product_model.env.website.id, context['website_id'])
        self.assertEqual(pricelist.id, context['pricelist_id'])
        self.assertEqual(fiscal_position.id, context['fiscal_position_id'])

    def test_callback_fetch_failure_is_a_jsonrpc_error(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=queue_submitted_request,
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
        session = self.env['ai.session'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'submitted')

    def test_session_advance_accepts_numeric_prompt_button_id(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt(
            'Do I have any customer in New Jersey?',
        ))
        prompt_button = self.env.ref('ai.ai_prompt_customer_new_jersey')

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=queue_submitted_request,
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
            part['text']
            for submitted_message in submitted_messages
            for part in submitted_message['content']
            if part['type'] == 'text'
        )
        self.assertIn('Get a list of contacts in New Jersey', submitted_text)

    def test_real_session_advance_and_callback_use_the_iap_result(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(self._post_committed_prompt('Hi'))

        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=queue_submitted_request,
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
        session = self.env['ai.session'].sudo().search([
            ('request_uuid', '=', acknowledgement['request_uuid']),
        ])
        self.assertEqual(len(session), 1)
        request_uuid = acknowledgement['request_uuid']
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_phase, 'submitted')
        self.assertEqual(session.loop_state, 'waiting_model')

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
            'request_uuid': request_uuid,
            'status': 'success',
            'result': assistant_text('Result fetched from IAP'),
        }
        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
            return_value=iap_result,
        ) as transport:
            callback = self._post_completion_callback({
                'request_uuid': request_uuid,
            })
        self.assertEqual(callback.status_code, 200)
        self.assertIsNone(callback.json()['result'])
        self.assertNotIn('Set-Cookie', callback.headers)
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args[1], '1/get_completion_result')
        self.assertEqual(transport.call_args.kwargs['timeout'], IAP_TRANSPORT_TIMEOUT)
        self.env.invalidate_all()
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_phase)
        self.assertFalse(session.request_uuid)
        self.assertEqual(len(self.ai_session.event_ids), event_count + 1)
        self.assertEqual(len(self.channel.message_ids), message_count + 1)
        self.assertIn('Result fetched from IAP', self.channel.message_ids[0].body)

        with patch(
            'odoo.addons.ai.controllers.thread.call_odoo_ai_transport',
        ) as transport:
            replay = self._post_completion_callback({'request_uuid': request_uuid})
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
            session._prepare_model_request(
                message._convert_to_parts(),
                context_snapshot=context,
            )
            session.request_phase = 'submitted'
            request_uuid = session.request_uuid

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
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            side_effect=queue_submitted_request,
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
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'submitted')
        self.assertFalse(session.resume_token)
        self.assertEqual(session.request_round, 2)
        self.assertEqual(session.request_uuid, acknowledgement['request_uuid'])
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
        session = self._get_session(confirmation['session_id'])
        original_snapshot = dict(session.request_context)
        current_view_info = {'marker': 'fresh-browser-view'}
        original_cids = self.opener.cookies.get('cids')
        self.opener.cookies['cids'] = str(resumed_company_id)
        try:
            with patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=queue_submitted_request,
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
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.request_uuid, acknowledgement['request_uuid'])
        self.assertNotEqual(session.request_context, original_snapshot)
        self.assertEqual(
            session.request_context['current_view_info'],
            current_view_info,
        )
        self.assertEqual(
            session.request_context['active_company_ids'],
            [resumed_company_id],
        )
        self.assertIn('fresh-browser-view', str(session.request_payload['messages']))

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
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, confirmation['resume_token'])
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
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, confirmation['resume_token'])
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
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, confirmation['resume_token'])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_confirmation_decline_settles_without_submission_or_mutation(self):
        self.authenticate('admin', 'admin')
        confirmation = self._create_committed_confirmation('HTTP Declined Contact')
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
        ) as transport:
            response = self._resume_pending_confirmation(
                confirmation,
                response={'value': UserInputResponse.DECLINE},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result']['responseState'], 'idle')
        transport.assert_not_called()
        self.env.invalidate_all()
        session = self._get_session(confirmation['session_id'])
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertFalse(session.pending_tool_call)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', confirmation['label']),
        ]))

    def test_submission_rejects_a_stale_expected_uuid_before_iap_call(self):
        prepared = self._create_committed_prepared_session(
            'Exact UUID submission fence',
        )

        with (
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            ) as transport,
            self.assertRaises(MissingError),
        ):
            AIThreadController()._submit_prepared_request(
                self.env.cr.dbname,
                prepared['session_id'],
                '00000000-0000-4000-8000-ffffffffffff',
            )

        transport.assert_not_called()
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertEqual(session.request_uuid, prepared['request_uuid'])

    def test_submission_marks_session_submitted_after_transport_returns(self):
        prepared = self._create_committed_prepared_session(
            'Trust successful transport',
        )
        with patch(
            'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
            return_value=None,
        ):
            acknowledgement = AIThreadController()._submit_prepared_request(
                self.env.cr.dbname,
                prepared['session_id'],
                prepared['request_uuid'],
            )

        self.assertEqual(acknowledgement, {
            'request_uuid': prepared['request_uuid'],
            'responseState': 'running',
        })
        session = self._get_session(prepared['session_id'])
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'submitted')
        self.assertEqual(session.request_uuid, prepared['request_uuid'])

    def test_submission_locks_session_before_iap_call(self):
        self.authenticate('admin', 'admin')
        message = self.env['mail.message'].browse(
            self._post_committed_prompt('Observe submission locks')
        )
        events = []
        session_model = self.env.registry['ai.session']
        lock_session = session_model.lock_for_update

        def observe_session_lock(session, *args, **kwargs):
            events.append(('session_lock', session.env.uid, session.env.su))
            return lock_session(session, *args, **kwargs)

        def observe_submit(*args, **_kwargs):
            events.append(('submit',))
            return {
                'request_uuid': args[2]['request_uuid'],
                'status': 'queued',
            }

        with (
            patch.object(
                session_model, 'lock_for_update', autospec=True,
                side_effect=observe_session_lock,
            ),
            patch(
                'odoo.addons.ai.models.ai_session.call_odoo_ai_transport',
                side_effect=observe_submit,
            ),
        ):
            advance_response = self._start_session_advance(message)

        self.assertEqual(advance_response.status_code, 200)
        submit_index = [event[0] for event in events].index('submit')
        self.assertEqual(
            [event[0] for event in events[submit_index - 1:submit_index + 1]],
            ['session_lock', 'submit'],
        )
        self.assertEqual(
            events[submit_index - 1][1:],
            (self.env.ref('base.user_admin').id, True),
        )
