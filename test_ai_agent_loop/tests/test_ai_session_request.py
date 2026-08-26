# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import copy
from textwrap import dedent
from unittest.mock import patch

from odoo import Command
from odoo.tests import new_test_user, tagged, TransactionCase
from odoo.exceptions import AccessError, UserError

from odoo.addons.ai.controllers.thread import AIThreadController
from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_utils import call_odoo_ai_transport
from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.ai_website_sale.controllers.thread import AIWebsiteSaleThreadController
from odoo.addons.mail.tools.discuss import Store


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'content': {'data': text}}],
    }


@tagged('post_install', '-at_install')
class TestAISessionRequest(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Callback Test Agent',
            'system_prompt': 'Answer plainly.',
        })
        cls.channel = cls.agent._create_ai_chat_channel('Callback Test')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })

    def _post_prompt(self, body='Hi'):
        return self.channel.message_post(body=body, message_type='comment')

    def _prepare_session_request(self, message=None):
        message = message or self._post_prompt()
        context_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
        }
        session = self.session.with_context(**context_snapshot)
        return session, session._prepare_session_request(
            message._convert_to_parts(),
            context_snapshot=context_snapshot,
        )

    def _create_test_tool(self, name, code, thinking_text='Checking records'):
        return self.env['ir.actions.server'].create({
            'name': name,
            'ai_tool_name': name,
            'ai_tool_thinking_text': thinking_text,
            'ai_tool_description': 'Callback checkpoint fixture tool.',
            'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code',
            'use_in_ai': True,
            'code': code,
        })

    def _apply_iap_tool_call(self, session, request, tool, call_id, args):
        return session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [{
                    'type': 'tool_call',
                    'call_id': call_id,
                    'name': tool.ai_tool_name,
                    'args': args,
                }],
            },
        })

    def _create_partner_args(self, name):
        return {
            'explanation': f'Create contact {name}?',
            'model_name': 'res.partner',
            'preview_menu_id': False,
            'values': [{
                'field_values': [{
                    'field': 'name',
                    'value': name,
                }],
            }],
        }

    def _prepare_question(self, choices, *, multi_select=False, allow_free_text=False):
        tool = self.env.ref('ai.ir_actions_server_ask_user_question')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        waiting = self._apply_iap_tool_call(
            session,
            request,
            tool,
            'callback-question',
            {
                'question': 'Which option should be used?',
                'choices': choices,
                'multi_select': multi_select,
                'allow_free_text': allow_free_text,
            },
        )
        return session, request, waiting

    def test_prepare_persists_one_immutable_model_round(self):
        message = self._post_prompt()
        _session, request = self._prepare_session_request(message)
        payload_before = copy.deepcopy(request.payload)

        self.assertEqual(request.state, 'prepared')
        self.assertEqual(request.round_no, 1)
        self.assertEqual(request.payload, payload_before)
        self.assertEqual(len(self.session.event_ids), 1)
        self.assertNotIn('<odoo_current_context>', str(self.session.event_ids.metadata))
        self.assertIn('<odoo_current_context>', str(request.payload['messages']))
        with self.assertRaises(UserError):
            request.write({'payload': {}})

    def test_request_data_bootstrap_supports_id_and_uuid(self):
        _session, request = self._prepare_session_request()
        controller = AIThreadController()
        expected = {
            'id': request.id,
            'user_id': request.user_id.id,
            'guest_id': False,
            'context': copy.deepcopy(request.context_snapshot),
        }

        request_data_by_id = controller._get_session_request_data(
            self.env.cr, request_id=request.id,
        )
        request_data_by_uuid = controller._get_session_request_data(
            self.env.cr, request_uuid=request.request_uuid,
        )

        self.assertEqual(request_data_by_id, expected)
        self.assertEqual(request_data_by_uuid, expected)
        self.assertEqual(set(request_data_by_id), {
            'id', 'user_id', 'guest_id', 'context',
        })
        request_data_by_id['context']['allowed_company_ids'].append(-1)
        self.assertNotIn(-1, request.context_snapshot['allowed_company_ids'])
        self.assertIsNone(controller._get_session_request_data(
            self.env.cr, request_id=0,
        ))

    def test_plain_result_applies_once_after_submission(self):
        session, request = self._prepare_session_request()
        request._transition('waiting_iap')
        session._publish_response_state()

        self.assertEqual(request.state, 'waiting_iap')
        event_count = len(session.event_ids)
        message_count = len(session.channel_id.message_ids)

        result = {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': assistant_text('Hello from the callback'),
        }
        outcome = session._apply_iap_result(request, result)
        counts_after_first = (
            len(session.event_ids),
            len(session.channel_id.message_ids),
        )
        replay = session._apply_iap_result(request, result)

        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(replay['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertEqual(len(session.event_ids), event_count + 1)
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertEqual(counts_after_first, (
            len(session.event_ids), len(session.channel_id.message_ids),
        ))
        self.assertIn('Hello from the callback', session.channel_id.message_ids[0].body)

    def test_result_handler_rejects_submission_payload(self):
        session, request = self._prepare_session_request()
        result = session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'queued',
        })

        self.assertEqual(result['responseState'], 'idle')
        self.assertEqual(request.state, 'failed')

    def test_inline_data_only_success_posts_one_visible_attachment(self):
        session, request = self._prepare_session_request()
        message_count = len(session.channel_id.message_ids)
        result = {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [{
                    'type': 'inline_data',
                    'content': {
                        'data': base64.b64encode(b'fixture image').decode(),
                        'mimetype': 'image/png',
                    },
                }],
            },
        }

        outcome = session._apply_iap_result(request, result)

        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertEqual(len(session.channel_id.message_ids[0].attachment_ids), 1)

    def test_server_tool_result_prepares_one_followup_round(self):
        self.env['res.partner'].create({'name': 'Callback Tool Contact'})
        tool = self._create_test_tool(
            'ai_tool_callback_count_contacts',
            "ai['result'] = len(env['res.partner'].search([('name', '=', 'Callback Tool Contact')]))",
        )
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        output_message = {
            'role': 'assistant',
            'content': [{
                'type': 'tool_call',
                'call_id': 'count-contacts',
                'name': tool.ai_tool_name,
                'args': {},
            }],
        }

        outcome = session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': output_message,
        })

        self.assertEqual(outcome['responseState'], 'running')
        self.assertEqual(request.state, 'done')
        next_request = self.env['ai.session.request'].sudo().browse(
            outcome['next_request_id']
        )
        self.assertEqual(next_request.state, 'prepared')
        self.assertEqual(next_request.round_no, 2)
        self.assertEqual(
            [message['role'] for message in next_request.payload['messages']],
            ['user', 'assistant', 'user'],
        )
        tool_result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertTrue(tool_result['success'])
        self.assertEqual(tool_result['tool_call']['call_id'], 'count-contacts')
        self.assertEqual(tool_result['result'][0]['content']['data'], '1')

        session._apply_iap_result(next_request, {
            'request_uuid': next_request.request_uuid,
            'status': 'success',
            'result': assistant_text('You have one callback tool contact.'),
        })

        self.assertEqual(next_request.state, 'done')
        self.assertIn(
            'You have one callback tool contact.',
            session.channel_id.message_ids[0].body,
        )

    def test_oneway_client_tool_is_published_with_the_tool_round(self):
        tool = self._create_test_tool(
            'ai_tool_callback_open_customers',
            """ai['result'] = {
                'result': 'Opened customers',
                'client_tool': {
                    'name': 'show_view',
                    'oneway': True,
                    'params': {
                        'action': {
                            'type': 'ir.actions.act_window',
                            'name': 'Customers',
                            'res_model': 'res.partner',
                            'views': [[False, 'list']],
                        },
                        'menuId': False,
                    },
                },
            }""",
            thinking_text='Opening customers',
        )
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()

        with patch.object(
            self.env.registry['discuss.channel'], '_bus_send', autospec=True,
        ) as bus_send:
            outcome = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': {
                    'role': 'assistant',
                    'content': [{
                        'type': 'tool_call',
                        'call_id': 'open-customers',
                        'name': tool.ai_tool_name,
                        'args': {},
                    }],
                },
            })

        client_tool_calls = [
            call for call in bus_send.call_args_list
            if call.args[1] == 'ai.session/client_tools'
        ]
        self.assertEqual(len(client_tool_calls), 1)
        payload = client_tool_calls[0].args[2]
        self.assertEqual(payload['channel_id'], session.channel_id.id)
        self.assertEqual(
            [command['name'] for command in payload['commands']],
            ['update_thinking', 'show_view'],
        )
        self.assertEqual(
            payload['commands'][1]['params']['action']['res_model'],
            'res.partner',
        )
        self.assertEqual(request.state, 'done')
        self.assertTrue(outcome['next_request_id'])

    def test_single_choice_question_survives_reload_and_resumes_once(self):
        session, request, waiting = self._prepare_question(['Draft', 'Send'])

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(request.state, 'waiting_input')
        resume_token = request.resume_token
        self.env.invalidate_all()
        session = self.env['ai.session'].sudo().browse(session.id)
        request = self.env['ai.session.request'].sudo().browse(request.id)
        stored_session = Store().add(
            session, '_store_session_fields',
        )._build_result()['ai.session'][0]
        self.assertEqual(stored_session['userInputRequest']['requestUuid'], request.request_uuid)
        self.assertEqual(stored_session['userInputRequest']['resumeToken'], resume_token)
        invalid_responses = (
            {'values': ['Invented']},
            {'values': 'Draft'},
            {'values': []},
            {'values': ['Draft', 'Draft']},
            {'values': ['Draft'], 'skip': True},
            {'skip': 1},
        )
        for response in invalid_responses:
            with self.subTest(response=response), self.assertRaises(UserError):
                session._resume_pending_interaction(request, resume_token, response)
        self.assertEqual(request.resume_token, resume_token)

        resumed = session._resume_pending_interaction(
            request, resume_token, {'values': ['Draft']},
        )

        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertEqual(result['tool_call']['call_id'], 'callback-question')
        self.assertIn('USER ANSWER: Draft', str(result['result']))
        self.assertIn('Draft', session.channel_id.message_ids[0].body)
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 2)
        with self.assertRaises(UserError):
            session._resume_pending_interaction(
                request, resume_token, {'values': ['Draft']},
            )
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 2)

    def test_free_text_question_preserves_the_answer(self):
        session, request, _waiting = self._prepare_question(
            ['Brussels', 'Ghent'], allow_free_text=True,
        )

        resumed = session._resume_pending_interaction(
            request, request.resume_token, {'values': ['Antwerp']},
        )

        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertIn('USER ANSWER: Antwerp', str(result['result']))
        self.assertIn('Antwerp', session.channel_id.message_ids[0].body)

    def test_multi_select_question_uses_persisted_choice_order(self):
        session, request, _waiting = self._prepare_question(
            ['Red', 'Green', 'Blue'], multi_select=True,
        )

        resumed = session._resume_pending_interaction(
            request, request.resume_token, {'values': ['Blue', 'Red']},
        )

        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertIn('USER ANSWER: Red,Blue', str(result['result']))
        self.assertIn('Red, Blue', session.channel_id.message_ids[0].body)

    def test_skipping_question_balances_remaining_batch_without_followup(self):
        first_tool = self._create_test_tool(
            'callback_completed_before_question',
            "ai['result'] = 'Completed before the question'",
        )
        question_tool = self.env.ref('ai.ir_actions_server_ask_user_question')
        create_tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {
            'available_tools': [first_tool.id, question_tool.id, create_tool.id],
        }
        session, request = self._prepare_session_request()
        session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [
                    {
                        'type': 'tool_call',
                        'call_id': 'completed-before-question',
                        'name': first_tool.ai_tool_name,
                        'args': {},
                    },
                    {
                        'type': 'tool_call',
                        'call_id': 'skipped-question',
                        'name': question_tool.ai_tool_name,
                        'args': {
                            'question': 'Continue?',
                            'choices': ['Continue', 'Stop'],
                            'multi_select': False,
                            'allow_free_text': False,
                        },
                    },
                    {
                        'type': 'tool_call',
                        'call_id': 'create-after-question',
                        'name': create_tool.ai_tool_name,
                        'args': self._create_partner_args('Must Not Be Created'),
                    },
                ],
            },
        })

        resume_token = request.resume_token
        with self.assertRaises(UserError):
            session._resume_pending_interaction(request, resume_token, {'skip': 1})
        self.assertEqual(request.resume_token, resume_token)

        skipped = session._resume_pending_interaction(
            request, request.resume_token, {'skip': True},
        )

        self.assertEqual(skipped['responseState'], 'idle')
        self.assertNotIn('next_request_id', skipped)
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        results = [
            part['tool_results']
            for part in session.event_ids.sorted('id')[-1].metadata['content']
        ]
        self.assertEqual(
            [result['tool_call']['call_id'] for result in results],
            ['completed-before-question', 'skipped-question', 'create-after-question'],
        )
        self.assertEqual([result['success'] for result in results], [True, False, False])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Must Not Be Created'),
        ]))
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 1)
        with self.assertRaises(UserError):
            session._resume_pending_interaction(request, resume_token, {'skip': True})

    def test_result_client_tool_resumes_truthy_falsy_and_error_without_rerun(self):
        tool = self._create_test_tool(
            'callback_result_client_tool',
            dedent("""
                ai['state']['client_tool_runs'] = (
                    ai['state'].get('client_tool_runs', 0) + 1
                )
                ai['result'] = {
                    'client_tool': {
                        'name': 'callback_get_client_value',
                        'params': {'key': 'answer'},
                    },
                }
            """),
        )
        cases = (
            ('truthy', {'result': {'client_value': 42}}, True, '{"client_value": 42}'),
            ('false', {'result': False}, True, 'false'),
            ('null', {'result': None}, True, None),
            ('empty', {'result': ''}, True, ''),
            ('error', {'error': 'Client tool failed'}, False, 'Error: Client tool failed'),
        )
        for label, response, success, expected_data in cases:
            with self.subTest(label=label):
                channel = self.agent._create_ai_chat_channel(f'Client tool {label}')
                session = self.env['ai.session'].sudo().create({
                    'agent_id': self.agent.id,
                    'channel_id': channel.id,
                    'state': {'available_tools': [tool.id]},
                })
                message = channel.message_post(body='Run client tool', message_type='comment')
                request = session._prepare_session_request(
                    message._convert_to_parts(),
                    context_snapshot={
                        'active_company_ids': self.env.companies.ids,
                        'allowed_company_ids': self.env.companies.ids,
                    },
                )

                waiting = self._apply_iap_tool_call(
                    session, request, tool, f'client-tool-{label}', {},
                )

                self.assertEqual(waiting['responseState'], 'waiting_client')
                self.assertEqual(request.state, 'waiting_input')
                self.assertEqual(session.state['client_tool_runs'], 1)
                self.assertEqual(
                    set(session.pending_tool_call['client_tool']), {'name', 'params'},
                )
                stored_session = Store().add(
                    session, '_store_session_fields',
                )._build_result()['ai.session'][0]
                self.assertEqual(stored_session['clientToolRequest'], {
                    'name': 'callback_get_client_value',
                    'params': {'key': 'answer'},
                    'requestUuid': request.request_uuid,
                    'resumeToken': request.resume_token,
                })
                resume_token = request.resume_token
                if label == 'truthy':
                    for invalid_response in (
                        {},
                        {'error': ''},
                        {'error': False},
                        {'result': 42, 'error': 'mixed response'},
                        {'skip': True},
                    ):
                        with (
                            self.subTest(invalid_response=invalid_response),
                            self.assertRaises(UserError),
                        ):
                            session._resume_pending_interaction(
                                request, resume_token, invalid_response,
                            )
                    self.assertEqual(request.resume_token, resume_token)

                resumed = session._resume_pending_interaction(
                    request, resume_token, response,
                )

                self.assertEqual(resumed['responseState'], 'running')
                self.assertEqual(session.state['client_tool_runs'], 1)
                next_request = self.env['ai.session.request'].sudo().browse(
                    resumed['next_request_id']
                )
                result = next_request.payload['messages'][-1]['content'][0]['tool_results']
                self.assertEqual(result['success'], success)
                self.assertEqual(result['result'][0]['content']['data'], expected_data)
                self.assertEqual(self.env['ai.session.request'].sudo().search_count([
                    ('session_id', '=', session.id),
                ]), 2)
                with self.assertRaises(UserError):
                    session._resume_pending_interaction(request, resume_token, response)
                self.assertEqual(session.state['client_tool_runs'], 1)
                self.assertEqual(self.env['ai.session.request'].sudo().search_count([
                    ('session_id', '=', session.id),
                ]), 2)

    def test_create_tool_waits_durably_then_confirmation_executes_once(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()

        waiting = self._apply_iap_tool_call(
            session, request, tool, 'create-contact',
            self._create_partner_args('Callback Confirmed Contact'),
        )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(request.state, 'waiting_input')
        self.assertTrue(request.resume_token)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Callback Confirmed Contact'),
        ]))
        self.assertEqual(session.pending_tool_call['request_id'], request.id)
        self.assertEqual(
            session.pending_tool_call['user_input_request']['type'],
            'confirmation',
        )
        resume_token = request.resume_token

        resumed = session._resume_pending_interaction(
            request, resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(request.state, 'done')
        self.assertFalse(request.resume_token)
        self.assertFalse(session.pending_tool_call)
        partners = self.env['res.partner'].search([
            ('name', '=', 'Callback Confirmed Contact'),
        ])
        self.assertEqual(len(partners), 1)
        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        tool_result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertEqual(tool_result['tool_call']['call_id'], 'create-contact')
        self.assertTrue(tool_result['success'])

        with self.assertRaises(UserError):
            session._resume_pending_interaction(
                request, resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
            )
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', 'Callback Confirmed Contact'),
        ]), 1)

    def test_confirmation_resume_rolls_back_effect_and_ledger_together(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        partner_name = 'Callback Rolled Back Contact'
        self._apply_iap_tool_call(
            session, request, tool, 'rollback-create',
            self._create_partner_args(partner_name),
        )
        resume_token = request.resume_token
        pending_tool_call = copy.deepcopy(session.pending_tool_call)
        event_count = len(session.event_ids)
        message_count = len(session.channel_id.message_ids)

        with (
            patch.object(
                AiSession,
                '_prepare_session_request',
                side_effect=RuntimeError('fixture rollback after tool execution'),
            ),
            self.assertRaises(RuntimeError),
            self.env.cr.savepoint(),
        ):
            session._resume_pending_interaction(
                request, resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
            )

        self.env.invalidate_all()
        session = self.env['ai.session'].sudo().browse(session.id)
        request = self.env['ai.session.request'].sudo().browse(request.id)
        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(request.resume_token, resume_token)
        self.assertEqual(session.pending_tool_call, pending_tool_call)
        self.assertEqual(len(session.event_ids), event_count)
        self.assertEqual(len(session.channel_id.message_ids), message_count)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', partner_name),
        ]))

    def test_confirmation_then_question_rotates_token_and_preserves_order(self):
        create_tool = self.env.ref('ai.ir_actions_server_create_records')
        question_tool = self.env.ref('ai.ir_actions_server_ask_user_question')
        self.session.state = {
            'available_tools': [create_tool.id, question_tool.id],
        }
        session, request = self._prepare_session_request()
        partner_name = 'Callback Question Follow-up Contact'
        waiting = session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [
                    {
                        'type': 'tool_call',
                        'call_id': 'create-before-question',
                        'name': create_tool.ai_tool_name,
                        'args': self._create_partner_args(partner_name),
                    },
                    {
                        'type': 'tool_call',
                        'call_id': 'follow-up-question',
                        'name': question_tool.ai_tool_name,
                        'args': {
                            'question': 'Which follow-up should be used?',
                            'choices': ['First option', 'Second option'],
                            'multi_select': False,
                            'allow_free_text': True,
                        },
                    },
                ],
            },
        })
        self.assertEqual(waiting['responseState'], 'waiting_user')
        confirmation_token = request.resume_token
        event_count = len(session.event_ids)

        question_waiting = session._resume_pending_interaction(
            request,
            confirmation_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(question_waiting['responseState'], 'waiting_user')
        self.assertEqual(request.state, 'waiting_input')
        self.assertNotEqual(request.resume_token, confirmation_token)
        self.assertEqual(session.pending_tool_call['call_id'], 'follow-up-question')
        self.assertEqual(
            session.pending_tool_call['user_input_request']['type'], 'question',
        )
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(len(session.event_ids), event_count)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', partner_name),
        ]), 1)

        resumed = session._resume_pending_interaction(
            request, request.resume_token, {'values': ['First option']},
        )

        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(request.state, 'done')
        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        results = [
            part['tool_results']
            for part in next_request.payload['messages'][-1]['content']
        ]
        self.assertEqual(
            [result['tool_call']['call_id'] for result in results],
            ['create-before-question', 'follow-up-question'],
        )
        self.assertTrue(all(result['success'] for result in results))
        self.assertIn('USER ANSWER: First option', str(results[1]['result']))
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', partner_name),
        ]), 1)

    def test_standard_confirmation_contract_is_tool_agnostic(self):
        tool = self._create_test_tool(
            'callback_generic_confirmation',
            dedent("""
                if not ai['tool_request_confirmed']:
                    ai['user_input_request'] = {
                        'type': 'confirmation',
                        'body': 'Run the generic callback tool?',
                        'choices': [
                            {'label': 'Yes, do it', 'value': 'confirm_once'},
                            {
                                'label': 'Yes, always approve in this chat',
                                'value': 'auto_confirm',
                            },
                            {'label': 'No, skip it', 'value': 'decline'},
                        ],
                    }
                else:
                    ai['state']['generic_confirmation_runs'] = (
                        ai['state'].get('generic_confirmation_runs', 0) + 1
                    )
                    ai['result'] = 'Generic callback tool confirmed'
            """),
        )
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()

        waiting = self._apply_iap_tool_call(
            session, request, tool, 'generic-confirmation', {},
        )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(request.state, 'waiting_input')
        self.assertNotIn('generic_confirmation_runs', session.state)
        resume_token = request.resume_token

        resumed = session._resume_pending_interaction(
            request, resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(session.state['generic_confirmation_runs'], 1)
        next_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id']
        )
        tool_result = next_request.payload['messages'][-1]['content'][0]['tool_results']
        self.assertEqual(tool_result['tool_call']['name'], tool.ai_tool_name)
        self.assertTrue(tool_result['success'])

    def test_update_tool_uses_persisted_arguments_after_confirmation(self):
        partner = self.env['res.partner'].create({'name': 'Callback Before Update'})
        tool = self.env.ref('ai.ir_actions_server_update_records')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        args = {
            'explanation': 'Rename the callback contact?',
            'preview_menus': [],
            'updates': [{
                'model_name': 'res.partner',
                'domain': f"[('id', '=', {partner.id})]",
                'changes': [{
                    'field': 'name',
                    'value': 'Callback After Update',
                }],
            }],
        }

        self._apply_iap_tool_call(session, request, tool, 'update-contact', args)

        self.assertEqual(request.state, 'waiting_input')
        self.assertEqual(partner.name, 'Callback Before Update')
        pending_call = session._get_last_tool_calls()[0]
        self.assertEqual(pending_call['args'], args)

        resumed = session._resume_pending_interaction(
            request, request.resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['responseState'], 'running')
        self.assertEqual(partner.name, 'Callback After Update')
        self.assertEqual(request.state, 'done')

    def test_decline_balances_the_tool_call_without_mutating(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        self._apply_iap_tool_call(
            session, request, tool, 'declined-create',
            self._create_partner_args('Declined Callback Contact'),
        )

        declined = session._resume_pending_interaction(
            request, request.resume_token, {'value': UserInputResponse.DECLINE},
        )

        self.assertEqual(declined['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Declined Callback Contact'),
        ]))
        tool_result = session.event_ids.sorted('id')[-1].metadata['content'][0]['tool_results']
        self.assertFalse(tool_result['success'])

    def test_sequential_confirmations_rotate_tokens_and_preserve_result_order(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session, request = self._prepare_session_request()
        tool_calls = [
            {
                'type': 'tool_call',
                'call_id': call_id,
                'name': tool.ai_tool_name,
                'args': self._create_partner_args(name),
            }
            for call_id, name in (
                ('create-first', 'Callback First Contact'),
                ('create-second', 'Callback Second Contact'),
            )
        ]
        session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {'role': 'assistant', 'content': tool_calls},
        })
        first_token = request.resume_token
        event_count_before_resumes = len(session.event_ids)

        first_resume = session._resume_pending_interaction(
            request, first_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(first_resume['responseState'], 'waiting_user')
        self.assertEqual(request.state, 'waiting_input')
        self.assertNotEqual(request.resume_token, first_token)
        self.assertEqual(session.pending_tool_call['call_id'], 'create-second')
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(session.pending_tool_call['pending_results'][0]['tool_call']['call_id'], 'create-first')
        self.assertEqual(len(session.event_ids), event_count_before_resumes)
        with self.assertRaises(UserError):
            session._resume_pending_interaction(
                request, first_token, {'value': UserInputResponse.CONFIRM_ONCE},
            )

        second_resume = session._resume_pending_interaction(
            request, request.resume_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(second_resume['responseState'], 'running')
        next_request = self.env['ai.session.request'].sudo().browse(
            second_resume['next_request_id']
        )
        results = [
            part['tool_results']
            for part in next_request.payload['messages'][-1]['content']
        ]
        self.assertEqual(
            [result['tool_call']['call_id'] for result in results],
            ['create-first', 'create-second'],
        )
        self.assertEqual(len(session.event_ids), event_count_before_resumes + 1)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', 'in', ['Callback First Contact', 'Callback Second Contact']),
        ]), 2)

    def test_auto_confirm_executes_later_confirmation_without_waiting(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session, first_request = self._prepare_session_request()
        self._apply_iap_tool_call(
            session, first_request, tool, 'auto-first',
            self._create_partner_args('Callback Auto First'),
        )
        first_resume = session._resume_pending_interaction(
            first_request, first_request.resume_token,
            {'value': UserInputResponse.AUTO_CONFIRM},
        )
        second_request = self.env['ai.session.request'].sudo().browse(
            first_resume['next_request_id']
        )

        second_resume = self._apply_iap_tool_call(
            session, second_request, tool, 'auto-second',
            self._create_partner_args('Callback Auto Second'),
        )

        self.assertTrue(session.auto_confirm)
        self.assertEqual(second_request.state, 'done')
        self.assertEqual(second_resume['responseState'], 'running')
        self.assertFalse(session.pending_tool_call)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', 'in', ['Callback Auto First', 'Callback Auto Second']),
        ]), 2)

    def test_direct_response_remains_synchronous_and_has_no_ledger_row(self):
        request_count = self.env['ai.session.request'].sudo().search_count([])
        with patch.object(AiSession, '_get_completions', return_value={
            'status': 'success',
            'result': assistant_text('Direct'),
        }):
            result = self.env['ai.session']._get_direct_response(
                instructions='Answer.',
                message=[{'type': 'text', 'content': {'data': 'Hi'}}],
            )

        self.assertEqual(result, assistant_text('Direct')['content'])
        self.assertEqual(
            self.env['ai.session.request'].sudo().search_count([]), request_count,
        )

    def test_scalar_transport_copies_payload_before_adding_credentials(self):
        connection = {
            'endpoint': 'http://127.0.0.1:18070',
            'account_token': 'fixture-token',
            'dbuuid': 'fixture-database',
        }
        params = {'request_uuid': '00000000-0000-4000-8000-000000000001'}
        with patch(
            'odoo.addons.ai.utils.ai_utils.iap_tools.iap_jsonrpc',
            return_value={'status': 'queued'},
        ) as transport:
            response = call_odoo_ai_transport(
                connection, '1/submit_completions', params,
            )

        self.assertEqual(response, {'status': 'queued'})
        self.assertNotIn('account_token', params)
        self.assertNotIn('dbuuid', params)
        sent_params = transport.call_args.kwargs['params']
        self.assertEqual(sent_params['account_token'], 'fixture-token')
        self.assertEqual(sent_params['dbuuid'], 'fixture-database')

    def test_scalar_transport_keeps_empty_credentials_when_auth_is_requested(self):
        connection = {
            'endpoint': 'http://127.0.0.1:18070',
            'account_token': False,
            'dbuuid': False,
        }
        with patch(
            'odoo.addons.ai.utils.ai_utils.iap_tools.iap_jsonrpc',
            return_value={'status': 'queued'},
        ) as transport:
            call_odoo_ai_transport(connection, '1/submit_completions', {})

        sent_params = transport.call_args.kwargs['params']
        self.assertIn('account_token', sent_params)
        self.assertIn('dbuuid', sent_params)
        self.assertFalse(sent_params['account_token'])
        self.assertFalse(sent_params['dbuuid'])

    def test_base_session_request_context_snapshot_owns_only_generic_keys(self):
        company_ids = self.env.companies.ids
        context = {
            'allowed_company_ids': company_ids,
            'active_company_ids': company_ids,
            'current_view_info': {'view_type': 'list'},
            'HTTP_HOST': 'example.test',
            'lang': 'en_US',
            'tz': 'UTC',
            'website_id': 7,
            'pricelist_id': 11,
            'fiscal_position_id': 13,
            'unrelated_key': 'not persisted',
        }
        snapshot = AIThreadController()._get_session_request_context_snapshot(self.env, context)

        self.assertEqual(AIThreadController._session_request_context_keys, frozenset({
            'allowed_company_ids',
            'active_company_ids',
            'current_view_info',
            'HTTP_HOST',
            'lang',
            'tz',
        }))
        self.assertEqual(snapshot, {
            'allowed_company_ids': company_ids,
            'active_company_ids': company_ids,
            'current_view_info': {'view_type': 'list'},
            'HTTP_HOST': 'example.test',
            'lang': 'en_US',
            'tz': 'UTC',
        })

    def test_website_sale_session_request_context_accepts_absent_optional_keys(self):
        snapshot = AIWebsiteSaleThreadController()._get_session_request_context_snapshot(
            self.env,
            {'lang': 'en_US'},
        )

        self.assertEqual(snapshot, {'lang': 'en_US'})

    def test_website_sale_session_request_context_preserves_owned_keys(self):
        context = {
            'website_id': 7,
            'pricelist_id': 11,
            'fiscal_position_id': 13,
        }
        snapshot = AIWebsiteSaleThreadController()._get_session_request_context_snapshot(
            self.env,
            context,
        )

        self.assertEqual(
            AIWebsiteSaleThreadController._session_request_context_keys
            - AIThreadController._session_request_context_keys,
            frozenset({'website_id', 'pricelist_id', 'fiscal_position_id'}),
        )
        self.assertEqual(snapshot, context)

    def test_session_request_context_is_bounded_to_accessible_companies(self):
        accessible_company_id = self.env.company.id
        inaccessible_company_id = max(self.env['res.company'].sudo().search([]).ids) + 1
        snapshot = AIThreadController()._get_session_request_context_snapshot(
            self.env,
            {
                'allowed_company_ids': [accessible_company_id, inaccessible_company_id],
                'active_company_ids': [inaccessible_company_id, accessible_company_id],
                'lang': 'en_US',
                'unrelated_key': 'not persisted',
            },
        )

        self.assertEqual(snapshot['allowed_company_ids'], [accessible_company_id])
        self.assertEqual(snapshot['active_company_ids'], [accessible_company_id])
        self.assertEqual(snapshot['lang'], 'en_US')
        self.assertNotIn('unrelated_key', snapshot)

    def test_session_request_company_validation_rejects_revoked_access(self):
        company = self.env['res.company'].create({'name': 'Callback revoked'})
        user = new_test_user(
            self.env,
            login='callback_company_revoked',
            groups='base.group_user',
        )
        user.sudo().write({'company_ids': [Command.link(company.id)]})
        actor_env = self.env['res.users'].with_user(user).env
        snapshot = {'allowed_company_ids': [company.id]}

        AIThreadController._validate_session_request_company_access(actor_env, snapshot)
        user.sudo().write({'company_ids': [Command.unlink(company.id)]})

        with self.assertRaises(AccessError):
            AIThreadController._validate_session_request_company_access(
                actor_env, snapshot,
            )
