# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
from unittest.mock import patch

from odoo import Command
from odoo.tests import tagged, TransactionCase

from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_fields_tools import get_ai_value
from odoo.addons.ai.utils.ai_utils import UserInputResponse


def assistant_text(text):
    return {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
        'provider_metadata': {},
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

    def _prepare_model_request(self, session=None, channel=None, body='Hi', snapshot=None):
        session = session or self.session
        channel = channel or self.channel
        snapshot = snapshot or {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
        }
        message = channel.message_post(body=body, message_type='comment')
        session = session.with_context(**snapshot)
        prepared = session._prepare_model_request(
            message._convert_to_parts(),
            context_snapshot=snapshot,
        )
        self.assertEqual(prepared, {
            'session_id': session.id,
            'request_uuid': session.request_uuid,
        })
        return session

    @staticmethod
    def _apply_iap_result(session, request_uuid, result):
        return session._apply_iap_result(request_uuid, result)

    @staticmethod
    def _resume_pending_interaction(
        session, request_uuid, resume_token, response, **kwargs,
    ):
        return session._resume_pending_interaction(
            request_uuid, resume_token, response, **kwargs,
        )

    def _new_session(self, title):
        channel = self.agent._create_ai_chat_channel(title)
        session = self.env['ai.session'].sudo().create({
            'agent_id': self.agent.id,
            'channel_id': channel.id,
        })
        return channel, session

    def _apply_iap_tool_calls(self, session, request_uuid, calls):
        return self._apply_iap_result(session, request_uuid, {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'content': calls,
                'provider_metadata': {},
            },
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
    def _tool_results(request_payload):
        return [
            part
            for part in request_payload['messages'][-1]['content']
            if part.get('type') == 'tool_result'
        ]

    @staticmethod
    def _context_part(request_payload):
        user_message = next(
            message for message in reversed(request_payload['messages'])
            if message['role'] == 'user'
            and any(part['type'] == 'text' for part in message['content'])
        )
        return next(
            part for part in user_message['content']
            if part.get('type') == 'text'
            and part.get('text', '').startswith('<odoo_current_context>')
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        event_count = len(session.event_ids)
        calls = [
            self._tool_call(tool, call_id)
            for tool, call_id in zip(
                tools,
                ('first', 'confirm-first', 'client', 'confirm-second', 'last'),
            )
        ]

        first_wait = self._apply_iap_tool_calls(session, request_uuid, calls)
        first_token = session.resume_token
        self.assertEqual(first_wait['response']['responseState'], 'waiting_user')
        self.assertEqual(len(session.pending_tool_call['pending_results']), 1)
        self.assertEqual(len(session.event_ids), event_count + 1)

        client_wait = self._resume_pending_interaction(
            session, request_uuid, first_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        client_token = session.resume_token
        self.assertEqual(client_wait['response']['responseState'], 'waiting_client')
        self.assertNotEqual(client_token, first_token)
        self.assertEqual(len(session.pending_tool_call['pending_results']), 2)
        self.assertEqual(len(session.event_ids), event_count + 1)

        second_wait = self._resume_pending_interaction(
            session, request_uuid, client_token,
            {'kind': 'client_result', 'value': False},
        )
        second_token = session.resume_token
        self.assertEqual(second_wait['response']['responseState'], 'waiting_user')
        self.assertNotEqual(second_token, client_token)
        self.assertEqual(len(session.pending_tool_call['pending_results']), 3)
        self.assertEqual(len(session.event_ids), event_count + 1)

        completed = self._resume_pending_interaction(
            session, request_uuid, second_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        results = self._tool_results(session.request_payload)

        self.assertEqual(
            [result['tool_call_id'] for result in results],
            ['first', 'confirm-first', 'client', 'confirm-second', 'last'],
        )
        self.assertTrue(all(result['success'] for result in results))
        self.assertEqual(len(session.event_ids), event_count + 2)
        self.assertEqual(session.state['first_runs'], 1)
        self.assertEqual(session.state['first_confirmation_runs'], 1)
        self.assertEqual(session.state['client_runs'], 1)
        self.assertEqual(session.state['second_confirmation_runs'], 1)
        self.assertEqual(session.state['last_runs'], 1)
        self.assertEqual(completed['prepared']['session_id'], session.id)
        self.assertEqual(completed['prepared']['request_uuid'], session.request_uuid)
        self.assertNotEqual(session.request_uuid, request_uuid)
        self.assertEqual(session.request_round, 2)

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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        self._apply_iap_tool_calls(session, request_uuid, [
            self._tool_call(first, 'before-pause'),
            self._tool_call(confirmation, 'allowed'),
            self._tool_call(excess, 'limited'),
        ])

        completed = self._resume_pending_interaction(
            session, request_uuid, session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        results = self._tool_results(session.request_payload)

        self.assertEqual(completed['response']['responseState'], 'running')
        self.assertEqual(
            [result['tool_call_id'] for result in results],
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
        session = self._prepare_model_request(body='Ask me a question')
        first_request_uuid = session.request_uuid
        self._apply_iap_tool_calls(session, first_request_uuid, [{
            **self._tool_call(question, 'pending-question'),
            'args': {
                'question': 'Continue?',
                'choices': ['Yes', 'No'],
                'multi_select': False,
                'allow_free_text': False,
            },
        }])

        session = self._prepare_model_request(
            session=session,
            body='Forget that and answer this instead',
        )

        self.assertFalse(session.pending_tool_call)
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertNotEqual(session.request_uuid, first_request_uuid)
        self.assertEqual(session.request_round, 1)
        refused_result = session.event_ids.sorted('id')[-2].metadata['content'][0]
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
        session = self._prepare_model_request(snapshot=initial_snapshot)
        first_request_uuid = session.request_uuid
        first_context = self._context_part(
            copy.deepcopy(session.request_payload),
        )
        automatic = self._apply_iap_tool_calls(session, first_request_uuid, [
            self._tool_call(ordinary_tool, 'ordinary'),
        ])
        self.assertEqual(self._context_part(session.request_payload), first_context)
        self.assertEqual(session.request_context, initial_snapshot)
        self.assertEqual(automatic['prepared']['session_id'], session.id)
        self.assertEqual(automatic['prepared']['request_uuid'], session.request_uuid)

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
        paused_session = self._prepare_model_request(
            session=paused_session,
            channel=channel,
            body='Pause first',
            snapshot=initial_snapshot,
        )
        paused_request_uuid = paused_session.request_uuid
        self._apply_iap_tool_calls(paused_session, paused_request_uuid, [
            self._tool_call(confirmation, 'confirmation'),
        ])
        self.assertEqual(paused_session.request_context, initial_snapshot)
        fresh_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            'current_view_info': {'marker': 'resumed'},
        }
        fresh_session = paused_session.with_context(**fresh_snapshot)
        resumed = self._resume_pending_interaction(
            fresh_session,
            paused_request_uuid,
            fresh_session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
            context_snapshot=fresh_snapshot,
        )

        self.assertEqual(resumed['prepared']['session_id'], paused_session.id)
        self.assertEqual(fresh_session.request_context, fresh_snapshot)
        self.assertIn('resumed', str(self._context_part(fresh_session.request_payload)))

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
                session = self._prepare_model_request(
                    session=session, channel=channel, body=f'Test {variant}',
                )
                request_uuid = session.request_uuid
                bad_call = self._tool_call(failing, 'bad')
                if variant == 'unknown':
                    bad_call['name'] = 'callback_unknown_tool'
                result = {
                    'kind': 'success',
                    'message': {
                        'role': 'assistant',
                        'provider_metadata': {},
                        'content': [
                            self._tool_call(successful, 'good'),
                            bad_call,
                        ],
                    },
                }

                outcome = self._apply_iap_result(session, request_uuid, result)
                followup_uuid = session.request_uuid
                results = self._tool_results(session.request_payload)
                counts = (
                    len(session.event_ids),
                    len(session.channel_id.message_ids),
                )

                self.assertTrue(results[0]['success'])
                self.assertFalse(results[1]['success'])
                self.assertEqual(session.state['successful_runs'], 1)
                self.assertEqual(outcome['prepared']['request_uuid'], followup_uuid)
                self._apply_iap_result(session, followup_uuid, {
                    'kind': 'success',
                    'message': assistant_text('The tool failed, so nothing else was changed.'),
                })
                self._apply_iap_result(session, request_uuid, result)
                self.assertEqual(session.state['successful_runs'], 1)
                self.assertEqual(counts[0] + 1, len(session.event_ids))
                self.assertEqual(counts[1] + 1, len(session.channel_id.message_ids))
                self.assertEqual(session.loop_state, 'ready')
                self.assertFalse(session.request_uuid)

    def test_later_tool_clears_an_earlier_tool_owned_final(self):
        final_tool = self._create_tool(
            'callback_owned_final',
            """
ai['final_message'] = [{'type': 'text', 'text': 'Owned final response'}]
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        waiting = self._apply_iap_tool_calls(session, request_uuid, [
            self._tool_call(final_tool, 'owned-final'),
            self._tool_call(confirmation, 'confirmation'),
        ])
        self.assertEqual(waiting['response']['responseState'], 'waiting_user')

        finished = self._resume_pending_interaction(
            session,
            request_uuid,
            session.resume_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )

        self.assertEqual(finished['response']['responseState'], 'running')
        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertEqual(finished['prepared']['session_id'], session.id)
        self.assertNotEqual(session.request_uuid, request_uuid)
        self.assertFalse(any(
            'Owned final response' in str(message.body)
            for message in session.channel_id.message_ids
        ))

        failure_channel, failure_session = self._new_session(
            'Callback failed sibling final',
        )
        failure_session.state = {'available_tools': final_tool.ids}
        failure_session = self._prepare_model_request(
            session=failure_session,
            channel=failure_channel,
            body='Suppress a final after a failure',
        )
        failure_uuid = failure_session.request_uuid
        failure_outcome = self._apply_iap_tool_calls(failure_session, failure_uuid, [
            self._tool_call(final_tool, 'candidate-final'),
            {
                'type': 'tool_call',
                'call_id': 'failed-sibling',
                'name': 'callback_missing_sibling',
                'args': {},
            },
        ])
        self.assertEqual(failure_outcome['response']['responseState'], 'running')
        self.assertFalse(
            self._tool_results(failure_session.request_payload)[1]['success'],
        )
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
        suffix_session = self._prepare_model_request(
            session=suffix_session,
            channel=suffix_channel,
            body='Carry preview markup to the final round',
        )
        suffix_uuid = suffix_session.request_uuid
        suffix_outcome = self._apply_iap_tool_calls(suffix_session, suffix_uuid, [
            self._tool_call(suffix_tool, 'suffix'),
        ])
        followup_uuid = suffix_session.request_uuid
        self.assertEqual(suffix_outcome['prepared']['request_uuid'], followup_uuid)
        self.assertIn(
            'callback-round-suffix', suffix_session.request_message_body_suffix,
        )
        self._apply_iap_result(suffix_session, followup_uuid, {
            'kind': 'success',
            'message': assistant_text('Final after preview'),
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
        session = self._prepare_model_request()
        request_uuid = session.request_uuid
        result = {
            'kind': 'success',
            'message': {
                'role': 'assistant',
                'provider_metadata': {},
                'content': [self._tool_call(tool, 'limit')],
            },
        }
        outcome = self._apply_iap_result(session, request_uuid, result)
        message_count = len(session.channel_id.message_ids)
        replay = self._apply_iap_result(session, request_uuid, result)
        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertEqual(replay['response']['responseState'], 'idle')
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertIn('too many successive tool rounds', session.channel_id.message_ids[0].body)
        self.assertEqual(len(session.channel_id.message_ids), message_count)

        for error_code in ('request_failed', 'insufficient_credit'):
            with self.subTest(error_code=error_code):
                channel, error_session = self._new_session(
                    f'Callback terminal {error_code}',
                )
                error_session = self._prepare_model_request(
                    session=error_session,
                    channel=channel,
                    body='Trigger a terminal error',
                )
                error_request_uuid = error_session.request_uuid
                error_result = {
                    'kind': 'failure',
                    'code': error_code,
                }
                with patch.object(
                    self.env.registry['iap.account'],
                    '_send_no_credit_notification',
                    autospec=True,
                ) as notify:
                    self._apply_iap_result(error_session, error_request_uuid, error_result)
                    error_message_count = len(error_session.channel_id.message_ids)
                    self._apply_iap_result(error_session, error_request_uuid, error_result)
                self.assertEqual(error_session.loop_state, 'ready')
                self.assertFalse(error_session.request_uuid)
                self.assertIn('AI is unreachable', error_session.channel_id.message_ids[0].body)
                self.assertEqual(
                    len(error_session.channel_id.message_ids), error_message_count,
                )
                self.assertEqual(
                    notify.call_count,
                    1 if error_code == 'insufficient_credit' else 0,
                )

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

    def _loop_snapshot(self):
        return self.session.read([
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

    def test_channel_title_and_agent_wrapper_remain_direct(self):
        loop_snapshot = self._loop_snapshot()
        completions = [
            {'status': 'success', 'result': assistant_text('Direct title')},
            {'status': 'success', 'result': assistant_text('Direct answer')},
        ]
        with patch.object(AiSession, '_get_completions', side_effect=completions):
            title = self.session._generate_channel_name([
                {'type': 'text', 'text': 'Name this chat'},
            ])
            answer = self.agent._generate_single_response([
                {'type': 'text', 'text': 'Answer directly'},
            ])

        self.assertEqual(title, 'Direct title')
        self.assertEqual(answer, assistant_text('Direct answer')['content'])
        self.assertEqual(self._loop_snapshot(), loop_snapshot)

    def test_server_action_and_structured_field_call_the_direct_engine(self):
        loop_snapshot = self._loop_snapshot()
        partner = self.env['res.partner'].create({'name': 'Direct input'})
        action = self.env['ir.actions.server'].create({
            'name': 'Direct parity action',
            'model_id': self.env['ir.model']._get_id('res.partner'),
            'state': 'ai',
            'ai_action_prompt': 'Summarize this contact.',
            'ai_tool_ids': [Command.set([
                self.env.ref('ai.ir_actions_server_search').id,
            ])],
        })
        structured = [{
            'type': 'text',
            'text': (
                '{"value": "Generated", "could_not_resolve": false, '
                '"unresolved_cause": null}'
            ),
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
        self.assertEqual(self._loop_snapshot(), loop_snapshot)

    def test_nested_web_search_and_image_generation_remain_direct(self):
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
        session._prepare_model_request(
            message._convert_to_parts(),
            context_snapshot={
                'active_company_ids': company_ids,
                'allowed_company_ids': company_ids,
            },
        )
        request_uuid = session.request_uuid
        event_count = len(session.event_ids)
        completions = [
            {'status': 'success', 'result': assistant_text('Search result')},
            {'status': 'success', 'result': assistant_text('Need more detail')},
        ]
        with patch.object(
            AiSession, '_get_completions', side_effect=completions,
        ) as direct_completion:
            outcome = session._apply_iap_result(request_uuid, {
                'kind': 'success',
                'message': {
                    'role': 'assistant',
                    'provider_metadata': {},
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

        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertEqual(session.loop_state, 'ready')
        self.assertFalse(session.request_uuid)
        self.assertEqual(direct_completion.call_count, 2)
        self.assertEqual(len(session.event_ids), event_count + 2)
        tool_results = session.event_ids.sorted('id')[-1].metadata['content']
        self.assertEqual(
            [part['tool_call_id'] for part in tool_results],
            ['nested-web-search', 'nested-image-generation'],
        )
        self.assertTrue(all(part['success'] for part in tool_results))
        self.assertIn('Need more detail', session.channel_id.message_ids[0].body)
