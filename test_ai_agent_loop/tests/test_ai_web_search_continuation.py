# Part of Odoo. See LICENSE file for full copyright and licensing details.

import copy
from unittest.mock import patch

import requests

from odoo import api, Command
from odoo.exceptions import UserError
from odoo.tests import HttpCase, tagged, TransactionCase
from odoo.tools import mute_logger

from odoo.addons.ai.models.ai_session import AiSession
from odoo.addons.ai.utils.ai_utils import UserInputResponse
from odoo.addons.iap import InsufficientCreditError

from .common import apply_iap_result


TRANSPORT = 'odoo.addons.ai.utils.session_env.call_odoo_ai_transport'
SEARCH_SOURCE = {'url': 'https://example.com/search', 'source_name': 'example.com'}


def assistant_text(text, sources=None):
    part = {'type': 'text', 'text': text}
    if sources is not None:
        part['sources'] = sources
    return {'role': 'assistant', 'content': [part]}


class WebSearchFixture:
    """Shared fixtures, without inheriting or duplicating another test suite."""

    fixture_name = 'Web search'
    fixture_key = 'web_search'
    fixture_skill = 'ai.ai_skill_web_search'
    fixture_tool = 'ai.ir_actions_server_ai_web_search'
    fixture_tool_key = 'search'
    fixture_prompt = 'Research durable callbacks.'
    fixture_instructions = 'Research the requested topic and cite the sources.'

    def _create_fixture(self, env):
        self.actor_id = env.uid
        self.context_snapshot = {
            'allowed_company_ids': env.companies.ids,
            'active_company_ids': env.companies.ids,
            'lang': 'en_US',
            'tz': 'UTC',
            'current_view_info': {'res_model': 'res.partner', 'view_type': 'list'},
        }
        agent = env['ai.agent'].create({
            'name': f'{self.fixture_name} Continuation Agent',
            'system_prompt': self.fixture_instructions,
            'skill_ids': [Command.link(env.ref(self.fixture_skill).id)],
        })
        channel = agent._create_ai_chat_channel(f'{self.fixture_name} Continuation')
        session = env['ai.session'].sudo().create({
            'agent_id': agent.id,
            'channel_id': channel.id,
        }).with_context(self.context_snapshot)
        self.session_id = session.id
        self.channel_id = channel.id
        self.prefix_name = f'{self.fixture_name} prefix {session.id}'
        tools = {
            self.fixture_tool_key: env.ref(self.fixture_tool),
            'question': env.ref('ai.ir_actions_server_ask_user_question'),
        }
        codes = {
            'prefix': f"""
partner = env['res.partner'].create({{'name': {self.prefix_name!r}}})
ai['state']['prefix_partner_ids'] = ai['state'].get('prefix_partner_ids', []) + partner.ids
ai['result'] = 'prefix'
""",
            'suffix': """
env['res.partner'].browse(ai['state'].get('prefix_partner_ids', [])).write({'comment': 'Suffix executed'})
ai['state']['suffix_runs'] = ai['state'].get('suffix_runs', 0) + 1
ai['result'] = 'suffix'
""",
            'confirmation': """
if not ai['tool_request_confirmed']:
    ai['user_input_request'] = {
        'type': 'confirmation',
        'body': 'Run the confirmed step?',
        'choices': [{'label': 'Yes', 'value': 'confirm_once'}],
    }
else:
    ai['state']['confirmation_runs'] = ai['state'].get('confirmation_runs', 0) + 1
    ai['result'] = 'confirmed'
""",
            'client': """
ai['state']['client_runs'] = ai['state'].get('client_runs', 0) + 1
ai['result'] = {'client_tool': {'name': 'web_search_fixture_client', 'params': {}}}
""",
        }
        for name, code in codes.items():
            tools[name] = env['ir.actions.server'].create({
                'name': f'{self.fixture_name} {name}',
                'ai_tool_name': f'{self.fixture_key}_{name}_{session.id}',
                'ai_tool_thinking_text': f'Running {name}',
                'ai_tool_description': f'{self.fixture_name} continuation fixture.',
                'ai_tool_schema': '{"type": "object", "properties": {}, "required": []}',
                'model_id': env.ref('ai.model_ai_tool').id,
                'state': 'code',
                'use_in_ai': True,
                'code': code,
            })
        self.tool_ids = {name: tool.id for name, tool in tools.items()}
        self.tool_names = {name: tool.ai_tool_name for name, tool in tools.items()}
        session.state = {
            'available_tools': [tool.id for tool in tools.values()],
            'web_sources': {'f00d': {'url': 'https://example.org/old', 'source_name': 'Earlier source'}},
        }
        message = channel.message_post(body=self.fixture_prompt, message_type='comment')
        session._prepare_model_request(
            message._convert_to_parts(), context_snapshot=self.context_snapshot,
        )
        self.parent_request_uuid = session.request_uuid

    def _session(self, session_id=None, env=None):
        env = env or self.env
        return env['ai.session'].with_user(self.actor_id).sudo().with_context(
            self.context_snapshot,
        ).browse(session_id or self.session_id)

    def _call(self, name, call_id=None, args=None):
        if args is None:
            args = {
                'search': {
                    'query': 'Odoo durable callbacks',
                    'retrieval_mode': 'summary',
                    'context_hint': 'Regression lookup',
                },
                'question': {
                    'question': 'Continue?', 'choices': ['Continue', 'Stop'],
                    'multi_select': False, 'allow_free_text': False,
                },
            }.get(name, {})
        return {
            'type': 'tool_call', 'call_id': call_id or name,
            'name': self.tool_names[name], 'args': args,
        }

    def _apply(self, session, message):
        with patch.object(
            AiSession, '_get_completions',
            side_effect=AssertionError(f'Durable {self.fixture_name} must not complete synchronously'),
        ) as direct:
            outcome = apply_iap_result(session, session.request_uuid, {
                'kind': 'success', 'message': message,
            })
        direct.assert_not_called()
        return outcome

    def _apply_calls(self, calls):
        return self._apply(self._session(), {'role': 'assistant', 'content': calls})

    def _results(self, session):
        return session.event_ids.sorted('id')[-1].metadata['content']

    def _assert_prefix_once(self, session):
        partners = self.env['res.partner'].search([('name', '=', self.prefix_name)])
        self.assertEqual(len(partners), 1)
        self.assertEqual(session.state['prefix_partner_ids'], partners.ids)


@tagged('post_install', '-at_install')
class TestAIWebSearchContinuation(WebSearchFixture, TransactionCase):
    def setUp(self):
        super().setUp()
        self._create_fixture(self.env(user=self.env.ref('base.user_admin').id))

    def test_search_prepares_headless_child_and_retains_parent_intent(self):
        parent = self._session()
        parent_payload = copy.deepcopy(parent.request_payload)
        calls = [self._call('prefix'), self._call('search'), self._call('suffix')]
        outcome = self._apply_calls(calls)
        child = self._session(outcome['prepared']['session_id'])

        self.assertEqual(outcome['response'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'running',
        })
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertFalse(parent.request_phase)
        self.assertFalse(parent.resume_token)
        self.assertEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(parent.request_payload, parent_payload)
        self.assertEqual(parent.request_result, {
            'kind': 'success', 'message': {'role': 'assistant', 'content': calls},
        })
        self.assertEqual(parent.pending_tool_call['call_id'], 'search')
        self.assertEqual(
            [part['tool_call_id'] for part in parent.pending_tool_call['pending_results']], ['prefix'],
        )
        self._assert_prefix_once(parent)
        self.assertNotIn('suffix_runs', parent.state)
        self.assertEqual(child.parent_session_id, parent)
        self.assertFalse(child.agent_id)
        self.assertFalse(child.channel_id)
        self.assertFalse(child.res_model)
        self.assertFalse(child.res_id)
        self.assertFalse(child.event_ids)
        self.assertEqual(parent.channel_id.ai_session_ids, parent)
        self.assertEqual(child.request_user_id.id, self.actor_id)
        self.assertFalse(child.request_guest_id)
        self.assertEqual(child.request_context, self.context_snapshot)
        self.assertEqual(child.request_callback_url, parent.request_callback_url)
        self.assertEqual(child.request_round, 1)
        self.assertEqual(child.request_round_limit, 1)
        self.assertEqual(child.request_phase, 'prepared')
        self.assertEqual(child.previous_request_uuid, self.parent_request_uuid)
        self.assertEqual(child.continuation_data, {
            'continuation_type': 'web_search',
            'parent_request_uuid': self.parent_request_uuid, 'call_id': 'search',
        })
        payload = child.request_payload
        self.assertEqual(set(payload), {'messages', 'instructions', 'tools', 'usage', 'web_grounding'})
        self.assertEqual(payload['messages'], [{
            'role': 'user', 'content': [{
                'type': 'text', 'text': 'Odoo durable callbacks\n[Context: Regression lookup]',
            }],
        }])
        self.assertEqual(payload['tools'], [])
        self.assertEqual(payload['usage'], 'web_search')
        self.assertIs(payload['web_grounding'], True)
        self.assertIn('Return a structured summary', payload['instructions'])
        self.assertNotIn('odoo_current_context', str(payload))

    def test_child_success_merges_sources_then_resumes_once_with_citations(self):
        outcome = self._apply_calls([self._call('prefix'), self._call('search'), self._call('suffix')])
        child = self._session(outcome['prepared']['session_id'])
        search_message = assistant_text('Grounded finding.[WEB_SOURCE:abcd]', {'abcd': SEARCH_SOURCE})
        resumed = self._apply(child, search_message)
        parent = self._session()

        self.assertEqual(child.loop_state, 'ready')
        self.assertFalse(child.request_phase)
        self.assertEqual(child.request_result['message'], search_message)
        self.assertEqual(resumed['prepared']['session_id'], parent.id)
        self.assertNotEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(parent.previous_request_uuid, child.request_uuid)
        self.assertEqual(parent.request_round, 2)
        self.assertEqual(parent.request_phase, 'prepared')
        self.assertFalse(parent.pending_tool_call)
        self.assertEqual(parent.state['web_sources']['abcd'], SEARCH_SOURCE)
        self.assertIn('f00d', parent.state['web_sources'])
        results = self._results(parent)
        self.assertEqual([part['tool_call_id'] for part in results], ['prefix', 'search', 'suffix'])
        self.assertIn('Grounded finding', results[1]['result'][0]['text'])
        self.assertIn('[WEB_SOURCE:abcd]', results[1]['result'][0]['text'])
        self._assert_prefix_once(parent)
        self.assertEqual(parent.state['suffix_runs'], 1)
        event_count = len(parent.event_ids)
        self._apply(child, search_message)
        self.assertEqual(len(parent.event_ids), event_count)
        self.assertEqual(parent.state['suffix_runs'], 1)

        self._apply(parent, assistant_text('Final finding.[WEB_SOURCE:abcd]'))
        self.assertEqual(parent.loop_state, 'ready')
        body = parent.channel_id.message_ids[0].body
        self.assertIn(SEARCH_SOURCE['url'], body)
        self.assertNotIn('[WEB_SOURCE:', body)

    def test_sequential_searches_carry_the_completed_prefix_without_replay(self):
        outcome = self._apply_calls([
            self._call('prefix'), self._call('search', 'first-search'),
            self._call('search', 'second-search'), self._call('suffix'),
        ])
        first = self._session(outcome['prepared']['session_id'])
        next_search = self._apply(first, assistant_text('First finding', {'abcd': SEARCH_SOURCE}))
        second = self._session(next_search['prepared']['session_id'])
        parent = self._session()

        self.assertNotEqual(first, second)
        self.assertEqual(second.parent_session_id, parent)
        self.assertEqual(second.continuation_data['call_id'], 'second-search')
        self.assertEqual(parent.request_uuid, self.parent_request_uuid)
        self.assertEqual(parent.request_round, 1)
        self.assertEqual(len(parent.event_ids), 2)
        self.assertEqual(
            [part['tool_call_id'] for part in parent.pending_tool_call['pending_results']],
            ['prefix', 'first-search'],
        )
        self._assert_prefix_once(parent)
        self.assertNotIn('suffix_runs', parent.state)

        self._apply(second, assistant_text('Second finding', {'beef': SEARCH_SOURCE}))
        self.assertEqual([part['tool_call_id'] for part in self._results(parent)], [
            'prefix', 'first-search', 'second-search', 'suffix',
        ])
        self.assertEqual(set(parent.state['web_sources']), {'f00d', 'abcd', 'beef'})
        self._assert_prefix_once(parent)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self.assertEqual(self.env['ai.session'].search_count([('parent_session_id', '=', parent.id)]), 2)

    def test_search_preserves_confirmation_client_and_question_suffix(self):
        names = ['search', 'confirmation', 'client', 'question', 'suffix']
        outcome = self._apply_calls([self._call(name) for name in names])
        child = self._session(outcome['prepared']['session_id'])
        waiting = self._apply(child, assistant_text('Search complete'))
        parent = self._session()
        self.assertEqual(waiting['response']['responseState'], 'waiting_user')
        self.assertEqual(parent.loop_state, 'waiting_confirmation')
        first_token = parent.resume_token
        parent._resume_pending_interaction(
            self.parent_request_uuid, first_token,
            {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
        )
        self.assertEqual(parent.loop_state, 'waiting_client_result')
        self.assertNotEqual(parent.resume_token, first_token)
        client_token = parent.resume_token
        parent._resume_pending_interaction(
            self.parent_request_uuid, client_token, {'kind': 'client_result', 'value': False},
        )
        self.assertEqual(parent.loop_state, 'waiting_answer')
        self.assertNotEqual(parent.resume_token, client_token)
        parent._resume_pending_interaction(
            self.parent_request_uuid, parent.resume_token, {'kind': 'question', 'value': ['Continue']},
        )
        results = self._results(parent)
        self.assertEqual([part['tool_call_id'] for part in results], names)
        self.assertTrue(all(part['success'] for part in results))
        self.assertEqual(results[2]['result'][0]['text'], 'false')
        self.assertEqual(parent.state['confirmation_runs'], 1)
        self.assertEqual(parent.state['client_runs'], 1)
        self.assertEqual(parent.state['suffix_runs'], 1)
        self.assertEqual(parent.request_round, 2)

    def test_search_failure_balances_unexecuted_calls_and_finishes_both_sessions(self):
        outcome = self._apply_calls([self._call('prefix'), self._call('search'), self._call('suffix')])
        child = self._session(outcome['prepared']['session_id'])
        failure = {'kind': 'failure', 'code': 'request_failed'}
        finished = apply_iap_result(child, child.request_uuid, failure)
        parent = self._session()

        self.assertEqual(finished['response'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'idle',
        })
        self.assertEqual(parent.loop_state, 'ready')
        self.assertEqual(child.loop_state, 'ready')
        self.assertFalse(parent.pending_tool_call)
        self.assertFalse(parent.request_phase)
        self.assertEqual(child.request_result, failure)
        results = self._results(parent)
        self.assertEqual([part['tool_call_id'] for part in results], ['prefix', 'search', 'suffix'])
        self.assertEqual([part['success'] for part in results], [True, False, False])
        self._assert_prefix_once(parent)
        self.assertNotIn('suffix_runs', parent.state)
        counts = (len(parent.event_ids), len(parent.channel_id.message_ids))
        apply_iap_result(child, child.request_uuid, failure)
        self.assertEqual((len(parent.event_ids), len(parent.channel_id.message_ids)), counts)

    def test_search_continuation_matches_the_pending_parent_call(self):
        outcome = self._apply_calls([self._call('prefix'), self._call('search'), self._call('suffix')])
        parent = self._session()
        child = self._session(outcome['prepared']['session_id'])
        child._store_request_result(child.request_uuid, {
            'kind': 'success', 'message': assistant_text('Stored search result'),
        })
        pending = copy.deepcopy(parent.pending_tool_call)
        parent.pending_tool_call = {**pending, 'call_id': 'different-call'}
        with self.assertRaises(UserError), self.env.cr.savepoint():
            child._continue(child.request_uuid)
        self.assertEqual(child.loop_state, 'waiting_model')
        self.assertTrue(child.request_result)
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertNotIn('suffix_runs', parent.state)
        parent.pending_tool_call = pending
        child._continue(child.request_uuid)
        self._assert_prefix_once(parent)
        self.assertEqual(parent.state['suffix_runs'], 1)


@tagged('post_install', '-at_install')
class TestAIWebSearchContinuationHttp(WebSearchFixture, HttpCase):
    def setUp(self):
        super().setUp()
        with self.registry.cursor() as cr:
            self._create_fixture(api.Environment(cr, self.env.ref('base.user_admin').id, {}))

    def _fresh_session(self, session_id=None):
        self.env.invalidate_all()
        return self._session(session_id)

    def _child(self):
        self.env.invalidate_all()
        return self.env['ai.session'].sudo().search([('parent_session_id', '=', self.session_id)])

    def _post_callback(self, request_uuid, message):
        with (
            self.allow_requests(all_requests=True),
            patch.object(
                AiSession, '_get_completions',
                side_effect=AssertionError('Durable web search must not complete synchronously'),
            ) as direct,
        ):
            response = requests.post(
                f'{self.base_url()}/ai/completion_result_ready',
                json={
                    'request_uuid': request_uuid,
                    'llm_result': {'status': 'success', 'result': message},
                    'llm_error': False,
                },
                timeout=12,
            )
        direct.assert_not_called()
        self.assertNotIn('Cookie', response.request.headers)
        return response

    def _wait_for_confirmation(self):
        with patch(TRANSPORT) as submit:
            response = self._post_callback(self.parent_request_uuid, {
                'role': 'assistant',
                'content': [self._call('confirmation'), self._call('search'), self._call('suffix')],
            })
        self.assertEqual(response.status_code, 200)
        submit.assert_not_called()
        return self._fresh_session().resume_token

    def _resume_confirmation(self, token):
        self.authenticate('admin', 'admin')
        with patch.object(
            AiSession, '_get_completions',
            side_effect=AssertionError('Durable web search must not complete synchronously'),
        ) as direct:
            response = self.url_open('/ai/resume_pending_interaction', json=self.build_rpc_payload({
                'channel_id': self.channel_id,
                'request_uuid': self.parent_request_uuid,
                'resume_token': token,
                'response': {'kind': 'confirmation', 'value': UserInputResponse.CONFIRM_ONCE},
                'current_view_info': {'res_model': 'res.partner', 'view_type': 'form'},
            }))
        direct.assert_not_called()
        return response

    def test_callback_commits_parent_prefix_and_child_before_submission(self):
        observations = []
        calls = [self._call('prefix'), self._call('search'), self._call('suffix')]

        def observe_submission(_connection, route, payload, **_kwargs):
            with self.registry.cursor() as cr:
                env = api.Environment(cr, self.actor_id, self.context_snapshot)
                parent = self._session(env=env)
                child = env['ai.session'].sudo().search([('request_uuid', '=', payload['request_uuid'])])
                observations.append({
                    'route': route, 'payload': copy.deepcopy(payload),
                    'child_payload': child.request_payload, 'child_phase': child.request_phase,
                    'child_parent': child.parent_session_id.id, 'child_user': child.request_user_id.id,
                    'parent_state': parent.loop_state, 'parent_result': parent.request_result,
                    'prefix_count': env['res.partner'].search_count([('name', '=', self.prefix_name)]),
                })
            return None

        with patch(TRANSPORT, side_effect=observe_submission) as submit:
            response = self._post_callback(self.parent_request_uuid, {'role': 'assistant', 'content': calls})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())
        submit.assert_called_once()
        observed = observations[0]
        self.assertEqual(observed['route'], '1/get_completions')
        self.assertEqual(observed['parent_state'], 'waiting_child')
        self.assertEqual(observed['child_phase'], 'prepared')
        self.assertEqual(observed['child_parent'], self.session_id)
        self.assertEqual(observed['child_user'], self.actor_id)
        self.assertEqual(observed['prefix_count'], 1)
        self.assertEqual(observed['parent_result'], {
            'kind': 'success', 'message': {'role': 'assistant', 'content': calls},
        })
        child = self._child()
        self.assertEqual(observed['payload'], {
            **observed['child_payload'], 'request_uuid': child.request_uuid,
            'webhook_url': child.request_callback_url,
            'webhook_token': child.request_webhook_token,
            'llm_retry': False,
        })
        self.assertEqual(child.request_phase, 'submitted')
        self.assertNotIn('suffix_runs', self._fresh_session().state)

    def test_search_callback_submits_image_successor_and_preserves_parent_batch(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.actor_id, self.context_snapshot)
            parent = self._session(env=env)
            image_tool = env.ref('ai.ir_actions_server_ai_generate_image')
            parent.state = {
                **parent.state, 'available_tools': parent.state['available_tools'] + image_tool.ids,
            }
            image_call = {
                'type': 'tool_call', 'call_id': 'image', 'name': image_tool.ai_tool_name,
                'args': {
                    'prompt': 'Illustrate the search result.', 'images_paths': [],
                    'image_title': 'Search continuation', 'feedback': 'Here is the illustration.',
                    'aspect_ratio': '16:9',
                },
            }
        calls = [self._call('prefix'), self._call('search'), image_call, self._call('suffix')]
        search_message = assistant_text('Grounded search result', {'abcd': SEARCH_SOURCE})
        image_message = assistant_text('Please provide a reference image.')

        with patch(TRANSPORT, return_value=None) as submit:
            response = self._post_callback(self.parent_request_uuid, {'role': 'assistant', 'content': calls})
            self.assertEqual(response.status_code, 200)
            submit.assert_called_once()
            search = self._child()
            self.assertEqual(search.request_phase, 'submitted')
            self.assertEqual(search.previous_request_uuid, self.parent_request_uuid)
            submit.reset_mock()

            response = self._post_callback(search.request_uuid, search_message)
            self.assertEqual(response.status_code, 200)
            submit.assert_called_once()
            children = self._child()
            image = children - search
            self.assertEqual(len(image), 1)
            self.assertEqual(submit.call_args.args[2]['request_uuid'], image.request_uuid)
            self.assertEqual(image.request_phase, 'submitted')
            self.assertEqual(image.previous_request_uuid, search.request_uuid)
            self.assertEqual(image.continuation_data, {
                'continuation_type': 'image_generation',
                'parent_request_uuid': self.parent_request_uuid, 'call_id': 'image',
            })
            parent = self._fresh_session()
            self.assertEqual(parent.request_uuid, self.parent_request_uuid)
            self.assertEqual(parent.loop_state, 'waiting_child')
            self.assertEqual(parent.pending_tool_call['call_id'], 'image')
            self.assertEqual(
                [part['tool_call_id'] for part in parent.pending_tool_call['pending_results']],
                ['prefix', 'search'],
            )
            self.assertNotIn('suffix_runs', parent.state)
            self._assert_prefix_once(parent)
            pending = copy.deepcopy(parent.pending_tool_call)
            submit.reset_mock()

            replay = self._post_callback(search.request_uuid, search_message)
            self.assertEqual(replay.status_code, 200)
            submit.assert_not_called()
            self.assertEqual(self._child(), children)
            self.assertEqual(self._fresh_session().pending_tool_call, pending)

            response = self._post_callback(image.request_uuid, image_message)
            self.assertEqual(response.status_code, 200)
            submit.assert_called_once()
            parent = self._fresh_session()
            self.assertEqual(parent.loop_state, 'waiting_model')
            self.assertEqual(parent.request_phase, 'submitted')
            self.assertEqual(parent.previous_request_uuid, image.request_uuid)
            self.assertEqual(submit.call_args.args[2]['request_uuid'], parent.request_uuid)
            self.assertEqual(parent.state['suffix_runs'], 1)
            self._assert_prefix_once(parent)
            results = self._results(parent)
            self.assertEqual([part['tool_call_id'] for part in results], ['prefix', 'search', 'image', 'suffix'])
            self.assertTrue(all(part['success'] for part in results))
            counts = (len(parent.event_ids), len(parent.channel_id.message_ids))
            submit.reset_mock()

            for request_uuid, message in [(search.request_uuid, search_message), (image.request_uuid, image_message)]:
                self.assertEqual(self._post_callback(request_uuid, message).status_code, 200)
            submit.assert_not_called()
            self.assertEqual(self._child(), children)
            parent = self._fresh_session()
            self.assertEqual((len(parent.event_ids), len(parent.channel_id.message_ids)), counts)
            self.assertEqual(parent.state['suffix_runs'], 1)
            self._assert_prefix_once(parent)

    def test_search_callback_submits_new_and_continued_conversational_children(self):
        with self.registry.cursor() as cr:
            env = api.Environment(cr, self.actor_id, self.context_snapshot)
            agent = self._session(env=env).agent_id
            agent.allowed_agent_ids = agent
            agent_id = agent.id
        child_id = None
        previous_child_uuid = None

        for round_no, tool_name in enumerate(('start_session', 'continue_session'), start=1):
            with patch(TRANSPORT, return_value=None) as submit:
                parent_uuid = self._fresh_session().request_uuid
                delegate_call = {
                    'type': 'tool_call', 'call_id': tool_name, 'name': tool_name,
                    'args': {
                        'agent_id' if tool_name == 'start_session' else 'session_id': agent_id if child_id is None else child_id,
                        'message': f'Delegated search follow-up {round_no}',
                    },
                }
                calls = ([self._call('prefix')] if round_no == 1 else []) + [
                    self._call('search'), delegate_call, self._call('suffix'),
                ]
                response = self._post_callback(parent_uuid, {'role': 'assistant', 'content': calls})
                self.assertEqual(response.status_code, 200)
                submit.assert_called_once()
                search_uuid = submit.call_args.args[2]['request_uuid']
                search = self._child().filtered(lambda session: session.request_uuid == search_uuid)
                self.assertEqual(search.continuation_data['parent_request_uuid'], parent_uuid)
                submit.reset_mock()

                search_message = assistant_text(f'Search result {round_no}')
                response = self._post_callback(search_uuid, search_message)
                self.assertEqual(response.status_code, 200)
                submit.assert_called_once()
                children = self._child()
                child = children.filtered('agent_id')
                self.assertEqual(len(child), 1)
                if child_id is not None:
                    self.assertEqual(child.id, child_id)
                    self.assertIn('Delegated answer 1', str(child.request_payload['messages']))
                child_id = child.id
                child_uuid = child.request_uuid
                self.assertNotEqual(child_uuid, previous_child_uuid)
                self.assertEqual(submit.call_args.args[2]['request_uuid'], child_uuid)
                self.assertEqual(child.request_phase, 'submitted')
                self.assertEqual(child.previous_request_uuid, search_uuid)
                parent = self._fresh_session()
                self.assertEqual(parent.request_uuid, parent_uuid)
                self.assertEqual(parent.loop_state, 'waiting_child')
                self.assertEqual(child.parent_session_id, parent)
                self.assertEqual(
                    [part['tool_call_id'] for part in parent.pending_tool_call['pending_results']],
                    [call['call_id'] for call in calls],
                )
                self.assertEqual(parent.state['suffix_runs'], round_no)
                self._assert_prefix_once(parent)
                pending = copy.deepcopy(parent.pending_tool_call)
                submit.reset_mock()

                replay = self._post_callback(search_uuid, search_message)
                self.assertEqual(replay.status_code, 200)
                submit.assert_not_called()
                self.assertEqual(self._child(), children)
                self.assertEqual(self._fresh_session().pending_tool_call, pending)

                child_message = assistant_text(f'Delegated answer {round_no}')
                response = self._post_callback(child_uuid, child_message)
                self.assertEqual(response.status_code, 200)
                submit.assert_called_once()
                parent = self._fresh_session()
                self.assertEqual(submit.call_args.args[2]['request_uuid'], parent.request_uuid)
                self.assertEqual(parent.request_phase, 'submitted')
                self.assertEqual(parent.previous_request_uuid, child_uuid)
                self.assertEqual(
                    [part['tool_call_id'] for part in self._results(parent)],
                    [call['call_id'] for call in calls],
                )
                self.assertTrue(all(part['success'] for part in self._results(parent)))
                self.assertEqual(parent.state['suffix_runs'], round_no)
                submit.reset_mock()

                for request_uuid, message in [(search_uuid, search_message), (child_uuid, child_message)]:
                    self.assertEqual(self._post_callback(request_uuid, message).status_code, 200)
                submit.assert_not_called()
                self.assertEqual(self._child(), children)
                self.assertEqual(self._fresh_session().state['suffix_runs'], round_no)
                previous_child_uuid = child_uuid

    def test_child_result_survives_rollback_and_resumes_without_repeating_tools(self):
        with patch(TRANSPORT, return_value=None):
            response = self._post_callback(self.parent_request_uuid, {
                'role': 'assistant',
                'content': [self._call('prefix'), self._call('search'), self._call('suffix')],
            })
        self.assertEqual(response.status_code, 200)
        child = self._child()
        message = assistant_text('Retained search result', {'abcd': SEARCH_SOURCE})
        original_continue = AiSession._continue_web_search

        def fail_after_effect(session):
            original_continue(session)
            raise RuntimeError('roll back the search continuation')

        with (
            mute_logger('odoo.http'),
            patch.object(AiSession, '_continue_web_search', autospec=True, side_effect=fail_after_effect),
            patch(TRANSPORT) as submit,
        ):
            failed = self._post_callback(child.request_uuid, message)
        self.assertEqual(failed.status_code, 500)
        submit.assert_not_called()
        child = self._fresh_session(child.id)
        self.assertEqual(child.request_result, {'kind': 'success', 'message': message})
        self.assertEqual(child.loop_state, 'waiting_model')
        parent = self._fresh_session()
        self.assertEqual(parent.loop_state, 'waiting_child')
        self.assertNotIn('suffix_runs', parent.state)
        self._assert_prefix_once(parent)

        with patch(TRANSPORT, return_value=None) as submit:
            redelivered = self._post_callback(child.request_uuid, message)
        self.assertEqual(redelivered.status_code, 200)
        submit.assert_called_once()
        parent = self._fresh_session()
        self.assertEqual(parent.request_round, 2)
        self.assertEqual(parent.request_phase, 'submitted')
        self.assertEqual(parent.state['suffix_runs'], 1)
        self._assert_prefix_once(parent)
        partner = self.env['res.partner'].browse(parent.state['prefix_partner_ids'])
        self.assertEqual(partner.write_uid.id, self.actor_id)
        self.assertEqual(self._fresh_session(child.id).loop_state, 'ready')

    def test_confirmation_to_search_keeps_parent_acknowledgement_and_fresh_context(self):
        token = self._wait_for_confirmation()
        with patch(TRANSPORT, return_value=None) as submit:
            response = self._resume_confirmation(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'running',
        })
        submit.assert_called_once()
        child = self._child()
        self.assertNotEqual(child.request_uuid, self.parent_request_uuid)
        self.assertEqual(child.request_context['current_view_info'], {
            'res_model': 'res.partner', 'view_type': 'form',
        })
        self.assertEqual(child.request_user_id.id, self.actor_id)
        self.assertEqual(self._fresh_session().loop_state, 'waiting_child')
        child_context = copy.deepcopy(child.request_context)
        with patch(TRANSPORT, return_value=None) as submit:
            completed = self._post_callback(child.request_uuid, assistant_text('Search complete'))
        self.assertEqual(completed.status_code, 200)
        submit.assert_called_once()
        parent = self._fresh_session()
        self.assertEqual(parent.loop_state, 'waiting_model')
        self.assertEqual(parent.request_phase, 'submitted')
        self.assertEqual(parent.previous_request_uuid, child.request_uuid)
        self.assertEqual(parent.request_context, child_context)
        self.assertEqual(parent.request_user_id.id, self.actor_id)

    def test_resume_replay_submits_the_existing_headless_child(self):
        token = self._wait_for_confirmation()
        sent_payloads = []

        def fail_first_send(_connection, _route, payload, **_kwargs):
            sent_payloads.append(copy.deepcopy(payload))
            if len(sent_payloads) == 1:
                raise requests.ConnectionError('fail after headless child commit')
            return None

        with (
            mute_logger('odoo.http'),
            patch(TRANSPORT, side_effect=fail_first_send) as transport,
        ):
            failed = self._resume_confirmation(token)
            self.assertIn('error', failed.json())

            parent = self._fresh_session()
            child = self._child()
            child_uuid = child.request_uuid
            child_token = child.request_webhook_token
            self.assertEqual(parent.loop_state, 'waiting_child')
            self.assertEqual(parent.state['confirmation_runs'], 1)
            self.assertEqual(child.parent_session_id, parent)
            self.assertEqual(child.previous_request_uuid, self.parent_request_uuid)
            self.assertEqual(child.request_phase, 'prepared')

            replay = self._resume_confirmation(token)

        self.assertNotIn('error', replay.json())
        self.assertEqual(replay.json()['result'], {
            'request_uuid': self.parent_request_uuid,
            'responseState': 'running',
        })
        self.assertEqual(transport.call_count, 2)
        self.assertEqual(sent_payloads[0], sent_payloads[1])
        self.assertEqual(sent_payloads[0]['request_uuid'], child_uuid)
        self.assertEqual(sent_payloads[0]['webhook_token'], child_token)
        parent = self._fresh_session()
        child = self._child()
        self.assertEqual(parent.state['confirmation_runs'], 1)
        self.assertEqual(child.request_uuid, child_uuid)
        self.assertEqual(child.request_phase, 'submitted')

    def test_child_submission_credit_failure_returns_idle_for_parent(self):
        token = self._wait_for_confirmation()
        with (
            patch(TRANSPORT, side_effect=InsufficientCreditError) as submit,
            patch.object(self.registry['iap.account'], '_send_no_credit_notification', autospec=True) as notify,
        ):
            response = self._resume_confirmation(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['result'], {
            'request_uuid': self.parent_request_uuid, 'responseState': 'idle',
        })
        submit.assert_called_once()
        notify.assert_called_once()
        parent = self._fresh_session()
        child = self._child()
        self.assertEqual(parent.loop_state, 'ready')
        self.assertEqual(child.loop_state, 'ready')
        self.assertEqual(child.request_result, {'kind': 'failure', 'code': 'insufficient_credit'})
        self.assertEqual([part['success'] for part in self._results(parent)], [True, False, False])
        self.assertEqual(parent.state['confirmation_runs'], 1)
        self.assertNotIn('suffix_runs', parent.state)
