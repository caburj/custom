import json
from textwrap import dedent
from unittest.mock import MagicMock, patch

from odoo import api
from odoo.modules.registry import Registry
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.ai.models.ai_session import AiSession as EnterpriseAiSession
from odoo.addons.ai.utils.ai_utils import UserInputResponse
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
        )
        return session, session._prepare_callback_request(message._convert_to_parts())

    @staticmethod
    def _capture(events):
        def capture(session, event_type, payload, **kwargs):
            events.append((event_type, payload, kwargs))
            return True
        return capture

    def _create_callback_tool(self, name, code):
        return self.env['ir.actions.server'].create({
            'name': name,
            'ai_tool_name': name,
            'ai_tool_thinking_text': f'Running {name}',
            'ai_tool_description': 'AI Debug committed callback fixture.',
            'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
            'model_id': self.env.ref('ai.model_ai_tool').id,
            'state': 'code',
            'use_in_ai': True,
            'code': code,
        })

    @staticmethod
    def _tool_result(tool, call_id, args=None):
        return {
            'role': 'assistant',
            'content': [{
                'type': 'tool_call',
                'call_id': call_id,
                'name': tool.ai_tool_name,
                'args': args or {},
            }],
        }

    def test_callback_trace_is_correlated_terminal_and_replay_safe(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare()
            session._apply_iap_submit_response(request, {
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
            applied = session._apply_iap_result(request, result)
            event_count = len(events)
            replay = session._apply_iap_result(request, result)

        self.assertEqual(applied['responseState'], 'idle')
        self.assertEqual(replay['responseState'], 'idle')
        self.assertEqual(len(events), event_count)
        self.assertEqual(len(session.channel_id.message_ids), message_count + 1)
        self.assertIn('Visible callback reply', session.channel_id.message_ids[0].body)
        self.assertEqual([event for event, _payload, _kwargs in events].count('new_trace'), 1)
        self.assertEqual([event for event, _payload, _kwargs in events].count('iteration'), 1)
        self.assertEqual([event for event, _payload, _kwargs in events].count('loop_end'), 1)
        exchange_uuid = request.context_snapshot['ai_debug_exchange_uuid']
        trace = next(payload for event, payload, _kwargs in events if event == 'new_trace')
        self.assertEqual(trace['session_id'], session.id)
        self.assertEqual(trace['exchange_uuid'], exchange_uuid)
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
        self.assertEqual(terminal['trace_id'], exchange_uuid)
        self.assertEqual(terminal['exchange_uuid'], exchange_uuid)
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
        self.assertNotIn('tool_call_count', loop_end)
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
            session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': assistant_text('No metadata result'),
            })

        iteration = next(payload for event, payload, _kwargs in events if event == 'iteration')
        self.assertIsNone(iteration['provider'])
        self.assertIsNone(iteration['model_name'])
        self.assertIsNone(iteration['provider_api'])
        self.assertNotIn('tokens', iteration)

    def test_callback_rounds_share_one_trace_and_close_once(self):
        events = []
        intermediate_result = {
            'status': 'success',
            'result': assistant_text('Intermediate round'),
        }
        final_result = {
            'status': 'success',
            'result': assistant_text('Final round'),
        }

        def apply_intermediate(enterprise_session, request, _response):
            request._transition('done')
            next_request = enterprise_session._prepare_callback_request(
                previous_request=request,
                tools_context=enterprise_session._build_tools_context(),
            )
            return {
                'request_uuid': request.request_uuid,
                'responseState': 'running',
                'next_request_id': next_request.id,
            }

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, first_request = self._prepare('Use two rounds')
            session._apply_iap_submit_response(first_request, {
                'request_uuid': first_request.request_uuid,
                'status': 'queued',
            })
            intermediate_result['request_uuid'] = first_request.request_uuid
            with patch.object(
                EnterpriseAiSession,
                '_apply_iap_result',
                new=apply_intermediate,
            ):
                first_outcome = session._apply_iap_result(
                    first_request, intermediate_result,
                )

            second_request = self.env['ai.session.request'].browse(
                first_outcome['next_request_id']
            )
            session._apply_iap_submit_response(second_request, {
                'request_uuid': second_request.request_uuid,
                'status': 'queued',
            })
            final_result['request_uuid'] = second_request.request_uuid
            session._apply_iap_result(second_request, final_result)

        exchange_uuid = first_request.context_snapshot['ai_debug_exchange_uuid']
        self.assertEqual(
            second_request.context_snapshot['ai_debug_exchange_uuid'],
            exchange_uuid,
        )
        self.assertEqual(second_request.round_no, 2)
        self.assertNotEqual(first_request.request_uuid, second_request.request_uuid)
        self.assertEqual(
            [event for event, _payload, _kwargs in events].count('new_trace'), 1,
        )
        iterations = [
            payload for event, payload, _kwargs in events if event == 'iteration'
        ]
        self.assertEqual(
            [iteration['request_uuid'] for iteration in iterations],
            [first_request.request_uuid, second_request.request_uuid],
        )
        self.assertEqual(
            [iteration['round_no'] for iteration in iterations], [1, 2],
        )
        self.assertEqual(
            [iteration['trace_id'] for iteration in iterations],
            [exchange_uuid, exchange_uuid],
        )
        self.assertEqual(
            [iteration['is_final'] for iteration in iterations], [False, True],
        )
        loop_ends = [
            payload for event, payload, _kwargs in events if event == 'loop_end'
        ]
        self.assertEqual(len(loop_ends), 1)
        self.assertEqual(loop_ends[0]['trace_id'], exchange_uuid)
        self.assertEqual(loop_ends[0]['request_uuid'], second_request.request_uuid)
        self.assertEqual(loop_ends[0]['iteration_count'], 2)

    def test_real_callback_tool_events_follow_the_authoritative_iteration(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_tool',
            "ai['result'] = 'callback tool executed'",
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Run the callback tool')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            outcome = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': self._tool_result(tool, 'real-tool-call'),
            })
            event_count = len(events)
            session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': self._tool_result(tool, 'real-tool-call'),
            })

        self.assertEqual(outcome['responseState'], 'running')
        self.assertTrue(outcome['next_request_id'])
        self.assertEqual(len(events), event_count)
        relevant_events = [
            event for event, _payload, _kwargs in events
            if event in ('iteration', 'tool_call_started', 'tool_call_completed')
        ]
        self.assertEqual(relevant_events, [
            'iteration', 'tool_call_started', 'tool_call_completed',
        ])
        started = next(
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        )
        completed = next(
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        )
        exchange_uuid = request.context_snapshot['ai_debug_exchange_uuid']
        self.assertEqual(started['trace_id'], exchange_uuid)
        self.assertEqual(started['iteration_id'], request.request_uuid)
        self.assertEqual(started['request_uuid'], request.request_uuid)
        self.assertEqual(started['round_no'], 1)
        self.assertEqual(started['call_id'], 'real-tool-call')
        self.assertEqual(started['tool_call_id'], completed['tool_call_id'])
        self.assertTrue(completed['success'])
        self.assertIn('callback tool executed', str(completed['result']))
        self.assertNotIn('tool_call_count', completed)
        self.assertFalse(any(event == 'loop_end' for event, _payload, _kwargs in events))

    def test_callback_tool_events_are_not_flushed_when_parent_application_fails(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_rollback_tool',
            "ai['result'] = 'must roll back'",
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Roll back the callback tool')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            event_count = len(events)
            with (
                patch.object(
                    EnterpriseAiSession,
                    '_prepare_callback_request',
                    side_effect=RuntimeError('parent application fixture failure'),
                ),
                self.assertRaises(RuntimeError),
                self.env.cr.savepoint(),
            ):
                session._apply_iap_result(request, {
                    'request_uuid': request.request_uuid,
                    'status': 'success',
                    'result': self._tool_result(tool, 'rolled-back-tool-call'),
                })

        self.env.invalidate_all()
        request = self.env['ai.session.request'].browse(request.id)
        self.assertEqual(len(events), event_count)
        self.assertEqual(request.state, 'waiting_iap')

    def test_real_sequential_confirmations_reuse_tool_identity_without_new_iteration(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_confirmation_tool',
            dedent("""
                if not ai['tool_request_confirmed']:
                    ai['user_input_request'] = {
                        'type': 'confirmation',
                        'body': 'Run this callback fixture?',
                        'choices': [
                            {'label': 'Yes', 'value': 'confirm_once'},
                            {'label': 'Always', 'value': 'auto_confirm'},
                            {'label': 'No', 'value': 'decline'},
                        ],
                    }
                else:
                    ai['state']['confirmed_runs'] = (
                        ai['state'].get('confirmed_runs', 0) + 1
                    )
                    ai['result'] = 'confirmed callback tool'
            """),
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Confirm both callback tools')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            waiting = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': {
                    'role': 'assistant',
                    'content': [
                        self._tool_result(tool, 'confirm-first')['content'][0],
                        self._tool_result(tool, 'confirm-second')['content'][0],
                    ],
                },
            })
            first_resume_token = request.resume_token
            waiting_again = session._resume_callback_tool(
                request,
                first_resume_token,
                {'value': UserInputResponse.CONFIRM_ONCE},
            )
            second_resume_token = request.resume_token
            fresh_context_snapshot = {
                'active_company_ids': self.env.companies.ids,
                'allowed_company_ids': self.env.companies.ids,
                'current_view_info': {'view_type': 'list'},
                'ai_debug_exchange_uuid': 'untrusted-browser-value',
            }
            outcome = session._resume_callback_tool(
                request,
                second_resume_token,
                {'value': UserInputResponse.CONFIRM_ONCE},
                context_snapshot=fresh_context_snapshot,
            )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(waiting_again['responseState'], 'waiting_user')
        self.assertNotEqual(first_resume_token, second_resume_token)
        self.assertEqual(outcome['responseState'], 'running')
        self.assertEqual(request.state, 'done')
        self.assertEqual(session.state['confirmed_runs'], 2)
        next_request = self.env['ai.session.request'].browse(
            outcome['next_request_id']
        )
        self.assertEqual(
            next_request.context_snapshot['ai_debug_exchange_uuid'],
            request.context_snapshot['ai_debug_exchange_uuid'],
        )
        self.assertEqual(
            next_request.context_snapshot['current_view_info'],
            {'view_type': 'list'},
        )
        self.assertEqual(
            fresh_context_snapshot['ai_debug_exchange_uuid'],
            'untrusted-browser-value',
        )

        iterations = [
            payload for event, payload, _kwargs in events if event == 'iteration'
        ]
        self.assertEqual(len(iterations), 1)
        self.assertEqual(iterations[0]['iteration_id'], request.request_uuid)
        started = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        ]
        completed = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        ]
        self.assertEqual(
            [payload['call_id'] for payload in started],
            ['confirm-first', 'confirm-second'],
        )
        self.assertEqual(
            [payload['call_id'] for payload in completed],
            ['confirm-first', 'confirm-first', 'confirm-second', 'confirm-second'],
        )
        started_ids = {
            payload['call_id']: payload['tool_call_id'] for payload in started
        }
        self.assertEqual(
            [payload['tool_call_id'] for payload in completed],
            [
                started_ids['confirm-first'],
                started_ids['confirm-first'],
                started_ids['confirm-second'],
                started_ids['confirm-second'],
            ],
        )
        self.assertEqual(
            [payload['triggered_confirmation'] for payload in completed],
            [True, False, True, False],
        )
        self.assertEqual(
            [payload['success'] for payload in completed],
            [None, True, None, True],
        )
        self.assertFalse(any(event == 'loop_end' for event, _payload, _kwargs in events))

    def test_callback_question_completes_the_pending_tool_without_new_iteration(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_question_tool',
            dedent("""
                ai['user_input_request'] = {
                    'type': 'question',
                    'body': 'Which status should be used?',
                    'choices': [
                        {'label': 'Draft', 'value': 'draft'},
                        {'label': 'Posted', 'value': 'posted'},
                    ],
                    'multi_select': False,
                    'allow_free_text': False,
                }
            """),
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Ask a structured question')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            waiting = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': self._tool_result(tool, 'question-tool-call'),
            })
            outcome = session._resume_callback_tool(
                request,
                request.resume_token,
                {'values': ['draft']},
            )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(outcome['responseState'], 'running')
        self.assertTrue(outcome['next_request_id'])
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        self.assertEqual(
            [event for event, _payload, _kwargs in events].count('iteration'), 1,
        )
        started = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        ]
        completed = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        ]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)
        self.assertEqual(started[0]['tool_call_id'], completed[0]['tool_call_id'])
        self.assertEqual(completed[0]['call_id'], 'question-tool-call')
        self.assertTrue(completed[0]['success'])
        self.assertIn('USER ANSWER: draft', str(completed[0]['result']))
        self.assertFalse(completed[0]['triggered_confirmation'])
        self.assertFalse(any(event == 'loop_end' for event, _payload, _kwargs in events))

    def test_callback_client_tool_result_completes_the_pending_tool(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_client_tool',
            dedent("""
                ai['result'] = {
                    'client_tool': {
                        'name': 'get_client_data',
                        'params': {'key': 'fixture'},
                    },
                }
            """),
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Run a result-bearing client tool')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            waiting = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': self._tool_result(tool, 'client-tool-call'),
            })
            pending_client_tool = session.pending_tool_call['client_tool']
            outcome = session._resume_callback_tool(
                request,
                request.resume_token,
                {'result': {'client_value': 42}},
            )

        self.assertEqual(waiting['responseState'], 'waiting_client')
        self.assertEqual(pending_client_tool, {
            'name': 'get_client_data',
            'params': {'key': 'fixture'},
        })
        self.assertEqual(outcome['responseState'], 'running')
        self.assertTrue(outcome['next_request_id'])
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        self.assertEqual(
            [event for event, _payload, _kwargs in events].count('iteration'), 1,
        )
        started = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        ]
        completed = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        ]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)
        self.assertEqual(started[0]['tool_call_id'], completed[0]['tool_call_id'])
        self.assertEqual(completed[0]['call_id'], 'client-tool-call')
        self.assertTrue(completed[0]['success'])
        self.assertIn('client_value', str(completed[0]['result']))
        self.assertFalse(completed[0]['triggered_confirmation'])
        self.assertFalse(any(event == 'loop_end' for event, _payload, _kwargs in events))

    def test_skipped_callback_question_closes_the_pending_tool_and_trace(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_callback_skipped_question_tool',
            dedent("""
                ai['user_input_request'] = {
                    'type': 'question',
                    'body': 'Which optional status should be used?',
                    'choices': [
                        {'label': 'Draft', 'value': 'draft'},
                        {'label': 'Posted', 'value': 'posted'},
                    ],
                    'multi_select': False,
                    'allow_free_text': False,
                }
            """),
        )
        self.session.state = {'available_tools': [tool.id]}

        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Skip a structured question')
            session._apply_iap_submit_response(request, {
                'request_uuid': request.request_uuid,
                'status': 'queued',
            })
            waiting = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': self._tool_result(tool, 'skipped-question-tool-call'),
            })
            outcome = session._resume_callback_tool(
                request,
                request.resume_token,
                {'skip': True},
            )

        self.assertEqual(waiting['responseState'], 'waiting_user')
        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(request.state, 'done')
        self.assertFalse(session.pending_tool_call)
        started = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        ]
        completed = [
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        ]
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)
        self.assertEqual(started[0]['tool_call_id'], completed[0]['tool_call_id'])
        self.assertEqual(completed[0]['call_id'], 'skipped-question-tool-call')
        self.assertFalse(completed[0]['success'])
        self.assertEqual(completed[0]['result'], 'Question skipped by user')
        self.assertFalse(completed[0]['triggered_confirmation'])
        self.assertEqual(
            [event for event, _payload, _kwargs in events].count('loop_end'), 1,
        )

    def test_provider_error_details_are_not_exported(self):
        events = []
        provider_error = 'provider body carried authorization=secret-fixture'
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Fail safely')
            outcome = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'error',
                'error': provider_error,
            })

        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(request.state, 'failed')
        iteration = next(
            payload for event, payload, _kwargs in events if event == 'iteration'
        )
        self.assertEqual(iteration['error'], 'request_failed')
        self.assertEqual(iteration['raw_response']['error'], 'request_failed')
        loop_end = next(
            payload for event, payload, _kwargs in events if event == 'loop_end'
        )
        self.assertEqual(loop_end['error'], 'request_failed')
        self.assertNotIn(provider_error, json.dumps(events))

    def test_malformed_result_traces_committed_terminal_failure(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Malformed result')
            outcome = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': [],
            })

        self.assertEqual(outcome['responseState'], 'idle')
        self.assertEqual(request.state, 'failed')
        iteration = next(
            payload for event, payload, _kwargs in events if event == 'iteration'
        )
        self.assertEqual(iteration['request_state'], 'failed')
        self.assertEqual(iteration['error'], 'request_failed')
        self.assertEqual(iteration['raw_response'], {
            'request_uuid': request.request_uuid,
            'status': 'success',
        })
        loop_end = next(
            payload for event, payload, _kwargs in events if event == 'loop_end'
        )
        self.assertEqual(loop_end['termination_reason'], 'error')
        self.assertEqual(loop_end['error'], 'request_failed')

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
            applied = session._apply_iap_result(request, {
                'request_uuid': request.request_uuid,
                'status': 'success',
                'result': assistant_text('Still visible'),
            })

        self.assertEqual(applied['responseState'], 'idle')
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

    def test_request_create_preserves_copied_exchange_uuid_without_lookup(self):
        copied_snapshot = {
            'ai_debug_exchange_uuid': 'copied-exchange-fixture',
            'active_company_ids': self.env.companies.ids,
        }
        with patch(
            'odoo.addons.ai_debug.models.ai_session_request.uuid.uuid4'
        ) as generate_uuid:
            request = self.env['ai.session.request'].sudo().create({
                'session_id': self.session.id,
                'request_uuid': 'copied-request-fixture',
                'round_no': 2,
                'round_limit': 3,
                'payload': {'messages': [], 'instructions': [], 'tools': []},
                'user_id': self.env.user.id,
                'context_snapshot': copied_snapshot,
            })

        generate_uuid.assert_not_called()
        self.assertEqual(
            request.context_snapshot['ai_debug_exchange_uuid'],
            'copied-exchange-fixture',
        )
        self.assertEqual(
            copied_snapshot['ai_debug_exchange_uuid'],
            'copied-exchange-fixture',
        )

    def test_non_dict_and_omitted_snapshots_bypass_exchange_injection(self):
        Request = self.env['ai.session.request'].sudo()
        common_vals = {
            'session_id': self.session.id,
            'round_no': 2,
            'round_limit': 3,
            'payload': {'messages': [], 'instructions': [], 'tools': []},
            'user_id': self.env.user.id,
        }
        non_dict_snapshot = [{'marker': 'preserved'}]
        non_dict_vals = {
            **common_vals,
            'request_uuid': 'non-dict-snapshot-request-fixture',
            'context_snapshot': non_dict_snapshot,
        }
        omitted_vals = {
            **common_vals,
            'request_uuid': 'omitted-snapshot-request-fixture',
        }
        with patch(
            'odoo.addons.ai_debug.models.ai_session_request.uuid.uuid4'
        ) as generate_uuid:
            self.assertIs(
                Request._ai_debug_prepare_create_vals(non_dict_vals),
                non_dict_vals,
            )
            self.assertIs(
                Request._ai_debug_prepare_create_vals(omitted_vals),
                omitted_vals,
            )
            non_dict_request = Request.create(non_dict_vals)

        generate_uuid.assert_not_called()
        self.assertEqual(non_dict_request.context_snapshot, non_dict_snapshot)
        self.assertEqual(
            self.session._ai_debug_exchange_uuid(non_dict_request),
            non_dict_request.request_uuid,
        )
        omitted_request = MagicMock(
            context_snapshot=None,
            request_uuid='omitted-snapshot-request-fixture',
        )
        self.assertEqual(
            self.session._ai_debug_exchange_uuid(omitted_request),
            omitted_request.request_uuid,
        )

    def test_exchange_uuid_injection_failure_does_not_block_request_create(self):
        original_snapshot = {'active_company_ids': self.env.companies.ids}
        with patch(
            'odoo.addons.ai_debug.models.ai_session_request.uuid.uuid4',
            side_effect=RuntimeError('uuid fixture failure'),
        ):
            request = self.env['ai.session.request'].sudo().create({
                'session_id': self.session.id,
                'request_uuid': 'uninstrumented-request-fixture',
                'round_no': 2,
                'round_limit': 3,
                'payload': {'messages': [], 'instructions': [], 'tools': []},
                'user_id': self.env.user.id,
                'context_snapshot': original_snapshot,
            })

        self.assertEqual(request.state, 'prepared')
        self.assertEqual(request.context_snapshot, original_snapshot)
        self.assertNotIn('ai_debug_exchange_uuid', request.context_snapshot)

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

    def test_channel_name_direct_trace_keeps_session_and_agent_identity(self):
        events = []
        request_count = self.env['ai.session.request'].sudo().search_count([])
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={
                'status': 'success',
                'result': assistant_text('Callback observability'),
            }),
        ):
            title = self.session._generate_channel_name([
                {'type': 'text', 'content': {'data': 'Trace this live chat'}},
            ])

        self.assertEqual(title, 'Callback observability')
        trace = next(
            payload for event, payload, _kwargs in events
            if event == 'new_trace'
        )
        self.assertEqual(trace['session_id'], self.session.id)
        self.assertEqual(trace['agent_name'], self.agent.name)
        self.assertEqual(trace['trace_kind'], 'channel_name')
        self.assertEqual(trace['trace_label'], 'Conversation Title')
        self.assertEqual(
            [event for event, _payload, _kwargs in events],
            ['new_trace', 'iteration', 'loop_end'],
        )
        self.assertEqual(
            self.env['ai.session.request'].sudo().search_count([]), request_count,
        )

    def test_direct_sync_tool_tracing_keeps_its_existing_event_contract(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_direct_tool',
            "ai['result'] = 'direct tool executed'",
        )
        request_count = self.env['ai.session.request'].sudo().search_count([])
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', side_effect=[
                {
                    'status': 'success',
                    'result': self._tool_result(tool, 'direct-tool-call'),
                },
                {
                    'status': 'success',
                    'result': assistant_text('Direct tool result'),
                },
            ]),
        ):
            result = self.env['ai.session']._get_direct_response(
                instructions='Use the tool.',
                message=[{'type': 'text', 'content': {'data': 'Run it'}}],
                tools=tool,
            )

        self.assertEqual(result, assistant_text('Direct tool result')['content'])
        self.assertEqual(
            [event for event, _payload, _kwargs in events],
            [
                'new_trace', 'iteration', 'tool_call_started',
                'tool_call_completed', 'iteration', 'loop_end',
            ],
        )
        loop_end = events[-1][1]
        self.assertEqual(loop_end['tool_call_count'], 1)
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
        self.assertEqual(json.loads(row.channel), [
            self.env.cr.dbname, 'res.users', self.env.uid, 'ai_debug',
        ])
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

    def test_guest_callback_trace_uses_shared_internal_debugger_channel(self):
        guest = self.env['mail.guest'].create({'name': 'AI Debug Livechat Guest'})
        public_user = self.env.ref('base.public_user')
        request = self.env['ai.session.request'].sudo().create({
            'session_id': self.session.id,
            'request_uuid': 'guest-observer-request-fixture',
            'round_no': 1,
            'round_limit': 3,
            'payload': {
                'messages': [{
                    'role': 'user',
                    'content': [{
                        'type': 'text',
                        'content': {'data': 'Livechat observer fixture'},
                    }],
                }],
                'instructions': 'Answer the livechat guest.',
                'tools': [],
            },
            'user_id': public_user.id,
            'guest_id': guest.id,
            'context_snapshot': {},
        })

        exchange_uuid = request.context_snapshot['ai_debug_exchange_uuid']
        rows = self.env['bus.bus'].sudo().search([
            ('message', 'ilike', exchange_uuid),
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(json.loads(rows.channel), [self.env.cr.dbname, 'ai_debug'])
        message = json.loads(rows.message)
        self.assertEqual(message['type'], 'new_trace')
        self.assertEqual(message['payload']['request_uuid'], request.request_uuid)
        self.assertEqual(message['payload']['agent_name'], self.agent.name)

    def test_internal_user_can_subscribe_to_shared_and_private_debugger_channels(self):
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = self.env.uid
        with patch('odoo.addons.bus.models.ir_websocket.wsrequest', new=mock_wsrequest):
            channels = self.env['ir.websocket']._prepare_subscribe_data(
                ['ai_debug', 'other'], 0,
            )['channels']

        self.assertIn((self.env.cr.dbname, 'ai_debug'), channels)
        self.assertIn(
            (self.env.cr.dbname, 'res.users', self.env.uid, 'ai_debug'),
            channels,
        )
        self.assertIn(
            (self.env.cr.dbname, 'res.users', self.env.uid),
            channels,
        )

    def test_non_internal_user_cannot_subscribe_to_debugger_channel(self):
        portal = new_test_user(
            self.env,
            login='ai_debug_portal_subscription',
            groups='base.group_portal',
        )
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = portal.id
        with patch('odoo.addons.bus.models.ir_websocket.wsrequest', new=mock_wsrequest):
            channels = (
                self.env['ir.websocket']
                .with_user(portal)
                ._prepare_subscribe_data(['ai_debug', 'other'], 0)['channels']
            )

        self.assertNotIn((self.env.cr.dbname, 'ai_debug'), channels)
        self.assertNotIn(
            (self.env.cr.dbname, 'res.users', portal.id, 'ai_debug'),
            channels,
        )
        self.assertIn((self.env.cr.dbname, 'other'), channels)
        self.assertIn(
            (self.env.cr.dbname, 'res.users', portal.id),
            channels,
        )

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

    def test_debugger_page_mounts(self):
        self.browser_js(
            url_path='/ai-debug',
            code="console.log('test successful');",
            ready="document.querySelector('.ai-debug-header') !== null",
            login='admin',
        )
