import json
from textwrap import dedent
from unittest.mock import MagicMock, patch

from odoo import api, Command
from odoo.exceptions import ConcurrencyError
from odoo.modules.registry import Registry
from odoo.tests import HttpCase, TransactionCase, new_test_user, tagged

from odoo.addons.ai.models.ai_session import AiSession as EnterpriseAiSession
from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.ai_debug.models.ai_session import AiSession as DebugAiSession


def assistant_text(text, provider_metadata=None):
    message = {
        'role': 'assistant',
        'content': [{'type': 'text', 'text': text}],
    }
    if provider_metadata:
        message['provider_metadata'] = provider_metadata
    return message


class RequestSnapshot:
    """Test-only attribute view of one pre-reducer session request snapshot."""

    def __init__(self, session, values):
        self.session = session
        self.request_uuid = values['request_uuid']
        self.round_no = values['round_no']
        self.round_limit = values['round_limit']
        self.payload = values['payload']
        self.context_snapshot = values['context_snapshot']
        self.user_id = session.env['res.users'].browse(values['user_id'])
        self.guest_id = session.env['mail.guest'].browse(values['guest_id'])

    @property
    def resume_token(self):
        return self.session.resume_token


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

    def _prepare(self, body='Hi', **context_overrides):
        message = self.channel.message_post(body=body, message_type='comment')
        context_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'allowed_company_ids': self.env.companies.ids,
            **context_overrides,
        }
        session = self.session.with_context(**context_snapshot)
        session._submit_agent_request(
            message._convert_to_parts(),
        )
        return session, RequestSnapshot(
            session, session._ai_debug_request_snapshot(),
        )

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

    def _enable_fixture_tools(self, session, tools):
        # Core rebuilds available tools from the agent's linked, loaded skills.
        skill = self.env['ai.skill'].create({
            'name': 'AI Debug fixture tools', 'tool_ids': [Command.set(tools.ids)],
        })
        session.agent_id.skill_ids |= skill
        session.state = {'loaded_skills': skill.ids}

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

    def setUp(self):
        super().setUp()
        transport = patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None)
        self.transport = transport.start()
        self.addCleanup(transport.stop)

    def _consume(self, session, message):
        session._continue_agent_loop({'kind': 'success', 'message': message})

    def _events(self, events, kind, **matches):
        return [payload for event, payload, _kwargs in events
                if event == kind and all(payload.get(key) == value for key, value in matches.items())]

    def test_submission_callback_and_followup_keep_connected_traces(self):
        tool = self._create_callback_tool('debug_plain', "ai['result'] = 'Tool result'")
        self._enable_fixture_tools(self.session, tool)
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, first = self._prepare('Trace my message')
            self.transport.assert_not_called()
            self.assertEqual(session.state['callback_type'], 'agent_loop')
            self.assertEqual(self._events(events, 'iteration')[-1]['phase'], 'prepared')
            self._consume(session, self._tool_result(tool, 'one'))
            self.assertEqual(session.loop_state, 'waiting_model')
            self.assertNotEqual(session.request_uuid, first.request_uuid)
            self.assertEqual(session.request_context['ai_debug_exchange_uuid'], first.context_snapshot['ai_debug_exchange_uuid'])
            self._consume(session, assistant_text('The answer'))
        self.assertEqual(len(self._events(events, 'new_trace')), 1)
        self.assertEqual(len(self._events(events, 'tool_call_completed')), 1)
        terminal, = self._events(events, 'loop_end')
        self.assertIn('The answer', str(terminal['final_output']))
        self.assertEqual(terminal['termination_reason'], 'success')
        self.assertEqual([e['round_no'] for e in self._events(events, 'iteration', phase='result_received')], [1, 2])

    def test_combined_tool_final_preserves_completion_and_output(self):
        tool = self._create_callback_tool('ai_debug_combined_final',
            "ai['result'] = 'Tool result'\nai['final_message'] = [{'type': 'text', 'text': 'Tool final'}]")
        self._enable_fixture_tools(self.session, tool)
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Finish in the tool')
            self._consume(session, self._tool_result(tool, 'final'))
        self.assertEqual(session.loop_state, 'ready')
        completed = self._events(events, 'tool_call_completed')
        self.assertEqual(len(completed), 1)
        self.assertIn('Tool result', str(completed[0]['result']))
        self.assertIn('Tool final', str(self._events(events, 'loop_end')[0]['final_output']))
        events.clear()
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={
                'status': 'success', 'result': self._tool_result(tool, 'direct-final'),
            }) as completion,
        ):
            result = self.env['ai.session']._get_direct_response(
                instructions='Finish in the tool.', message=[{'type': 'text', 'text': 'Run'}], tools=tool,
            )
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(result, [{'type': 'text', 'text': 'Tool final'}])
        self.assertEqual(len(self._events(events, 'tool_call_completed')), 1)
        self.assertEqual(self._events(events, 'loop_end')[0]['termination_reason'], 'success')

        iterations = self._events(events, 'iteration')
        self.assertEqual(len(iterations), 2)
        self.assertNotEqual(iterations[0]['iteration_id'], iterations[1]['iteration_id'])
        self.assertIn('direct-final', str(iterations[0]['raw_response']))
        self.assertIn('Tool final', str(iterations[1]['raw_response']))
        self.assertIsNotNone(iterations[0]['request_body'])
        self.assertIsNone(iterations[1].get('request_body'))

    def test_business_flush_conflict_escapes_debugger_guard(self):
        observer = MagicMock()
        conflict = ConcurrencyError('Retry pending business work')
        with self.assertRaises(ConcurrencyError) as raised:
            with patch.object(type(self.env.cr), 'flush', side_effect=conflict):
                self.session._ai_debug_try(observer)
        self.assertIs(raised.exception, conflict)
        observer.assert_not_called()

    def test_failed_callback_closes_trace(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare()
            session._continue_agent_loop({'kind': 'failure', 'code': 'request_failed'})
        terminal, = self._events(events, 'loop_end')
        self.assertEqual(terminal['termination_reason'], 'failed')
        self.assertEqual(terminal['error'], 'request_failed')

    def test_pending_client_resume_and_new_exchange(self):
        tool = self._create_callback_tool('debug_client', "ai['result'] = {'client_tool': {'name': 'debug_client', 'params': {}}}")
        self._enable_fixture_tools(self.session, tool)
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, first = self._prepare()
            self._consume(session, self._tool_result(tool, 'client'))
            self.assertEqual(session.loop_state, 'waiting_client_result')
            session._resume_pending_interaction({'kind': 'client_result', 'value': False},
                                                ai_session_config={'enable_think_longer': True})
            self.assertTrue(session.request_payload['boost_reasoning'])
            completed, = self._events(events, 'tool_call_completed')
            self.assertTrue(completed['success'])
            self._consume(session, self._tool_result(tool, 'client-again'))
            session._abort_pending_tools()
            session._submit_agent_request([{'type': 'text', 'text': 'Another message'}])
        self.assertNotEqual(first.context_snapshot['ai_debug_exchange_uuid'], session.request_context['ai_debug_exchange_uuid'])
        terminal, = self._events(events, 'loop_end')
        self.assertEqual(terminal['termination_reason'], 'declined')

    def test_unchanged_event_context_refreshes_context_message_with_debug_metadata(self):
        tool = self._create_callback_tool('debug_context', "ai['result'] = 'Done'")
        self._enable_fixture_tools(self.session, tool)
        session, request = self._prepare('Keep current context')
        current = session.with_context(ai_debug_exchange_uuid='another-session',
                                       _ai_debug_parent_link={'parent_trace_id': 'another-session'})
        self.assertEqual(current._get_request_context_snapshot(), session.request_context)
        fresh_context = '<odoo_current_context>Fresh record data</odoo_current_context>'
        with patch.object(EnterpriseAiSession, '_get_context_input', return_value=fresh_context) as build_context:
            self._consume(current, self._tool_result(tool, 'unchanged'))
        build_context.assert_called_once_with(None)
        context_parts = [part['text'] for message in current.request_payload['messages'] for part in message['content']
                         if part['type'] == 'text' and part['text'].startswith('<odoo_current_context>')]
        self.assertEqual(context_parts, [fresh_context])
        self.assertEqual(current.request_context['ai_debug_exchange_uuid'], request.context_snapshot['ai_debug_exchange_uuid'])

    def test_subagent_delivery_and_reuse_link_to_ordinary_tools(self):
        self.agent.allowed_agent_ids = self.agent
        start = self.env.ref('ai.ir_actions_server_start_session')
        again = self.env.ref('ai.ir_actions_server_continue_session')
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            root, request = self._prepare('Delegate')
            self._consume(root, self._tool_result(start, 'start', {'agent_id': self.agent.id, 'message': 'Child task'}))
            child = self.env['ai.session'].search([('parent_session_id', '=', root.id)])
            self.assertEqual(len(child), 1)
            child_trace, = self._events(events, 'new_trace', session_id=child.id)
            self.assertEqual(child_trace['parent_tool_call_id'], root._ai_debug_callback_tool_call_id(request.request_uuid, 'start'))
            child_request = child.request_uuid
            loader = self.env.ref('ai.ir_actions_server_load_skills')
            self._consume(child, self._tool_result(loader, 'load-skill', {
                'skill_ids': [self.env.ref('ai.ai_skill_generate_image').id],
            }))
            self.assertNotEqual(child.request_uuid, child_request)
            self.assertEqual(child.request_context['_ai_debug_parent_link']['parent_request_uuid'], request.request_uuid)
            self.assertEqual(child.request_context['ai_debug_exchange_uuid'], child_trace['trace_id'])
            self.assertEqual(len(self._events(events, 'new_trace', session_id=child.id)), 1)
            self._consume(child, assistant_text('Child answer'))
            self.assertEqual(root.loop_state, 'waiting_model')
            terminal, = self._events(events, 'loop_end', trace_id=child_trace['trace_id'])
            self.assertIn('Child answer', terminal['exchange_result']['message'])
            self.assertIn('Child answer', str(terminal['final_output']))
            parent_request = root.request_uuid
            self._consume(root, self._tool_result(again, 'again', {'session_id': child.id, 'message': 'Another task'}))
            self._consume(child, assistant_text('Second answer'))
            traces = self._events(events, 'new_trace', session_id=child.id)
            self.assertEqual(len(traces), 2)
            self.assertNotEqual(traces[0]['trace_id'], traces[1]['trace_id'])
            self.assertEqual(traces[1]['parent_request_uuid'], parent_request)
            self.assertEqual(len(self._events(events, 'request_state', phase='child_applied')), 2)

    def test_channel_title_trace_closes_after_session_deletion(self):
        self.channel.name = ''
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            root, request = self._prepare()
            title = self.env['ai.session'].sudo().create({'parent_session_id': root.id})
            title._save_and_submit_request({'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Title'}]}],
                                           'instructions': 'Name it', 'tools': []}, callback_type='channel_name',
                                          request_round=1, request_round_limit=1, state={})
            title_id = title.id
            title._continue_channel_name({'kind': 'success', 'message': assistant_text('A good title')})
        self.assertFalse(title.exists())
        self.assertEqual(self.channel.name, 'A good title')
        trace, = self._events(events, 'new_trace', session_id=title_id)
        terminal, = self._events(events, 'loop_end', trace_id=trace['trace_id'])
        self.assertEqual(terminal['termination_reason'], 'success')

    def test_debugger_failures_do_not_break_business_requests(self):
        with patch.object(DebugAiSession, '_ai_debug_prepare_request_context', side_effect=RuntimeError('Observer failed')):
            session, request = self._prepare()
        self.assertEqual(session.loop_state, 'waiting_model')
        with patch.object(DebugAiSession, '_ai_debug_record_callback', side_effect=RuntimeError('Observer failed')):
            self._consume(session, assistant_text('Still answered'))
        self.assertEqual(session.loop_state, 'ready')
        self.assertIn('Still answered', session.channel_id.message_ids[0].body)

    def test_web_search_calls_are_nested_under_exact_callback_tools(self):
        tool = self.env.ref('ai.ir_actions_server_ai_web_search')
        self.session.enable_web_search = True
        events = []
        completion_contexts = []

        def complete(model, messages, instructions, tools=None, **options):
            completion_contexts.append(dict(model.env.context))
            return {'result': assistant_text('Found a source')}

        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', complete),
        ):
            parent, request = self._prepare('Search twice', current_view_info={'marker': 'current-page'})
            calls = [self._tool_result(tool, call_id, {'query': 'Odoo', 'retrieval_mode': 'summary'})['content'][0]
                     for call_id in ('search-first', 'search-second')]
            self._consume(parent, {'role': 'assistant', 'content': calls})
        traces = self._events(events, 'new_trace', trace_kind='web_search')
        self.assertEqual(len(traces), 2)
        for trace, call in zip(traces, calls):
            self.assertEqual(trace['parent_trace_id'], request.context_snapshot['ai_debug_exchange_uuid'])
            self.assertEqual(trace['parent_session_id'], parent.id)
            self.assertEqual(trace['parent_request_uuid'], request.request_uuid)
            self.assertEqual(trace['parent_tool_call_id'], parent._ai_debug_callback_tool_call_id(request.request_uuid, call['call_id']))
            iteration, = self._events(events, 'iteration', trace_id=trace['trace_id'])
            self.assertTrue(iteration['request_body']['web_grounding'])
            self.assertIn('Odoo', str(iteration['request_body']['messages']))
            self.assertIn('Found a source', str(iteration['raw_response']))
            terminal, = self._events(events, 'loop_end', trace_id=trace['trace_id'])
            self.assertEqual(terminal['termination_reason'], 'success')
        self.assertTrue(all(context['current_view_info'] == {'marker': 'current-page'} for context in completion_contexts))
        self.assertEqual(len(self._events(events, 'tool_call_completed')), 2)
        self.assertEqual(parent.loop_state, 'waiting_model')
        self.assertEqual(parent.request_context['ai_debug_exchange_uuid'], request.context_snapshot['ai_debug_exchange_uuid'])

    def test_direct_tool_parent_link_does_not_require_session_read_access(self):
        user = new_test_user(self.env, login='debug_tool_user', groups='base.group_user')
        events = []
        context = {
            '_ai_debug_callback_ctx': {'session_id': self.session.id, 'trace_id': 'root-trace',
                                       'request_uuid': 'root-request'},
            'ai_parent_trace_id': 'root-trace', 'ai_parent_tool_call_id': 'search-call',
            'allowed_company_ids': user.company_ids.ids, 'current_view_info': {'marker': 'page'},
        }
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={'result': assistant_text('Found')}),
        ):
            response = self.env['ai.session'].with_user(user).with_context(**context)._get_direct_response(
                instructions='Search', message=[{'type': 'text', 'text': 'Find it'}], usage='web_search',
            )
        self.assertEqual(response, assistant_text('Found')['content'])
        trace, = self._events(events, 'new_trace')
        self.assertEqual(trace['parent_session_id'], self.session.id)
        self.assertEqual(trace['parent_tool_call_id'], self.session._ai_debug_callback_tool_call_id('root-request', 'search-call'))

    def test_direct_sync_tracing_keeps_existing_event_contract(self):
        events = []
        callback_items = []
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={
                'status': 'success',
                'result': assistant_text('Direct result'),
            }),
        ):
            result = self.env['ai.session']._get_direct_response(
                instructions='Answer.',
                message=[{'type': 'text', 'text': 'Hi'}],
                on_item_callback=lambda item, _tools_context: callback_items.append(item),
            )

        self.assertEqual(result, assistant_text('Direct result')['content'])
        self.assertEqual(callback_items, [{
            'final_message': assistant_text('Direct result')['content'],
        }])
        self.assertEqual(
            [event for event, _payload, _kwargs in events],
            ['new_trace', 'iteration', 'loop_end'],
        )
        iteration = next(
            payload for event, payload, _kwargs in events
            if event == 'iteration'
        )
        self.assertEqual(
            iteration['raw_response'],
            [{
                'role': 'assistant',
                'content': [{
                    'type': 'text',
                    'content': {'data': 'Direct result'},
                }],
            }],
        )

    def test_channel_name_direct_trace_keeps_session_and_agent_identity(self):
        events = []
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch.object(EnterpriseAiSession, '_get_completions', return_value={
                'status': 'success',
                'result': assistant_text('Callback observability'),
            }),
        ):
            title = self.session._get_direct_response(
                instructions='Name this conversation.',
                message=[{'type': 'text', 'text': 'Trace this live chat'}],
                usage='channel_name',
            )

        self.assertEqual(title, assistant_text('Callback observability')['content'])
        trace = next(
            payload for event, payload, _kwargs in events
            if event == 'new_trace'
        )
        self.assertEqual(trace['session_id'], self.session.id)
        self.assertEqual(trace['agent_name'], self.agent.name)
        self.assertEqual(trace['trace_kind'], 'channel_name')
        self.assertEqual(trace['trace_label'], 'Conversation Title')
        iteration = next(
            payload for event, payload, _kwargs in events
            if event == 'iteration'
        )
        self.assertEqual(
            iteration['raw_response'],
            [{
                'role': 'assistant',
                'content': [{
                    'type': 'text',
                    'content': {'data': 'Callback observability'},
                }],
            }],
        )
        self.assertEqual(
            [event for event, _payload, _kwargs in events],
            ['new_trace', 'iteration', 'loop_end'],
        )

    def test_direct_sync_tool_tracing_keeps_its_existing_event_contract(self):
        events = []
        tool = self._create_callback_tool(
            'ai_debug_direct_tool',
            "ai['result'] = 'direct tool executed'",
        )
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
                message=[{'type': 'text', 'text': 'Run it'}],
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
        started = next(
            payload for event, payload, _kwargs in events
            if event == 'tool_call_started'
        )
        completed = next(
            payload for event, payload, _kwargs in events
            if event == 'tool_call_completed'
        )
        self.assertEqual(started['call_id'], 'direct-tool-call')
        self.assertEqual(completed['call_id'], 'direct-tool-call')
        self.assertEqual(completed['tool_name'], tool.ai_tool_name)
        self.assertEqual(completed['tool_call_id'], started['tool_call_id'])
        self.assertTrue(completed['success'])
        self.assertIn('direct tool executed', str(completed['result']))
        loop_end = events[-1][1]
        self.assertEqual(loop_end['tool_call_count'], 1)

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

        message = [{'type': 'text', 'text': 'Hi'}]
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
                'webhook_secret': 'webhook-secret',
                'signature': 'callback-signature',
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
        self.assertEqual(sanitized['nested']['webhook_secret'], '[REDACTED]')
        self.assertEqual(sanitized['nested']['signature'], '[REDACTED]')
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
                    'text': 'Visible text',
                    'sources': [{
                        'url': 'https://provider.invalid/file?signature=secret',
                    }],
                    'provider_data': {'thought_signature': 'opaque-signature'},
                },
                {
                    'type': 'inline_data',
                    'mimetype': 'image/png',
                    'data': 'iVBORw0KGg',
                },
                {
                    'type': 'inline_data',
                    'mimetype': 'application/pdf',
                    'data': 'pdf-bytes',
                },
                {
                    'type': 'tool_result',
                    'tool_name': 'fixture_tool',
                    'tool_call_id': 'fixture-call',
                    'result': [{'type': 'text', 'text': 'Tool result'}],
                    'success': True,
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
        self.assertNotIn('sources', normalized[0]['content'][0])
        self.assertNotIn('provider_data', normalized[0]['content'][0])
        self.assertEqual(
            normalized[0]['content'][1]['content']['data'],
            'data:image/png;base64,iVBORw0KGg',
        )
        self.assertTrue(normalized[0]['content'][2]['content']['_binary_excluded'])
        self.assertNotIn('data', normalized[0]['content'][2]['content'])
        self.assertEqual(normalized[0]['content'][3], {
            'type': 'tool_result',
            'tool_name': 'fixture_tool',
            'tool_call_id': 'fixture-call',
            'result': [{
                'type': 'text',
                'content': {'data': 'Tool result'},
            }],
            'success': True,
        })

        preview_data = 'A' * 47_000
        preview = self.session._ai_debug_normalized_messages([{
            'role': 'assistant',
            'content': [{
                'type': 'inline_data',
                'mimetype': 'image/png',
                'data': preview_data,
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
                'mimetype': 'image/png',
                'data': 'A' * 48_001,
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
            'parent_trace_id': 'parent-trace',
            'parent_request_uuid': 'parent-request',
            'parent_tool_call_id': 'parent-tool',
            'phase': 'result_received',
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
        self.assertEqual(oversized_payload['parent_tool_call_id'], 'parent-tool')
        self.assertEqual(oversized_payload['parent_request_uuid'], 'parent-request')
        self.assertEqual(oversized_payload['phase'], 'result_received')

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

    def test_guest_callback_trace_is_not_published_to_internal_users(self):
        public_user = self.env.ref('base.public_user')
        request = {
            'continuation_type': 'agent',
            'request_uuid': 'guest-observer-request-fixture',
            'round_no': 1,
            'round_limit': 3,
            'payload': {
                'messages': [{
                    'role': 'user',
                    'content': [{
                        'type': 'text',
                        'text': 'Livechat observer fixture',
                    }],
                }],
                'instructions': 'Answer the livechat guest.',
                'tools': [],
            },
            'user_id': public_user.id,
            'guest_id': False,
            'context_snapshot': {
                'ai_debug_exchange_uuid': 'guest-observer-exchange-fixture',
            },
            'loop_state': 'waiting_model',
            'request_phase': 'prepared',
        }
        bus = self.env['bus.bus'].sudo()
        before = bus.search_count([
            ('message', 'ilike', 'guest-observer-exchange-fixture'),
        ])

        queued = self.session._ai_debug_trace_request_prepared(request)

        self.assertFalse(queued)
        self.assertEqual(bus.search_count([
            ('message', 'ilike', 'guest-observer-exchange-fixture'),
        ]), before)

    def test_internal_user_subscribes_only_to_private_debugger_channel(self):
        mock_wsrequest = MagicMock()
        mock_wsrequest.session.uid = self.env.uid
        with patch('odoo.addons.bus.models.ir_websocket.wsrequest', new=mock_wsrequest):
            channels = self.env['ir.websocket']._prepare_subscribe_data(
                ['ai_debug', 'other'], 0,
            )['channels']

        self.assertNotIn((self.env.cr.dbname, 'ai_debug'), channels)
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
