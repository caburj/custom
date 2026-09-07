import json
from textwrap import dedent
from unittest.mock import MagicMock, patch

from odoo import api
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
        session._prepare_agent_request(
            message._convert_to_parts(),
        )
        return session, RequestSnapshot(
            session, session._ai_debug_request_snapshot(),
        )

    @staticmethod
    def _mark_submitted(session):
        session.request_phase = 'submitted'

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

    def _consume(self, session, message, request_uuid=None):
        request_uuid = request_uuid or session.request_uuid
        return session._continue(request_uuid, {'kind': 'success', 'message': message})

    def _events(self, events, kind, **matches):
        return [payload for event, payload, _kwargs in events
                if event == kind and all(payload.get(key) == value for key, value in matches.items())]

    def test_preparation_receipt_consumption_and_replay(self):
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare()
            self.assertEqual(len(self._events(events, 'new_trace')), 1)
            prepared = self._events(events, 'iteration', phase='prepared')[0]
            self.assertIsNone(prepared['raw_response'])
            self.assertEqual(prepared['request_body']['request_uuid'], request.request_uuid)
            with patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport:
                session._submit_prepared_request(request.request_uuid)
                session._submit_prepared_request(request.request_uuid)
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(len(self._events(events, 'request_state', phase='submitted')), 1)
            result = {'kind': 'success', 'message': assistant_text('Visible callback reply')}
            session._store_request_result(request.request_uuid, result)
            count = len(events)
            session._store_request_result(request.request_uuid, result)
            self.assertEqual(len(events), count)
            self.assertFalse(self._events(events, 'loop_end'))
            self.assertEqual(session.loop_state, 'waiting_model')
            outcome = session._continue(request.request_uuid, session.request_result)
            self.assertEqual(outcome['response']['responseState'], 'idle')
            count = len(events)
            session._continue(request.request_uuid, session.request_result)
            session._store_request_result(request.request_uuid, result)
            self.assertEqual(len(events), count)
        received = self._events(events, 'iteration', phase='result_received')
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]['iteration_id'], prepared['iteration_id'])
        self.assertEqual(received[0]['raw_response']['result']['content'][0]['content']['data'], 'Visible callback reply')
        self.assertIsNone(received[0]['provider'])
        self.assertIsNone(received[0]['duration_ms'])
        self.assertEqual(self._events(events, 'loop_end')[0]['termination_reason'], 'success')
        self.assertIn('Visible callback reply', session.channel_id.message_ids[0].body)

    def test_combined_tool_final_preserves_completion_and_output(self):
        tool = self._create_callback_tool('ai_debug_combined_final',
            "ai['result'] = 'Tool result'\nai['final_message'] = [{'type': 'text', 'text': 'Tool final'}]")
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Finish in the tool')
            outcome = self._consume(session, self._tool_result(tool, 'final'))
        self.assertFalse(outcome['prepared_requests'])
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

    def test_typed_client_responses_preserve_empty_error_and_falsy_results(self):
        tool = self._create_callback_tool('ai_debug_client_response',
            "ai['result'] = {'client_tool': {'name': 'debug_fixture', 'params': {}}}")
        for kind, value in [('client_result', 0), ('client_result', False), ('client_result', ''), ('client_error', '')]:
            with self.subTest(kind=kind, value=value):
                self.session.state = {'available_tools': tool.ids}
                events = []
                with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
                    session, request = self._prepare('Client response')
                    self._consume(session, self._tool_result(tool, 'client'))
                    self.assertEqual(session.loop_state, 'waiting_client_result')
                    with patch.object(type(tool), '_ai_tool_run', side_effect=AssertionError('Client tool rerun')):
                        session._resume_pending_interaction(session.resume_token, {'kind': kind, 'value': value})
                    self.assertEqual(session.loop_state, 'waiting_model')
                    completed = self._events(events, 'tool_call_completed')
                    self.assertEqual(len(completed), 1)
                    self.assertEqual(completed[0]['success'], kind == 'client_result')
                    self.assertEqual(completed[0]['iteration_id'], request.request_uuid)
                    self._consume(session, assistant_text('Finished'))

    def test_new_exchange_correlation_failure_does_not_reuse_previous_uuid(self):
        session, request = self._prepare('First exchange')
        self._consume(session, assistant_text('First answer'))
        current = session.with_context(current_view_info={'marker': 'new-exchange-view'})
        with patch.object(DebugAiSession, '_ai_debug_prepare_request_context', side_effect=RuntimeError('correlation unavailable')):
            current._prepare_agent_request([{'type': 'text', 'text': 'Second exchange'}])
        self.assertNotEqual(current.request_uuid, request.request_uuid)
        self.assertNotIn('ai_debug_exchange_uuid', current.request_context)
        self.assertNotIn('_ai_debug_parent_link', current.request_context)
        self.assertEqual(current.request_context['current_view_info'], {'marker': 'new-exchange-view'})

    def test_ordinary_tool_round_keeps_exchange_and_request_identity(self):
        tool = self._create_callback_tool('ai_debug_round_tool', "ai['result'] = 'executed once'")
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Run a tool')
            outcome = self._consume(session, self._tool_result(tool, 'call-1'))
            self.assertEqual(outcome['prepared_requests'], [{'session_id': session.id, 'request_uuid': session.request_uuid}])
            self.assertNotEqual(session.request_uuid, request.request_uuid)
            count = len(events)
            self._consume(session, self._tool_result(tool, 'call-1'), request.request_uuid)
            self.assertEqual(len(events), count)
            self._consume(session, assistant_text('Done'))
        self.assertEqual(len(self._events(events, 'new_trace')), 1)
        self.assertEqual([p['round_no'] for p in self._events(events, 'iteration', phase='prepared')], [1, 2])
        started = self._events(events, 'tool_call_started')
        completed = self._events(events, 'tool_call_completed')
        self.assertEqual(len(started), 1)
        self.assertEqual(len(completed), 1)
        self.assertEqual(started[0]['tool_call_id'], completed[0]['tool_call_id'])
        self.assertEqual(completed[0]['iteration_id'], request.request_uuid)
        self.assertEqual(len(self._events(events, 'loop_end')), 1)

    def test_atomic_result_and_tool_facts_roll_back_with_reduction(self):
        tool = self._create_callback_tool('ai_debug_rollback_tool', "ai['result'] = 'rolled back'")
        self.session.state = {'available_tools': tool.ids}
        session, request = self._prepare()
        bus = self.env['bus.bus'].sudo()
        domain = [('message', 'ilike', request.context_snapshot['ai_debug_exchange_uuid'])]
        before = bus.search(domain).ids
        with self.assertRaises(RuntimeError), self.env.cr.savepoint(), patch.object(
            EnterpriseAiSession, '_prepare_agent_request', side_effect=RuntimeError('continuation failure'),
        ):
            self._consume(session, self._tool_result(tool, 'rollback-call'))
        self.assertFalse(session.request_result)
        self.assertEqual(bus.search(domain).ids, before)
        self._consume(session, self._tool_result(tool, 'rollback-call'))
        events = [json.loads(row.message) for row in bus.search(domain)]
        self.assertEqual(sum(event['type'] == 'iteration' and event['payload'].get('phase') == 'result_received'
                             for event in events), 1)
        self.assertEqual(sum(event['type'] == 'tool_call_completed' for event in events), 1)

    def test_debugger_flush_failure_preserves_pending_business_result(self):
        session, request = self._prepare()
        def fail_after_flush(debug_session, *_args, **_kwargs):
            debug_session.flush_recordset(['request_result'])
            raise RuntimeError('observer failed after flushing pending result')
        with patch.object(DebugAiSession, '_ai_debug_trace_request_result', new=fail_after_flush):
            self._consume(session, assistant_text('Durable despite observer failure'))
        session.flush_recordset()
        self.env.cr.execute('SELECT request_result FROM ai_session WHERE id = %s', [session.id])
        result = self.env.cr.fetchone()[0]
        self.assertEqual(result, {'kind': 'success', 'message': assistant_text('Durable despite observer failure')})

    def test_business_flush_conflict_escapes_debugger_guard(self):
        observer = MagicMock()
        conflict = ConcurrencyError('Retry pending business work')
        with self.assertRaises(ConcurrencyError) as raised:
            with patch.object(type(self.env.cr), 'flush', side_effect=conflict):
                self.session._ai_debug_try(observer)
        self.assertIs(raised.exception, conflict)
        observer.assert_not_called()

    def _delegate(self, root, worker, call_ids):
        return self._consume(root, {'role': 'assistant', 'content': [
            {'type': 'tool_call', 'name': 'start_session', 'call_id': call_id,
             'args': {'agent_id': worker.id, 'message': 'Answer briefly'}} for call_id in call_ids
        ]})

    def test_parallel_children_apply_once_and_reused_child_has_new_exchange(self):
        worker = self.env['ai.agent'].create({'name': 'Trace Worker', 'system_prompt': 'Answer briefly.'})
        self.agent.allowed_agent_ids = worker
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            root, first = self._prepare('Delegate twice')
            outcome = self._delegate(root, worker, ['one', 'two'])
            children = self.env['ai.session'].browse([p['session_id'] for p in outcome['prepared_requests']])
            self.assertEqual(len(children), 2)
            self.assertNotIn('child_result', outcome, 'Waiting exchanges have no terminal result')
            for child in children[::-1]:
                child_outcome = self._consume(child, assistant_text('Worker answer'))
                child_result = child_outcome['child_result']
                terminal = self._events(events, 'loop_end', trace_id=child.request_context['ai_debug_exchange_uuid'])
                self.assertEqual(len(terminal), 1)
                self.assertEqual(terminal[0]['exchange_result'], child_result)
                self.assertEqual(child_result['status'], 'completed')
                self.assertIn('Worker answer', child_result['message'])
                self.assertEqual(root.loop_state, 'waiting_child')
                root._merge_child_result(child, child_result)
                count = len(events)
                root._merge_child_result(child, child_result)
                self.assertEqual(len(events), count)
            self.assertEqual(root.loop_state, 'waiting_model')
            old_child_trace = self._events(events, 'new_trace', session_id=children[0].id)[0]
            self._consume(root, {'role': 'assistant', 'content': [
                {'type': 'tool_call', 'name': 'continue_session', 'call_id': 'one',
                 'args': {'session_id': children[0].id, 'message': 'Answer again'}}
            ]})
            traces = self._events(events, 'new_trace', session_id=children[0].id)
            self.assertEqual(len(traces), 2)
            self.assertNotEqual(traces[-1]['trace_id'], old_child_trace['trace_id'])
            self.assertNotEqual(traces[-1]['parent_tool_call_id'], old_child_trace['parent_tool_call_id'])
        child_traces = [p for p in self._events(events, 'new_trace') if p.get('parent_trace_id')]
        for trace in child_traces:
            self.assertEqual(trace['parent_trace_id'], first.context_snapshot['ai_debug_exchange_uuid'])
            self.assertTrue(trace['parent_request_uuid'])
        self.assertEqual(len(self._events(events, 'tool_call_started')), 3)
        self.assertEqual(len(self._events(events, 'tool_call_completed')), 2)
        self.assertEqual(len(self._events(events, 'request_state', phase='child_applied')), 2)

    def _helper_tool(self, kind):
        return self._create_callback_tool('ai_debug_' + kind, "ai['result'] = " + repr({
            'completion_request': {'continuation_type': kind, 'payload': {
                'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': 'Fixture'}]}],
                'instructions': 'Fixture', 'tools': [],
            }},
        }))

    def test_web_helper_continuation_applies_sources_and_parent_trace(self):
        tool = self._helper_tool('web_search')
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            parent, request = self._prepare('Search')
            outcome = self._consume(parent, self._tool_result(tool, 'search'))
            child = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            source = {'abc123': {'url': 'https://www.odoo.com', 'source_name': 'Odoo'}}
            message = {'role': 'assistant', 'content': [{'type': 'text', 'text': 'Found', 'sources': source}]}
            self._consume(child, message)
            self.assertEqual(parent.state['web_sources'], source)
            applied = self._events(events, 'request_state', phase='child_applied')
            self.assertEqual(len(applied), 1)
            self.assertEqual(applied[0]['trace_id'], request.context_snapshot['ai_debug_exchange_uuid'])
            count = len(events)
            self._consume(child, message)
            self.assertEqual(len(events), count)
        trace = self._events(events, 'new_trace', session_id=child.id)[0]
        self.assertEqual(trace['trace_label'], 'Web Search')
        self.assertEqual(trace['parent_trace_id'], request.context_snapshot['ai_debug_exchange_uuid'])
        self.assertEqual(trace['parent_session_id'], parent.id)
        self.assertEqual(trace['parent_tool_call_id'], parent._ai_debug_callback_tool_call_id(request.request_uuid, 'search'))
        completed = self._events(events, 'tool_call_completed')
        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0]['trace_id'], trace['parent_trace_id'])
        self.assertEqual(completed[0]['tool_call_id'], trace['parent_tool_call_id'])
        raw = self._events(events, 'iteration', iteration_id=child.request_uuid, phase='result_received')[0]
        self.assertEqual(raw['raw_response']['result']['content'][0]['sources'], source)

    def test_image_helper_application_rolls_back_attachments_and_trace_together(self):
        from odoo.addons.base.tests.files import PNG_B64
        tool = self.env.ref('ai.ir_actions_server_ai_generate_image')
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            parent, request = self._prepare('Generate an image')
            outcome = self._consume(parent, self._tool_result(tool, 'image', {
                'prompt': 'A green mug', 'images_paths': [], 'image_title': 'debug-image-fixture',
                'feedback': 'Here is the image', 'aspect_ratio': '1:1',
            }))
            child = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            message = {'role': 'assistant', 'content': [
                {'type': 'inline_data', 'data': PNG_B64, 'mimetype': 'image/png'}
            ]}
            domain = [('name', '=', 'AI Generated debug-image-fixture')]
            self.assertFalse(self.env['ir.attachment'].search(domain))
            with self.assertRaises(RuntimeError), self.env.cr.savepoint():
                self._consume(child, message)
                self.assertEqual(len(self.env['ir.attachment'].search(domain)), 1)
                raise RuntimeError('rollback parent effects')
            self.assertFalse(self.env['ir.attachment'].search(domain))
            # Captured Python callbacks are not transactional; inspect durable Bus in the
            # separate rollback tests. Here reset the capture before the accepted retry.
            events.clear()
            self._consume(child, message)
            self.assertEqual(len(self.env['ir.attachment'].search(domain)), 1)
            count = len(events)
            self._consume(child, message)
            self.assertEqual(len(events), count)
            self.assertEqual(len(self._events(events, 'request_state', phase='child_applied')), 1)
            parent_end = self._events(events, 'loop_end', trace_id=request.context_snapshot['ai_debug_exchange_uuid'])
            self.assertEqual(len(parent_end), 1)
            self.assertTrue(parent_end[0]['final_output'])
            helper_end = self._events(events, 'loop_end', trace_id=child.request_context['ai_debug_exchange_uuid'])
            self.assertEqual(len(helper_end), 1)
            self.assertFalse(helper_end[0]['final_output'])

    def test_consecutive_helpers_keep_parent_identity_and_completed_prefix(self):
        tool = self._helper_tool('web_search')
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            parent, request = self._prepare('Search twice')
            message = {'role': 'assistant', 'content': [
                self._tool_result(tool, call_id)['content'][0] for call_id in ('first', 'second')
            ]}
            outcome = self._consume(parent, message)
            first = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            outcome = self._consume(first, assistant_text('First result'))
            second = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            self.assertNotEqual(first, second)
            self.assertEqual(parent.loop_state, 'waiting_child')
            self.assertFalse(self._events(events, 'loop_end', trace_id=request.context_snapshot['ai_debug_exchange_uuid']))
            self.assertEqual(len(self._events(events, 'tool_call_completed')), 1)
            self._consume(second, assistant_text('Second result'))
            self.assertEqual(parent.loop_state, 'waiting_model')
            count = len(events)
            self._consume(first, assistant_text('First result'))
            self._consume(second, assistant_text('Second result'))
            self.assertEqual(len(events), count)
        traces = [self._events(events, 'new_trace', session_id=child.id)[0] for child in (first, second)]
        for trace, call_id in zip(traces, ('first', 'second')):
            self.assertEqual(trace['parent_trace_id'], request.context_snapshot['ai_debug_exchange_uuid'])
            self.assertEqual(trace['parent_request_uuid'], request.request_uuid)
            self.assertEqual(trace['parent_tool_call_id'], parent._ai_debug_callback_tool_call_id(request.request_uuid, call_id))
        completed = self._events(events, 'tool_call_completed')
        self.assertEqual([item['call_id'] for item in completed], ['first', 'second'])
        self.assertEqual({item['trace_id'] for item in completed}, {request.context_snapshot['ai_debug_exchange_uuid']})
        self.assertEqual(len(self._events(events, 'request_state', phase='child_applied')), 2)

    def test_stale_submission_does_not_emit_acknowledgement(self):
        session, first = self._prepare()
        self._consume(session, assistant_text('First answer'))
        session._prepare_agent_request([{'type': 'text', 'text': 'Next exchange'}])
        events = []
        with (
            patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)),
            patch('odoo.addons.ai.models.ai_session.call_odoo_ai_transport', return_value=None) as transport,
        ):
            self.assertIsNone(session._submit_prepared_request(first.request_uuid))
            transport.assert_not_called()
            self.assertFalse(events)
            session._submit_prepared_request(session.request_uuid)
            submitted = self._events(events, 'request_state', phase='submitted')
            self.assertEqual(len(submitted), 1)
            self.assertEqual(submitted[0]['request_uuid'], session.request_uuid)
            count = len(events)
            self.assertIsNone(session._submit_prepared_request(session.request_uuid))
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(len(events), count)

    def test_typed_question_resume_and_supersession(self):
        tool = self._create_callback_tool('ai_debug_question', "ai['user_input_request'] = {'type': 'question', 'body': 'Choose', 'choices': [{'label': 'A', 'value': 'a'}], 'multi_select': False, 'allow_free_text': False}")
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, first = self._prepare()
            self._consume(session, self._tool_result(tool, 'question'))
            self.assertEqual(session.loop_state, 'waiting_answer')
            session._resume_pending_interaction(session.resume_token, {'kind': 'question', 'value': ['a']})
            self.assertEqual(session.loop_state, 'waiting_model')
            self._consume(session, self._tool_result(tool, 'question-again'))
            session._prepare_agent_request([{'type': 'text', 'text': 'New request'}])
            self.assertNotEqual(session.request_context['ai_debug_exchange_uuid'], first.context_snapshot['ai_debug_exchange_uuid'])
        self.assertEqual(len(self._events(events, 'loop_end')), 1)
        self.assertEqual(self._events(events, 'loop_end')[0]['termination_reason'], 'superseded')
        self.assertIn('USER ANSWER: a', str(self._events(events, 'tool_call_completed')))

    def test_decline_and_helper_failure_are_not_success(self):
        events = []
        tool = self._helper_tool('web_search')
        self.session.state = {'available_tools': tool.ids}
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            parent, request = self._prepare()
            outcome = self._consume(parent, self._tool_result(tool, 'failure'))
            child = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            child._store_request_result(child.request_uuid, {'kind': 'failure', 'code': 'request_failed'})
            child._continue(child.request_uuid, child.request_result)
        terminals = self._events(events, 'loop_end', trace_id=request.context_snapshot['ai_debug_exchange_uuid'])
        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0]['termination_reason'], 'failed')
        self.assertEqual([item['termination_reason'] for item in self._events(events, 'loop_end')], ['failed', 'failed'])

    def test_skip_and_decline_close_root_trace(self):
        for interaction, response in (
            ('question', {'kind': 'skip'}),
            ('confirmation', {'kind': 'confirmation', 'value': UserInputResponse.DECLINE}),
        ):
            with self.subTest(interaction=interaction):
                tool = self._create_callback_tool('ai_debug_' + interaction, "ai['user_input_request'] = " + repr({
                    'type': interaction, 'body': 'Choose',
                    'choices': [{'label': 'Decline', 'value': 'decline'}],
                    'multi_select': False, 'allow_free_text': False,
                }))
                self.session.state = {'available_tools': tool.ids}
                events = []
                with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
                    session, request = self._prepare()
                    self._consume(session, self._tool_result(tool, interaction))
                    session._resume_pending_interaction(session.resume_token, response)
                self.assertEqual(session.loop_state, 'ready')
                self.assertEqual(self._events(events, 'loop_end')[0]['termination_reason'], 'declined')

    def test_transition_setup_failure_preserves_business_reply(self):
        session, request = self._prepare()
        with patch.object(DebugAiSession, '_ai_debug_transition_snapshot', side_effect=RuntimeError('observer setup')):
            outcome = self._consume(session, assistant_text('Still answered'))
        self.assertEqual(outcome['response']['responseState'], 'idle')
        self.assertIn('Still answered', session.channel_id.message_ids[0].body)

    def test_missing_optional_exchange_key_does_not_close_active_trace(self):
        worker = self.env['ai.agent'].create({'name': 'Fallback worker', 'system_prompt': 'Answer.'})
        self.agent.allowed_agent_ids = worker
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            with patch.object(DebugAiSession, '_ai_debug_prepare_request_context', side_effect=RuntimeError('optional key')):
                root, request = self._prepare()
            self._delegate(root, worker, ['child'])
        self.assertEqual(root.loop_state, 'waiting_child')
        self.assertFalse(self._events(events, 'loop_end'))

    def test_merged_tool_parts_exclude_pdf_and_keep_attachment_reference(self):
        session, request = self._prepare()
        context = session._ai_debug_callback_context(session._ai_debug_request_snapshot())
        session._ai_debug_buffer_callback_tool_completed(context, {'call_id': 'file', 'name': 'start_session'}, result=[
            {'type': 'inline_data', 'mimetype': 'application/pdf', 'data': 'private-pdf-bytes'},
            {'type': 'inline_data', 'mimetype': 'image/png', 'data': 'image-bytes',
             'metadata': {'attachment_id': 42, 'image_path': '/web/image/42', 'secret': 'excluded'}},
        ], success=False)
        self.assertNotIn('private-pdf-bytes', str(context['events']))
        result = context['events'][-1][1]['result']
        self.assertNotIn('private-pdf-bytes', str(result))
        self.assertTrue(result[0]['content']['_binary_excluded'])
        self.assertEqual(result[1]['metadata'], {'attachment_id': 42, 'image_path': '/web/image/42'})

    def test_debugger_failure_does_not_change_request_or_reply(self):
        session, request = self._prepare('Failure isolation')
        def fail_with_database_error(debug_session, *_args, **_kwargs):
            debug_session.env.cr.execute('SELECT 1 / 0')
        with patch.object(DebugAiSession, '_ai_debug_trace_request_result', new=fail_with_database_error):
            outcome = self._consume(session, assistant_text('Still visible'))
        self.assertEqual(outcome['response']['responseState'], 'idle')
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
        self.assertEqual(_session.loop_state, 'waiting_model')
        self.assertEqual(_session.request_phase, 'prepared')
        self.assertTrue(request.request_uuid)

    def test_unchanged_event_context_reuses_context_message_with_debug_metadata(self):
        tool = self._create_callback_tool('ai_debug_unchanged_context', "ai['result'] = 'Done'")
        self.session.state = {'available_tools': tool.ids}
        session, request = self._prepare('Keep current context')
        current = session.with_context(**session.request_context)
        # Private metadata in the event may belong to a returning child.
        current = current.with_context(ai_debug_exchange_uuid='another-session',
                                       _ai_debug_parent_link={'parent_trace_id': 'another-session'})
        self.assertEqual(current._get_request_context_snapshot(), session.request_context)
        with patch.object(EnterpriseAiSession, '_get_context_input', side_effect=AssertionError('Unchanged context rebuilt')):
            self._consume(current, self._tool_result(tool, 'unchanged'))
        self.assertEqual(current.request_context['ai_debug_exchange_uuid'], request.context_snapshot['ai_debug_exchange_uuid'])

    def test_continuation_uses_event_context_and_retains_exchange_identity(self):
        tool = self._create_callback_tool('ai_debug_event_context', "ai['result'] = 'Done'")
        self.session.state = {'available_tools': tool.ids}
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            session, request = self._prepare('Run with current context', current_view_info={'marker': 'old-view'})
            current = session.with_context(current_view_info={'marker': 'event-view'}, private_event_value='not durable')
            snapshot = current._ai_debug_prepare_request_context(None, continuation=True)
            self.assertEqual(snapshot['current_view_info'], {'marker': 'event-view'})
            self.assertNotIn('private_event_value', snapshot)
            self._consume(current, self._tool_result(tool, 'context'))
            self.assertEqual(current.request_context['current_view_info'], {'marker': 'event-view'})
            self.assertNotIn('private_event_value', current.request_context)
            self.assertEqual(current.request_context['ai_debug_exchange_uuid'], request.context_snapshot['ai_debug_exchange_uuid'])
            self.assertIn('event-view', str(current.request_payload['messages']))
            self.assertNotIn('old-view', str(current.request_payload['messages']))
        self.assertEqual(len(self._events(events, 'new_trace')), 1)
        self.assertEqual([item['round_no'] for item in self._events(events, 'iteration', phase='prepared')], [1, 2])

    def test_delegated_helper_uses_event_context_without_changing_parent_links(self):
        worker = self.env['ai.agent'].create({'name': 'Context Worker', 'system_prompt': 'Answer.'})
        self.agent.allowed_agent_ids = worker
        tool = self._helper_tool('web_search')
        events = []
        with patch.object(DebugAiSession, '_ai_debug_bus_send', self._capture(events)):
            root, request = self._prepare('Delegate a search', current_view_info={'marker': 'root-old'})
            outcome = self._delegate(root.with_context(current_view_info={'marker': 'start-event'}), worker, ['worker'])
            child = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            self.assertEqual(child.request_context['current_view_info'], {'marker': 'start-event'})
            child_trace = child.request_context['ai_debug_exchange_uuid']
            child_link = child.request_context['_ai_debug_parent_link']
            child.state = {'available_tools': tool.ids}
            child_request_uuid = child.request_uuid
            outcome = self._consume(child.with_context(current_view_info={'marker': 'search-event'}), self._tool_result(tool, 'search'))
            helper = self.env['ai.session'].browse(outcome['prepared_requests'][0]['session_id'])
            self.assertEqual(helper.request_context['current_view_info'], {'marker': 'search-event'})
            self._consume(helper.with_context(current_view_info={'marker': 'result-event'}), assistant_text('Found'))
            self.assertEqual(child.request_context['current_view_info'], {'marker': 'result-event'})
            self.assertEqual(child.request_context['ai_debug_exchange_uuid'], child_trace)
            self.assertEqual(child.request_context['_ai_debug_parent_link'], child_link)
            self.assertIn('result-event', str(child.request_payload['messages']))
            self.assertEqual(root.request_context['current_view_info'], {'marker': 'root-old'})
        helper_trace = self._events(events, 'new_trace', session_id=helper.id)[0]
        self.assertEqual(helper_trace['parent_trace_id'], child_trace)
        self.assertEqual(helper_trace['parent_request_uuid'], child_request_uuid)
        self.assertEqual(child_link['parent_trace_id'], request.context_snapshot['ai_debug_exchange_uuid'])
        self.assertEqual(len(self._events(events, 'new_trace')), 3)

    def test_continuation_preserves_server_exchange_uuid(self):
        session, request = self._prepare('Correlate a continuation')
        browser_snapshot = {
            'active_company_ids': self.env.companies.ids,
            'ai_debug_exchange_uuid': 'untrusted-browser-value',
        }

        prepared_snapshot = session._ai_debug_prepare_request_context(
            browser_snapshot,
            continuation=True,
        )

        self.assertEqual(
            prepared_snapshot['ai_debug_exchange_uuid'],
            request.context_snapshot['ai_debug_exchange_uuid'],
        )
        self.assertEqual(
            browser_snapshot['ai_debug_exchange_uuid'],
            'untrusted-browser-value',
        )
        self.assertIsNot(prepared_snapshot, browser_snapshot)

    def test_non_dict_and_omitted_snapshots_have_safe_correlation(self):
        non_dict_snapshot = [{'marker': 'preserved'}]
        self.assertIs(
            self.session._ai_debug_prepare_request_context(
                non_dict_snapshot,
                continuation=False,
            ),
            non_dict_snapshot,
        )
        prepared_snapshot = self.session._ai_debug_prepare_request_context(
            None,
            continuation=False,
        )
        self.assertIsInstance(prepared_snapshot['ai_debug_exchange_uuid'], str)
        self.assertTrue(prepared_snapshot['ai_debug_exchange_uuid'])
        self.assertEqual(
            self.session._ai_debug_exchange_uuid({
                'request_uuid': 'non-dict-snapshot-request-fixture',
                'context_snapshot': non_dict_snapshot,
            }),
            'non-dict-snapshot-request-fixture',
        )
        self.assertEqual(
            self.session._ai_debug_exchange_uuid({
                'request_uuid': 'omitted-snapshot-request-fixture',
                'context_snapshot': None,
            }),
            'omitted-snapshot-request-fixture',
        )

    def test_exchange_uuid_injection_failure_does_not_block_request_prepare(self):
        with patch.object(
            DebugAiSession,
            '_ai_debug_prepare_request_context',
            side_effect=RuntimeError('uuid fixture failure'),
        ):
            session, request = self._prepare('Prepare without debugger correlation')

        self.assertEqual(session.loop_state, 'waiting_model')
        self.assertEqual(session.request_phase, 'prepared')
        self.assertTrue(request.request_uuid)
        self.assertNotIn('ai_debug_exchange_uuid', request.context_snapshot)

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
            'message_body_suffix': False,
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
