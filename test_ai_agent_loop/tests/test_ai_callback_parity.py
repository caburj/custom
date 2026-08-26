# Part of Odoo. See LICENSE file for full copyright and licensing details.

from unittest.mock import patch

from odoo.tests import tagged, TransactionCase

from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_fields_tools import get_ai_value
from odoo.addons.ai.utils.ai_utils import UserInputResponse


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'content': {'data': text}}],
    }


@tagged('post_install', '-at_install')
class TestAICallbackParity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Callback Parity Agent',
            'system_prompt': 'Answer plainly.',
        })
        cls.channel = cls.agent._create_ai_chat_channel('Callback Parity')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })

    def _create_tool(self, name, code):
        return self.env['ir.actions.server'].create({
            'name': name,
            'ai_tool_name': name,
            'ai_tool_thinking_text': f'Running {name}',
            'ai_tool_description': 'Callback parity fixture.',
            'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code',
            'use_in_ai': True,
            'code': code,
        })

    def _prepare_session_request(self, session=None, channel=None, body='Hi', snapshot=None):
        session = session or self.session
        channel = channel or self.channel
        snapshot = snapshot or {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
        }
        message = channel.message_post(body=body, message_type='comment')
        session = session.with_context(**snapshot)
        return session, session._prepare_session_request(
            message._convert_to_parts(),
            context_snapshot=snapshot,
        )

    def _new_session(self, title):
        channel = self.agent._create_ai_chat_channel(title)
        session = self.env['ai.session'].sudo().create({
            'agent_id': self.agent.id,
            'channel_id': channel.id,
        })
        return channel, session

    def _apply_iap_tool_calls(self, session, request, calls):
        return session._apply_iap_result(request, {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {'role': 'assistant', 'content': calls},
        })

    @staticmethod
    def _tool_call(tool, call_id):
        return {
            'type': 'tool_call',
            'call_id': call_id,
            'name': tool.ai_tool_name,
            'args': {},
        }

    @staticmethod
    def _tool_results(request):
        return [
            part['tool_results']
            for part in request.payload['messages'][-1]['content']
        ]

    @staticmethod
    def _context_part(request):
        user_message = next(
            message for message in reversed(request.payload['messages'])
            if message['role'] == 'user'
            and any(part['type'] == 'text' for part in message['content'])
        )
        return next(
            part for part in user_message['content']
            if part.get('type') == 'text'
            and str(part.get('content', {}).get('data', '')).startswith(
                '<odoo_current_context>'
            )
        )

    def test_five_call_batch_preserves_order_across_every_pause(self):
        first = self._create_tool(
            'callback_batch_first',
            "ai['state']['first_runs'] = ai['state'].get('first_runs', 0) + 1; ai['result'] = 'first'",
        )
        first_confirmation = self._create_tool(
            'callback_batch_confirm_first',
            """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Run the first confirmed step?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['state']['first_confirmation_runs'] = ai['state'].get('first_confirmation_runs', 0) + 1
    ai['result'] = 'first confirmed'
""",
        )
        blocking_client = self._create_tool(
            'callback_batch_client',
            """
ai['state']['client_runs'] = ai['state'].get('client_runs', 0) + 1
ai['result'] = {'client_tool': {'name': 'callback_fixture_client', 'params': {}}}
""",
        )
        second_confirmation = self._create_tool(
            'callback_batch_confirm_second',
            """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Run the second confirmed step?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['state']['second_confirmation_runs'] = ai['state'].get('second_confirmation_runs', 0) + 1
    ai['result'] = 'second confirmed'
""",
        )
        last = self._create_tool(
            'callback_batch_last',
            "ai['state']['last_runs'] = ai['state'].get('last_runs', 0) + 1; ai['result'] = 'last'",
        )
        tools = first | first_confirmation | blocking_client | second_confirmation | last
        self.session.state = {'available_tools': tools.ids}
        session, request = self._prepare_session_request()
        event_count = len(session.event_ids)
        calls = [
            self._tool_call(tool, call_id)
            for tool, call_id in zip(
                tools,
                ('first', 'confirm-first', 'client', 'confirm-second', 'last'),
            )
        ]

        first_wait = self._apply_iap_tool_calls(session, request, calls)
        first_token = request.resume_token
        self.assertEqual(first_wait['responseState'], 'waiting_user')
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(len(session.event_ids), event_count + 1)

        client_wait = session._resume_pending_interaction(
            request, first_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )
        client_token = request.resume_token
        self.assertEqual(client_wait['responseState'], 'waiting_client')
        self.assertNotEqual(client_token, first_token)
        self.assertEqual(len(session.pending_tool_call['pending_results']), 2)
        self.assertEqual(len(session.event_ids), event_count + 1)

        second_wait = session._resume_pending_interaction(
            request, client_token, {'result': False},
        )
        second_token = request.resume_token
        self.assertEqual(second_wait['responseState'], 'waiting_user')
        self.assertNotEqual(second_token, client_token)
        self.assertEqual(len(session.pending_tool_call['pending_results']), 3)
        self.assertEqual(len(session.event_ids), event_count + 1)

        completed = session._resume_pending_interaction(
            request, second_token, {'value': UserInputResponse.CONFIRM_ONCE},
        )
        next_request = self.env['ai.session.request'].sudo().browse(
            completed['next_request_id'],
        )
        results = self._tool_results(next_request)

        self.assertEqual(
            [result['tool_call']['call_id'] for result in results],
            ['first', 'confirm-first', 'client', 'confirm-second', 'last'],
        )
        self.assertTrue(all(result['success'] for result in results))
        self.assertEqual(len(session.event_ids), event_count + 2)
        self.assertEqual(session.state['first_runs'], 1)
        self.assertEqual(session.state['first_confirmation_runs'], 1)
        self.assertEqual(session.state['client_runs'], 1)
        self.assertEqual(session.state['second_confirmation_runs'], 1)
        self.assertEqual(session.state['last_runs'], 1)
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 2)

    def test_tool_limit_counts_calls_before_a_confirmation_pause(self):
        self.env['ir.config_parameter'].sudo().set_int(
            'ai.max_tool_calls_per_call', 2,
        )
        first = self._create_tool(
            'callback_limited_first',
            "ai['state']['first_runs'] = ai['state'].get('first_runs', 0) + 1; ai['result'] = 'first'",
        )
        confirmation = self._create_tool(
            'callback_limited_confirmation',
            """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Run the limited step?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['result'] = 'confirmed'
""",
        )
        excess = self._create_tool(
            'callback_limited_excess',
            "ai['state']['excess_runs'] = ai['state'].get('excess_runs', 0) + 1; ai['result'] = 'unexpected'",
        )
        self.session.state = {
            'available_tools': (first | confirmation | excess).ids,
        }
        session, request = self._prepare_session_request()
        self._apply_iap_tool_calls(session, request, [
            self._tool_call(first, 'before-pause'),
            self._tool_call(confirmation, 'allowed'),
            self._tool_call(excess, 'limited'),
        ])

        completed = session._resume_pending_interaction(
            request, request.resume_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
        )
        results = self._tool_results(
            self.env['ai.session.request'].sudo().browse(completed['next_request_id']),
        )

        self.assertEqual(
            [result['tool_call']['call_id'] for result in results],
            ['before-pause', 'allowed', 'limited'],
        )
        self.assertTrue(results[0]['success'])
        self.assertTrue(results[1]['success'])
        self.assertFalse(results[2]['success'])
        self.assertIn('tool call limit reached', str(results[2]['result']))
        self.assertEqual(session.state['first_runs'], 1)
        self.assertNotIn('excess_runs', session.state)

    def test_new_message_refuses_pending_batch_then_starts_a_new_request(self):
        question = self.env.ref('ai.ir_actions_server_ask_user_question')
        session, first_request = self._prepare_session_request(body='Ask me a question')
        self._apply_iap_tool_calls(session, first_request, [{
            **self._tool_call(question, 'pending-question'),
            'args': {
                'question': 'Continue?',
                'choices': ['Yes', 'No'],
                'multi_select': False,
                'allow_free_text': False,
            },
        }])

        _session, second_request = self._prepare_session_request(
            session=session,
            body='Forget that and answer this instead',
        )

        self.assertEqual(first_request.state, 'done')
        self.assertFalse(first_request.resume_token)
        self.assertFalse(session.pending_tool_call)
        self.assertEqual(second_request.state, 'prepared')
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 2)
        refused_result = session.event_ids.sorted('id')[-2].metadata['content'][0]['tool_results']
        self.assertFalse(refused_result['success'])
        self.assertIn('chose not to proceed', str(refused_result['result']))
        self.assertTrue(any(
            'Skipped' in str(message.body)
            for message in session.channel_id.message_ids
        ))

    def test_context_is_stable_between_rounds_and_refreshed_after_resume(self):
        ordinary_tool = self._create_tool(
            'callback_context_round', "ai['result'] = 'done'",
        )
        initial_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'current_view_info': {'marker': 'initial'},
        }
        self.session.state = {'available_tools': ordinary_tool.ids}
        session, first_request = self._prepare_session_request(snapshot=initial_snapshot)
        first_context = self._context_part(first_request)
        automatic = self._apply_iap_tool_calls(session, first_request, [
            self._tool_call(ordinary_tool, 'ordinary'),
        ])
        automatic_request = self.env['ai.session.request'].sudo().browse(
            automatic['next_request_id'],
        )
        self.assertEqual(self._context_part(automatic_request), first_context)
        self.assertEqual(automatic_request.context_snapshot, initial_snapshot)

        channel, paused_session = self._new_session('Callback Fresh Context')
        confirmation = self._create_tool(
            'callback_context_confirmation',
            """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Resume with current context?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['result'] = 'confirmed'
""",
        )
        paused_session.state = {'available_tools': confirmation.ids}
        paused_session, paused_request = self._prepare_session_request(
            session=paused_session,
            channel=channel,
            body='Pause first',
            snapshot=initial_snapshot,
        )
        self._apply_iap_tool_calls(paused_session, paused_request, [
            self._tool_call(confirmation, 'confirmation'),
        ])
        fresh_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'current_view_info': {'marker': 'resumed'},
        }
        fresh_session = paused_session.with_context(**fresh_snapshot)
        fresh_request = fresh_session.env['ai.session.request'].sudo().browse(
            paused_request.id,
        )
        resumed = fresh_session._resume_pending_interaction(
            fresh_request,
            fresh_request.resume_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
            context_snapshot=fresh_snapshot,
        )
        resumed_request = self.env['ai.session.request'].sudo().browse(
            resumed['next_request_id'],
        )

        self.assertEqual(paused_request.context_snapshot, initial_snapshot)
        self.assertEqual(resumed_request.context_snapshot, fresh_snapshot)
        self.assertIn('resumed', str(self._context_part(resumed_request)))

    def test_unlinked_and_deleted_loaded_skills_lose_their_tools(self):
        tool = self._create_tool(
            'callback_removed_skill_tool', "ai['result'] = 'done'",
        )
        skill = self.env['ai.skill'].create({
            'name': 'Callback removable skill',
            'instructions': 'Use the removable tool.',
            'tool_ids': tool.ids,
        })
        self.agent.skill_ids = skill
        self.session.state = {
            'loaded_skills': skill.ids,
            'available_tools': tool.ids,
        }
        self.assertIn(tool, self.session._get_available_tools(
            self.session._build_tools_context(),
        ))

        self.agent.skill_ids = False
        unlinked_context = self.session._build_tools_context()
        self.assertNotIn(skill.id, unlinked_context['state']['loaded_skills'])
        self.assertNotIn(tool, self.session._get_available_tools(unlinked_context))

        self.agent.skill_ids = skill
        self.session.state = {
            'loaded_skills': skill.ids,
            'available_tools': tool.ids,
        }
        skill.unlink()
        deleted_context = self.session._build_tools_context()
        self.assertFalse(deleted_context['state']['loaded_skills'])
        self.assertNotIn(tool, self.session._get_available_tools(deleted_context))

    def test_tool_failures_prepare_one_explanatory_round_without_replay(self):
        for variant in ('unknown', 'exception'):
            with self.subTest(variant=variant):
                channel, session = self._new_session(f'Callback failure {variant}')
                successful = self._create_tool(
                    f'callback_success_before_{variant}',
                    "ai['state']['successful_runs'] = ai['state'].get('successful_runs', 0) + 1; ai['result'] = 'success'",
                )
                failing = self._create_tool(
                    f'callback_raising_{variant}', "ai['result'] = 1 / 0",
                )
                session.state = {'available_tools': (successful | failing).ids}
                session, request = self._prepare_session_request(
                    session=session, channel=channel, body=f'Test {variant}',
                )
                bad_call = self._tool_call(failing, 'bad')
                if variant == 'unknown':
                    bad_call['name'] = 'callback_unknown_tool'
                result = {
                    'request_uuid': request.request_uuid,
                    'status': 'success',
                    'result': {
                        'role': 'assistant',
                        'content': [
                            self._tool_call(successful, 'good'),
                            bad_call,
                        ],
                    },
                }

                outcome = session._apply_iap_result(request, result)
                next_request = self.env['ai.session.request'].sudo().browse(
                    outcome['next_request_id'],
                )
                results = self._tool_results(next_request)
                counts = (
                    len(session.event_ids),
                    len(session.channel_id.message_ids),
                    len(self.env['ai.session.request'].sudo().search([
                        ('session_id', '=', session.id),
                    ])),
                )

                self.assertTrue(results[0]['success'])
                self.assertFalse(results[1]['success'])
                self.assertEqual(session.state['successful_runs'], 1)
                session._apply_iap_result(next_request, {
                    'request_uuid': next_request.request_uuid,
                    'status': 'success',
                    'result': assistant_text('The tool failed, so nothing else was changed.'),
                })
                session._apply_iap_result(request, result)
                self.assertEqual(session.state['successful_runs'], 1)
                self.assertEqual(counts[0] + 1, len(session.event_ids))
                self.assertEqual(counts[1] + 1, len(session.channel_id.message_ids))
                self.assertEqual(counts[2], self.env['ai.session.request'].sudo().search_count([
                    ('session_id', '=', session.id),
                ]))

    def test_tool_owned_final_survives_a_later_confirmation_pause(self):
        final_tool = self._create_tool(
            'callback_owned_final',
            """
ai['final_message'] = [{'type': 'text', 'content': {'data': 'Owned final response'}}]
ai['message_body_suffix'] = '<span class="callback-owned-suffix">Preview</span>'
ai['result'] = 'done'
""",
        )
        confirmation = self._create_tool(
            'callback_after_owned_final',
            """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Finish the batch?',
        'choices': [
            {'label': 'Yes', 'value': 'confirm_once'},
            {'label': 'Always', 'value': 'auto_confirm'},
            {'label': 'No', 'value': 'decline'},
        ],
    }
else:
    ai['result'] = 'confirmed'
""",
        )
        self.session.state = {'available_tools': (final_tool | confirmation).ids}
        session, request = self._prepare_session_request()
        waiting = self._apply_iap_tool_calls(session, request, [
            self._tool_call(final_tool, 'owned-final'),
            self._tool_call(confirmation, 'confirmation'),
        ])
        self.assertEqual(waiting['responseState'], 'waiting_user')

        finished = session._resume_pending_interaction(
            request,
            request.resume_token,
            {'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(finished['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertNotIn('next_request_id', finished)
        self.assertIn('Owned final response', session.channel_id.message_ids[0].body)
        self.assertIn('callback-owned-suffix', session.channel_id.message_ids[0].body)
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 1)

        failure_channel, failure_session = self._new_session(
            'Callback failed sibling final',
        )
        failure_session.state = {'available_tools': final_tool.ids}
        failure_session, failure_request = self._prepare_session_request(
            session=failure_session,
            channel=failure_channel,
            body='Suppress a final after a failure',
        )
        failure_outcome = self._apply_iap_tool_calls(failure_session, failure_request, [
            self._tool_call(final_tool, 'candidate-final'),
            {
                'type': 'tool_call',
                'call_id': 'failed-sibling',
                'name': 'callback_missing_sibling',
                'args': {},
            },
        ])
        failure_followup = self.env['ai.session.request'].sudo().browse(
            failure_outcome['next_request_id'],
        )
        self.assertEqual(failure_outcome['responseState'], 'running')
        self.assertFalse(self._tool_results(failure_followup)[1]['success'])
        self.assertFalse(any(
            'Owned final response' in str(message.body)
            for message in failure_session.channel_id.message_ids
        ))

        suffix_channel, suffix_session = self._new_session(
            'Callback suffix continuation',
        )
        suffix_tool = self._create_tool(
            'callback_suffix_continuation',
            """
ai['message_body_suffix'] = '<span class="callback-round-suffix">Round preview</span>'
ai['result'] = 'continue'
""",
        )
        suffix_session.state = {'available_tools': suffix_tool.ids}
        suffix_session, suffix_request = self._prepare_session_request(
            session=suffix_session,
            channel=suffix_channel,
            body='Carry preview markup to the final round',
        )
        suffix_outcome = self._apply_iap_tool_calls(suffix_session, suffix_request, [
            self._tool_call(suffix_tool, 'suffix'),
        ])
        suffix_followup = self.env['ai.session.request'].sudo().browse(
            suffix_outcome['next_request_id'],
        )
        self.assertIn('callback-round-suffix', suffix_followup.message_body_suffix)
        suffix_session._apply_iap_result(suffix_followup, {
            'request_uuid': suffix_followup.request_uuid,
            'status': 'success',
            'result': assistant_text('Final after preview'),
        })
        self.assertIn(
            'callback-round-suffix', suffix_session.channel_id.message_ids[0].body,
        )

    def test_round_limit_and_terminal_iap_errors_settle_once(self):
        self.env['ir.config_parameter'].sudo().set_int(
            'ai.max_successive_calls', 1,
        )
        tool = self._create_tool(
            'callback_round_limit_tool', "ai['result'] = 'continue'",
        )
        self.session.state = {'available_tools': tool.ids}
        session, request = self._prepare_session_request()
        result = {
            'request_uuid': request.request_uuid,
            'status': 'success',
            'result': {
                'role': 'assistant',
                'content': [self._tool_call(tool, 'limit')],
            },
        }
        outcome = session._apply_iap_result(request, result)
        message_count = len(session.channel_id.message_ids)
        replay = session._apply_iap_result(request, result)
        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(replay['responseState'], 'idle')
        self.assertEqual(request.state, 'failed')
        self.assertIn('too many successive tool rounds', session.channel_id.message_ids[0].body)
        self.assertEqual(len(session.channel_id.message_ids), message_count)
        self.assertEqual(self.env['ai.session.request'].sudo().search_count([
            ('session_id', '=', session.id),
        ]), 1)

        for error_code in ('request_failed', 'insufficient_credit'):
            with self.subTest(error_code=error_code):
                channel, error_session = self._new_session(
                    f'Callback terminal {error_code}',
                )
                error_session, error_request = self._prepare_session_request(
                    session=error_session,
                    channel=channel,
                    body='Trigger a terminal error',
                )
                error_result = {
                    'request_uuid': error_request.request_uuid,
                    'status': 'error',
                    'error': error_code,
                }
                with patch.object(
                    self.env.registry['iap.account'],
                    '_send_no_credit_notification',
                    autospec=True,
                ) as notify:
                    error_session._apply_iap_result(error_request, error_result)
                    error_message_count = len(error_session.channel_id.message_ids)
                    error_session._apply_iap_result(error_request, error_result)
                self.assertEqual(error_request.state, 'failed')
                self.assertIn('AI is unreachable', error_session.channel_id.message_ids[0].body)
                self.assertEqual(
                    len(error_session.channel_id.message_ids), error_message_count,
                )
                self.assertEqual(
                    notify.call_count,
                    1 if error_code == 'insufficient_credit' else 0,
                )

        channel, invalid_session = self._new_session('Callback invalid result')
        invalid_session, invalid_request = self._prepare_session_request(
            session=invalid_session,
            channel=channel,
            body='Trigger invalid result',
        )
        invalid_event_count = len(invalid_session.event_ids)
        invalid = invalid_session._apply_iap_result(invalid_request, {
            'request_uuid': invalid_request.request_uuid,
            'status': 'success',
            'result': {'role': 'assistant', 'content': []},
        })
        self.assertEqual(invalid['responseState'], 'idle')
        self.assertEqual(invalid_request.state, 'failed')
        self.assertEqual(len(invalid_session.event_ids), invalid_event_count)


@tagged('post_install', '-at_install')
class TestAIDirectParity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = cls.env['ai.agent'].create({
            'name': 'Direct Parity Agent',
            'system_prompt': 'Answer plainly.',
        })
        cls.channel = cls.agent._create_ai_chat_channel('Direct Parity')
        cls.session = cls.env['ai.session'].sudo().create({
            'agent_id': cls.agent.id,
            'channel_id': cls.channel.id,
        })

    def _request_count(self):
        return self.env['ai.session.request'].sudo().search_count([])

    def test_channel_title_and_agent_wrapper_remain_direct(self):
        request_count = self._request_count()
        completions = [
            {'status': 'success', 'result': assistant_text('Direct title')},
            {'status': 'success', 'result': assistant_text('Direct answer')},
        ]
        with patch.object(AiSession, '_get_completions', side_effect=completions):
            title = self.session._generate_channel_name([
                {'type': 'text', 'content': {'data': 'Name this chat'}},
            ])
            answer = self.agent._generate_single_response([
                {'type': 'text', 'content': {'data': 'Answer directly'}},
            ])

        self.assertEqual(title, 'Direct title')
        self.assertEqual(answer, assistant_text('Direct answer')['content'])
        self.assertEqual(self._request_count(), request_count)

    def test_server_action_and_structured_field_call_the_direct_engine(self):
        request_count = self._request_count()
        partner = self.env['res.partner'].create({'name': 'Direct input'})
        action = self.env['ir.actions.server'].create({
            'name': 'Direct parity action',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'state': 'ai',
            'ai_action_prompt': 'Summarize this contact.',
        })
        structured = [{
            'type': 'text',
            'content': {
                'data': (
                    '{"value": "Generated", "could_not_resolve": false, '
                    '"unresolved_cause": null}'
                ),
            },
        }]
        with patch.object(
            AiSession,
            '_get_direct_response',
            side_effect=[assistant_text('Action done')['content'], structured],
        ) as direct_response:
            action_response, tool_history = action._ai_action_run(partner)
            field_value = get_ai_value(
                partner,
                {'type': 'char', 'string': 'Generated value'},
                'Generate the value.',
                [],
                {},
            )

        self.assertEqual(action_response, assistant_text('Action done')['content'])
        self.assertFalse(tool_history)
        self.assertEqual(field_value, 'Generated')
        self.assertEqual(direct_response.call_count, 2)
        self.assertEqual(self._request_count(), request_count)

    def test_nested_web_search_and_image_generation_remain_direct(self):
        request_count = self._request_count()
        web_search = self.env.ref('ai.ir_actions_server_ai_web_search')
        image_generation = self.env.ref('ai.ir_actions_server_ai_generate_image')
        self.session.state = {
            'available_tools': (web_search | image_generation).ids,
        }
        company_ids = self.env.companies.ids
        message = self.channel.message_post(
            body='Research callbacks and draw a diagram.',
            message_type='comment',
        )
        session = self.session.with_context(
            active_company_ids=company_ids,
            allowed_company_ids=company_ids,
        )
        request = session._prepare_session_request(
            message._convert_to_parts(),
            context_snapshot={
                'active_company_ids': company_ids,
                'allowed_company_ids': company_ids,
            },
        )
        completions = [
            {'status': 'success', 'result': assistant_text('Search result')},
            {'status': 'success', 'result': assistant_text('Need more detail')},
        ]
        with patch.object(
            AiSession, '_get_completions', side_effect=completions,
        ) as direct_completion:
            outcome = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': {
                    'role': 'assistant',
                    'content': [
                        {
                            'type': 'tool_call',
                            'call_id': 'nested-web-search',
                            'name': web_search.ai_tool_name,
                            'args': {
                                'query': 'callback parity',
                                'retrieval_mode': 'summary',
                                'context_hint': None,
                            },
                        },
                        {
                            'type': 'tool_call',
                            'call_id': 'nested-image-generation',
                            'name': image_generation.ai_tool_name,
                            'args': {
                                'prompt': 'Draw a callback diagram.',
                                'images_paths': [],
                                'image_title': 'Callback diagram',
                                'feedback': 'Here is the diagram.',
                                'aspect_ratio': '1:1',
                            },
                        },
                    ],
                },
            })

        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertEqual(direct_completion.call_count, 2)
        self.assertEqual(self._request_count(), request_count + 1)
        tool_results = session.event_ids.sorted('id')[-1].metadata['content']
        self.assertEqual(
            [part['tool_results']['tool_call']['call_id'] for part in tool_results],
            ['nested-web-search', 'nested-image-generation'],
        )
        self.assertTrue(all(part['tool_results']['success'] for part in tool_results))
        self.assertIn('Need more detail', session.channel_id.message_ids[0].body)
