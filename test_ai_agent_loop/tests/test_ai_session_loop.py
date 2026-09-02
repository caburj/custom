# Part of Odoo. See LICENSE file for full copyright and licensing details.

import base64
import copy
from textwrap import dedent
from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo import Command
from odoo.tests import new_test_user, tagged, TransactionCase
from odoo.exceptions import AccessError, UserError
from odoo.tools import mute_logger

from odoo.addons.ai.controllers.thread import AIThreadController
from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_utils import call_odoo_ai_transport
from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.ai_website_sale.controllers.thread import AIWebsiteSaleThreadController
from odoo.addons.mail.tools.discuss import Store


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
        'provider_metadata': {},
    }


@tagged('post_install', '-at_install')
class TestAISessionLoop(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Callback Test Agent',
            'system_prompt': 'Answer plainly.',
        })
        cls.agent.skill_ids = cls.env['ai.skill'].create({
            'name': 'Callback Business Records',
            'instructions': 'Create and update test contacts when requested.',
            'tool_ids': [Command.set([
                cls.env.ref('ai.ir_actions_server_create_records').id,
                cls.env.ref('ai.ir_actions_server_update_records').id,
            ])],
        })
        cls.channel = cls.agent._create_ai_chat_channel('Callback Test')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })

    def _post_prompt(self, body='Hi'):
        return self.channel.message_post(body=body, message_type='comment')

    def _prepare_model_request(self, message=None):
        message = message or self._post_prompt()
        context_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
        }
        session = self.session.with_context(**context_snapshot)
        prepared = session._prepare_model_request(
            message._convert_to_parts(),
            context_snapshot=context_snapshot,
        )
        self.assertEqual(prepared, {
            'session_id': session.id,
            'request_uuid': session.request_uuid,
        })
        return session

    def _apply_iap_result(self, session, request_uuid, result):
        return session._apply_iap_result(request_uuid, result)

    def _resume_pending_interaction(self, session, request_uuid, resume_token, response):
        return session._resume_pending_interaction(request_uuid, resume_token, response)

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

    def _apply_iap_tool_call(self, session, request_uuid, tool, call_id, args):
        return self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'provider_metadata': {},
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        waiting = self._apply_iap_tool_call(
            session,
            request_uuid,
            tool,
            'callback-question',
            {
                'question': 'Which option should be used?',
                'choices': choices,
                'multi_select': multi_select,
                'allow_free_text': allow_free_text,
            },
        )
        return session, request_uuid, waiting

    def test_prepare_persists_one_immutable_active_model_round(self):
        message = self._post_prompt()
        session = self._prepare_model_request(message)
        payload_before = copy.deepcopy(session.request_payload)

        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertEqual(session.request_round, 1)
        self.assertEqual(session.request_payload, payload_before)
        self.assertEqual(len(self.session.event_ids), 1)
        self.assertNotIn('<odoo_current_context>', str(self.session.event_ids.metadata))
        self.assertIn('<odoo_current_context>', str(session.request_payload['messages']))
        with self.assertRaises(UserError):
            session.write({'request_payload': {}})

    def test_active_model_round_requires_non_null_bounds(self):
        session = self._prepare_model_request()
        for column, query in (
            (
                'request_round',
                'UPDATE ai_session SET request_round = NULL WHERE id = %s',
            ),
            (
                'request_round_limit',
                'UPDATE ai_session SET request_round_limit = NULL WHERE id = %s',
            ),
        ):
            with (
                self.subTest(column=column),
                mute_logger('odoo.sql_db'),
                self.assertRaises(IntegrityError),
                self.env.cr.savepoint(),
            ):
                self.env.cr.execute(query, [session.id])

    def test_plain_result_applies_once_after_submission(self):
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        session.request_phase = 'submitted'
        session._publish_response_state()

        self.assertEqual(session.request_phase, 'submitted')
        event_count = len(session.event_ids)
        message_count = len(session.channel_id.message_ids)

        result = {
            'kind': 'success',
            'message': assistant_text('Hello from the callback'),
        }
        outcome = self._apply_iap_result(session, request_uuid, result)
        counts_after_first = (
            len(session.event_ids),
            len(session.channel_id.message_ids),
        )
        replay = self._apply_iap_result(session, request_uuid, result)

        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertEqual(replay['response']['responseState'], 'idle')
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_phase)
        self.assertFalse(session.request_uuid)
        self.assertEqual(len(session.event_ids), event_count + 1)
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertEqual(counts_after_first, (
            len(session.event_ids), len(session.channel_id.message_ids),
        ))
        self.assertIn('Hello from the callback', session.channel_id.message_ids[0].body)

    def test_inline_data_only_success_posts_one_visible_attachment(self):
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        message_count = len(session.channel_id.message_ids)
        result = {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'provider_metadata': {},
                'content': [{
                    'type': 'inline_data',
                    'data': base64.b64encode(b'fixture image').decode(),
                    'mimetype': 'image/png',
                }],
            },
        }

        outcome = self._apply_iap_result(session, request_uuid, result)

        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertEqual(session.loop_state, 'ready')
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertEqual(len(session.channel_id.message_ids[0].attachment_ids), 1)

    def test_server_tool_result_prepares_one_followup_round(self):
        self.env['res.partner'].create({'name': 'Callback Tool Contact'})
        tool = self._create_test_tool(
            'ai_tool_callback_count_contacts',
            "ai['result'] = len(env['res.partner'].search([('name', '=', 'Callback Tool Contact')]))",
        )
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        output_message = {
            'role': 'assistant',
            'provider_metadata': {},
            'content': [{
                'type': 'tool_call',
                'call_id': 'count-contacts',
                'name': tool.ai_tool_name,
                'args': {},
            }],
        }

        outcome = self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': output_message,
        })

        self.assertEqual(outcome['response']['responseState'], 'running')
        self.assertEqual(outcome['prepared']['session_id'], session.id)
        self.assertEqual(outcome['prepared']['request_uuid'], session.request_uuid)
        self.assertEqual(session.request_phase, 'prepared')
        self.assertEqual(session.request_round, 2)
        self.assertNotEqual(session.request_uuid, request_uuid)
        self.assertEqual(
            [message['role'] for message in session.request_payload['messages']],
            ['user', 'assistant', 'user'],
        )
        tool_result = session.request_payload['messages'][-1]['content'][0]
        self.assertTrue(tool_result['success'])
        self.assertEqual(tool_result['tool_call_id'], 'count-contacts')
        self.assertEqual(tool_result['result'][0]['text'], '1')

        followup_uuid = session.request_uuid
        self._apply_iap_result(session, followup_uuid, {
            'kind': 'success',
            'message': assistant_text('You have one callback tool contact.'),
        })

        self.assertEqual(session.loop_state, 'ready')
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid

        with patch.object(
            self.env.registry['discuss.channel'], '_bus_send', autospec=True,
        ) as bus_send:
            outcome = self._apply_iap_result(session, request_uuid, {
                'kind': 'success',
                'message': {
                    'role': 'assistant',
                    'provider_metadata': {},
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
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(outcome['prepared']['session_id'], session.id)
        self.assertEqual(outcome['prepared']['request_uuid'], session.request_uuid)
        self.assertNotEqual(session.request_uuid, request_uuid)

    def test_single_choice_question_survives_reload_and_resumes_once(self):
        session, request_uuid, waiting = self._prepare_question(['Draft', 'Send'])

        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(session.loop_state, 'waiting_answer')
        self.assertFalse(session.request_phase)
        resume_token = session.resume_token
        self.env.invalidate_all()
        session = self.env['ai.session'].sudo().browse(session.id)
        stored_session = Store().add(
            session, '_store_session_fields',
        )._build_result()['ai.session'][0]
        self.assertEqual(stored_session['userInputRequest']['requestUuid'], request_uuid)
        self.assertEqual(stored_session['userInputRequest']['resumeToken'], resume_token)
        for invalid_response in (
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
            {'kind': 'question', 'value': ['Draft', 'Send']},
            {'kind': 'question', 'value': ['Invented']},
        ):
            with self.subTest(invalid_response=invalid_response), self.assertRaises(UserError):
                self._resume_pending_interaction(
                    session, request_uuid, resume_token, invalid_response,
                )
        self.assertEqual(session.loop_state, 'waiting_answer')
        self.assertEqual(session.resume_token, resume_token)

        resumed = self._resume_pending_interaction(
            session, request_uuid, resume_token,
            {'kind': 'question', 'value': ['Draft']},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        self.assertFalse(session.pending_tool_call)
        self.assertEqual(resumed['prepared']['session_id'], session.id)
        self.assertNotEqual(session.request_uuid, request_uuid)
        result = session.request_payload['messages'][-1]['content'][0]
        self.assertEqual(result['tool_call_id'], 'callback-question')
        self.assertIn('USER ANSWER: Draft', str(result['result']))
        self.assertIn('Draft', session.channel_id.message_ids[0].body)
        with self.assertRaises(UserError):
            self._resume_pending_interaction(
                session, request_uuid, resume_token,
                {'kind': 'question', 'value': ['Draft']},
            )

    def test_free_text_question_preserves_the_answer(self):
        session, request_uuid, _waiting = self._prepare_question(
            ['Brussels', 'Ghent'], allow_free_text=True,
        )

        resumed = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'question', 'value': ['Antwerp']},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        result = session.request_payload['messages'][-1]['content'][0]
        self.assertIn('USER ANSWER: Antwerp', str(result['result']))
        self.assertIn('Antwerp', session.channel_id.message_ids[0].body)

    def test_multi_select_question_uses_persisted_choice_order(self):
        session, request_uuid, _waiting = self._prepare_question(
            ['Red', 'Green', 'Blue'], multi_select=True,
        )

        resumed = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'question', 'value': ['Blue', 'Red']},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        result = session.request_payload['messages'][-1]['content'][0]
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'provider_metadata': {},
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

        resume_token = session.resume_token
        skipped = self._resume_pending_interaction(
            session, request_uuid, session.resume_token, {'kind': 'skip'},
        )

        self.assertEqual(skipped['response']['responseState'], 'idle')
        self.assertEqual(skipped['kind'], 'stable')
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertFalse(session.pending_tool_call)
        results = [
            part
            for part in session.event_ids.sorted('id')[-1].metadata['content']
            if part.get('type') == 'tool_result'
        ]
        self.assertEqual(
            [result['tool_call_id'] for result in results],
            ['completed-before-question', 'skipped-question', 'create-after-question'],
        )
        self.assertEqual([result['success'] for result in results], [True, False, False])
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Must Not Be Created'),
        ]))
        with self.assertRaises(UserError):
            self._resume_pending_interaction(
                session, request_uuid, resume_token, {'kind': 'skip'},
            )

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
            ('truthy', {'kind': 'client_result', 'value': {'client_value': 42}}, True, '{"client_value": 42}'),
            ('false', {'kind': 'client_result', 'value': False}, True, 'false'),
            ('null', {'kind': 'client_result', 'value': None}, True, 'success'),
            ('empty', {'kind': 'client_result', 'value': ''}, True, ''),
            ('error', {'kind': 'client_error', 'value': 'Client tool failed'}, False, 'Error: Client tool failed'),
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
                session._prepare_model_request(
                    message._convert_to_parts(),
                    context_snapshot={
                        'active_company_ids': self.env.companies.ids,
                        'allowed_company_ids': self.env.companies.ids,
                    },
                )
                request_uuid = session.request_uuid

                waiting = self._apply_iap_tool_call(
                    session, request_uuid, tool, f'client-tool-{label}', {},
                )

                self.assertEqual(waiting['response']['responseState'], 'waiting_client')
                self.assertEqual(session.loop_state, 'waiting_client_result')
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
                    'requestUuid': request_uuid,
                    'resumeToken': session.resume_token,
                })
                resume_token = session.resume_token
                if label == 'truthy':
                    with self.assertRaises(UserError):
                        self._resume_pending_interaction(
                            session, request_uuid, resume_token,
                            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
                        )
                    self.assertEqual(session.loop_state, 'waiting_client_result')
                    self.assertEqual(session.resume_token, resume_token)
                resumed = self._resume_pending_interaction(
                    session, request_uuid, resume_token, response,
                )

                self.assertEqual(resumed['response']['responseState'], 'running')
                self.assertEqual(session.state['client_tool_runs'], 1)
                self.assertNotEqual(session.request_uuid, request_uuid)
                result = session.request_payload['messages'][-1]['content'][0]
                self.assertEqual(result['success'], success)
                self.assertEqual(result['result'][0]['text'], expected_data)
                with self.assertRaises(UserError):
                    self._resume_pending_interaction(
                        session, request_uuid, resume_token, response,
                    )
                self.assertEqual(session.state['client_tool_runs'], 1)

    def test_create_tool_waits_durably_then_confirmation_executes_once(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid

        waiting = self._apply_iap_tool_call(
            session, request_uuid, tool, 'create-contact',
            self._create_partner_args('Callback Confirmed Contact'),
        )

        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertTrue(session.resume_token)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Callback Confirmed Contact'),
        ]))
        self.assertNotIn('request_id', session.pending_tool_call)
        self.assertEqual(
            session.pending_tool_call['user_input_request']['type'],
            'confirmation',
        )
        resume_token = session.resume_token

        for invalid_response in (
            {'kind': 'skip'},
            {'kind': 'confirmation', 'value': 'invented'},
        ):
            with self.subTest(invalid_response=invalid_response), self.assertRaises(UserError):
                self._resume_pending_interaction(
                    session, request_uuid, resume_token, invalid_response,
                )
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.resume_token, resume_token)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Callback Confirmed Contact'),
        ]))

        resumed = self._resume_pending_interaction(
            session, request_uuid, resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        self.assertFalse(session.pending_tool_call)
        self.assertNotEqual(session.request_uuid, request_uuid)
        partners = self.env['res.partner'].search([
            ('name', '=', 'Callback Confirmed Contact'),
        ])
        self.assertEqual(len(partners), 1)
        tool_result = session.request_payload['messages'][-1]['content'][0]
        self.assertEqual(tool_result['tool_call_id'], 'create-contact')
        self.assertTrue(tool_result['success'])

        with self.assertRaises(UserError):
            self._resume_pending_interaction(
                session, request_uuid, resume_token,
                {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
            )
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', 'Callback Confirmed Contact'),
        ]), 1)

    def test_confirmation_resume_rolls_back_effect_and_session_state_together(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        partner_name = 'Callback Rolled Back Contact'
        self._apply_iap_tool_call(
            session, request_uuid, tool, 'rollback-create',
            self._create_partner_args(partner_name),
        )
        resume_token = session.resume_token
        pending_tool_call = copy.deepcopy(session.pending_tool_call)
        request_payload = copy.deepcopy(session.request_payload)
        event_count = len(session.event_ids)
        message_count = len(session.channel_id.message_ids)

        with (
            patch.object(
                AiSession,
                '_prepare_model_request',
                side_effect=RuntimeError('fixture rollback after tool execution'),
            ),
            self.assertRaises(RuntimeError),
            self.env.cr.savepoint(),
        ):
            self._resume_pending_interaction(
                session, request_uuid, resume_token,
                {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
            )

        self.env.invalidate_all()
        session = self.env['ai.session'].sudo().browse(session.id)
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.resume_token, resume_token)
        self.assertEqual(session.request_payload, request_payload)
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        partner_name = 'Callback Question Follow-up Contact'
        waiting = self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'provider_metadata': {},
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
        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        confirmation_token = session.resume_token
        event_count = len(session.event_ids)

        question_waiting = self._resume_pending_interaction(
            session,
            request_uuid,
            confirmation_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(question_waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(session.loop_state, 'waiting_answer')
        self.assertNotEqual(session.resume_token, confirmation_token)
        self.assertEqual(session.pending_tool_call['call_id'], 'follow-up-question')
        self.assertEqual(
            session.pending_tool_call['user_input_request']['type'], 'question',
        )
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(len(session.event_ids), event_count)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', '=', partner_name),
        ]), 1)

        resumed = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'question', 'value': ['First option']},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        results = [
            part
            for part in session.request_payload['messages'][-1]['content']
            if part.get('type') == 'tool_result'
        ]
        self.assertEqual(
            [result['tool_call_id'] for result in results],
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid

        waiting = self._apply_iap_tool_call(
            session, request_uuid, tool, 'generic-confirmation', {},
        )

        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertNotIn('generic_confirmation_runs', session.state)
        resume_token = session.resume_token

        resumed = self._resume_pending_interaction(
            session, request_uuid, resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        self.assertEqual(session.state['generic_confirmation_runs'], 1)
        tool_result = session.request_payload['messages'][-1]['content'][0]
        self.assertEqual(tool_result['tool_name'], tool.ai_tool_name)
        self.assertTrue(tool_result['success'])

    def test_update_tool_uses_persisted_arguments_after_confirmation(self):
        partner = self.env['res.partner'].create({'name': 'Callback Before Update'})
        tool = self.env.ref('ai.ir_actions_server_update_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
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

        self._apply_iap_tool_call(
            session, request_uuid, tool, 'update-contact', args,
        )

        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertEqual(partner.name, 'Callback Before Update')
        pending_call = session._get_last_tool_calls()[0]
        self.assertEqual(pending_call['args'], args)

        resumed = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(resumed['response']['responseState'], 'running')
        self.assertEqual(partner.name, 'Callback After Update')
        self.assertNotEqual(session.request_uuid, request_uuid)

    def test_decline_balances_the_tool_call_without_mutating(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        self._apply_iap_tool_call(
            session, request_uuid, tool, 'declined-create',
            self._create_partner_args('Declined Callback Contact'),
        )

        declined = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.DECLINE},
        )

        self.assertEqual(declined['response']['responseState'], 'idle')
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertFalse(session.pending_tool_call)
        self.assertFalse(self.env['res.partner'].search([
            ('name', '=', 'Declined Callback Contact'),
        ]))
        tool_result = session.event_ids.sorted('id')[-1].metadata['content'][0]
        self.assertFalse(tool_result['success'])

    def test_sequential_confirmations_rotate_tokens_and_preserve_result_order(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
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
        self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'content': tool_calls,
                'provider_metadata': {},
            },
        })
        first_token = session.resume_token
        event_count_before_resumes = len(session.event_ids)

        first_resume = self._resume_pending_interaction(
            session, request_uuid, first_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(first_resume['response']['responseState'], 'waiting_user')
        self.assertEqual(session.loop_state, 'waiting_confirmation')
        self.assertNotEqual(session.resume_token, first_token)
        self.assertEqual(session.pending_tool_call['call_id'], 'create-second')
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(session.pending_tool_call['pending_results'][0]['tool_call_id'], 'create-first')
        self.assertEqual(len(session.event_ids), event_count_before_resumes)
        with self.assertRaises(UserError):
            self._resume_pending_interaction(
                session, request_uuid, first_token,
                {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
            )

        second_resume = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(second_resume['response']['responseState'], 'running')
        results = [
            part
            for part in session.request_payload['messages'][-1]['content']
            if part.get('type') == 'tool_result'
        ]
        self.assertEqual(
            [result['tool_call_id'] for result in results],
            ['create-first', 'create-second'],
        )
        self.assertEqual(len(session.event_ids), event_count_before_resumes + 1)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', 'in', ['Callback First Contact', 'Callback Second Contact']),
        ]), 2)

    def test_auto_confirm_executes_later_confirmation_without_waiting(self):
        tool = self.env.ref('ai.ir_actions_server_create_records')
        self.session.state = {'available_tools': [tool.id]}
        session = self._prepare_model_request()
        first_request_uuid = session.request_uuid
        self._apply_iap_tool_call(
            session, first_request_uuid, tool, 'auto-first',
            self._create_partner_args('Callback Auto First'),
        )
        first_resume = self._resume_pending_interaction(
            session, first_request_uuid, session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.AUTO_CONFIRM},
        )
        self.assertEqual(first_resume['response']['responseState'], 'running')
        second_request_uuid = session.request_uuid

        second_resume = self._apply_iap_tool_call(
            session, second_request_uuid, tool, 'auto-second',
            self._create_partner_args('Callback Auto Second'),
        )

        self.assertTrue(session.auto_confirm)
        self.assertEqual(second_resume['response']['responseState'], 'running')
        self.assertFalse(session.pending_tool_call)
        self.assertNotEqual(session.request_uuid, second_request_uuid)
        self.assertEqual(self.env['res.partner'].search_count([
            ('name', 'in', ['Callback Auto First', 'Callback Auto Second']),
        ]), 2)

    def test_direct_response_remains_synchronous_and_does_not_change_loop_state(self):
        loop_snapshot = self.session.read([
            'loop_state',
            'request_phase',
            'request_uuid',
            'request_payload',
            'request_round',
            'request_round_limit',
            'request_context',
            'resume_token',
            'pending_tool_call',
        ])[0]
        event_ids = self.session.event_ids.ids
        with patch.object(AiSession, '_get_completions', return_value={
            'status': 'success',
            'result': assistant_text('Direct'),
        }):
            result = self.env['ai.session']._get_direct_response(
                instructions='Answer.',
                message=[{'type': 'text', 'text': 'Hi'}],
            )

        self.assertEqual(result, assistant_text('Direct')['content'])
        self.assertEqual(self.session.read(list(loop_snapshot))[0], loop_snapshot)
        self.assertEqual(self.session.event_ids.ids, event_ids)

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
